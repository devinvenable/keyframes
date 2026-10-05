#!/usr/bin/env python3
"""Assemble beat-aligned sections from beatcut takes into one video.

Companion to beatcut.py: given an ordered list of sections (take:section
pairs resolved through each cut dir's manifest.json), re-extracts every
section from its MASTER take and splices them with beat-preserving
crossfades and per-section loudness control.

The existing section files are NOT crossfaded: they are butt-cut on
downbeats with zero handle, and overlapping them would slide every later
downbeat. Instead each chosen section is re-extracted from
recordings/perform_<id>.mkv at its manifest t_rec_start (which already
carries beatcut's cross-correlation timeline_correction) with a tail
HANDLE of --fade-beats extra beats. Video xfade (dissolve) + equal-power
audio acrossfade then consume ONLY handle material, so every section's
downbeat grid position in the output equals the sum of the exact section
durations before it. The tool asserts this arithmetically: the final
audio graph is teed to a PCM wav whose sample count must match the
planned duration (container/AAC durations are too sloppy for a ms-level
check), and the run fails loudly on drift.

Everything is one ffmpeg pass (per-input seek -> exact atrim -> gain ->
chained xfade/acrossfade -> encode), so no intermediate AAC padding can
shift a splice. The cost: the video is fully re-encoded once at the
share-mp4 settings — xfade forces a decode of every frame anyway, and a
copy/re-encode hybrid cannot keep one coherent h264 stream across splices.

Section entry grammar (CLI args or one-per-line --file, '#' comments):
    125936:3              newest recordings/cuts_*125936*_v* dir, section 3
    cuts_20261003_171223_v2:2   explicit cut dir (relative to recordings/)
    125936:3@-16          pin this section's loudness target to -16 LUFS
    125936:9@off          never gain this section (bit-identical level)
    125936:3,fade=0       hard cut (no handle) into the NEXT section
    125936:3@-16,fade=0.5 both

Loudness (--target-lufs) is boost-only: integrated LUFS is measured per
section straight from the master (ebur128); quiet sections are raised to
target through a lookahead limiter, hot sections are never lowered.

Sections cut from different-tempo takes cannot share a beat grid; mixed
bpms abort unless --force.

A sidecar <out>.json records the full recipe so any mix is reproducible.

Usage: beatmix.py 125936:3 171223:2 010307:4 [options]
"""
import argparse
import datetime
import json
from pathlib import Path
import re
import subprocess
import sys

# share-mp4 encode settings, matching beatcut.encode_clip
VIDEO_OPTS = ['-c:v', 'libx264', '-preset', 'medium', '-b:v', '2300k',
              '-maxrate', '2900k', '-bufsize', '5800k', '-g', '60',
              '-pix_fmt', 'yuv420p']
AUDIO_OPTS = ['-c:a', 'aac', '-b:a', '160k']
RATE = 48000
BPM_MISMATCH = 0.05      # bpm spread across sections that aborts without --force
DRIFT_BASE = 0.002       # s of allowed planned-vs-actual slack, plus ...
DRIFT_PER_SPLICE = 0.003  # ... per splice ("a few ms per splice")


def die(msg):
    raise SystemExit(f'beatmix: {msg}')


ENTRY = re.compile(r'^(?P<base>[^@,]+)(@(?P<gain>off|none|[-+]?\d+(\.\d+)?))?'
                   r'(?P<opts>(,[a-z]+=[^,]+)*)$')


def parse_entry(token):
    """One section spec -> dict(base, target, no_gain, fade)."""
    m = ENTRY.match(token.strip())
    if not m:
        die(f'cannot parse section entry {token!r}')
    entry = {'spec': token.strip(), 'base': m['base'],
             'target': None, 'no_gain': False, 'fade': None}
    if m['gain'] in ('off', 'none'):
        entry['no_gain'] = True
    elif m['gain'] is not None:
        entry['target'] = float(m['gain'])
    for opt in filter(None, (m['opts'] or '').split(',')):
        key, _, value = opt.partition('=')
        if key == 'fade':
            entry['fade'] = float(value)
            if entry['fade'] < 0:
                die(f'negative fade in {token!r}')
        else:
            die(f'unknown option {key!r} in {token!r}')
    return entry


def read_sections_file(path):
    tokens = []
    for line in Path(path).read_text().splitlines():
        line = line.split('#', 1)[0].strip()
        if line:
            tokens.append(line)
    return tokens


def resolve_cut_dir(base, recordings):
    """'125936' or an explicit dir -> Path of the cut dir."""
    candidate = Path(base)
    for root in (candidate, recordings / candidate):
        if root.is_dir():
            return root
    matches = sorted(recordings.glob(f'cuts_*{base}*'))
    if not matches:
        die(f'no cut dir matching {base!r} under {recordings}/')

    def version(path):
        m = re.search(r'_v(\d+)$', path.name)
        return int(m.group(1)) if m else 1
    best = max(version(m) for m in matches)
    newest = [m for m in matches if version(m) == best]
    if len(newest) > 1:
        die(f'{base!r} is ambiguous: {", ".join(p.name for p in newest)} '
            f'— name the dir explicitly')
    return newest[0]


def resolve_section(entry, recordings, manifests):
    """Attach cut dir, manifest clip, master path and grid to an entry."""
    base = entry['base']
    if base.endswith('.mp4'):            # direct section-file path
        path = Path(base) if Path(base).exists() else recordings / base
        if not path.exists():
            die(f'section file not found: {base}')
        cut_dir, clip_name = path.parent, path.name
        number = None
    else:
        head, sep, tail = base.rpartition(':')
        if not sep or not tail.isdigit():
            die(f'cannot parse section entry {entry["spec"]!r} '
                f'(expected take:section)')
        cut_dir = resolve_cut_dir(head, recordings)
        number, clip_name = int(tail), None
    if cut_dir not in manifests:
        manifest_path = cut_dir / 'manifest.json'
        if not manifest_path.exists():
            die(f'no manifest.json in {cut_dir}')
        manifests[cut_dir] = json.loads(manifest_path.read_text())
    manifest = manifests[cut_dir]
    if clip_name is not None:
        clips = [c for c in manifest['clips'] if c['name'] == clip_name]
    else:
        clips = [c for c in manifest['clips']
                 if re.fullmatch(f'section_{number:03d}(_\\w+)?\\.mp4', c['name'])]
    if not clips:
        want = clip_name or f'section_{number:03d}'
        die(f'{want} not found in {cut_dir}/manifest.json')
    clip = clips[0]
    if 't_rec_start' not in clip or 't_rec_end' not in clip:
        die(f'{cut_dir}/manifest.json clips lack t_rec_* — re-run beatcut '
            f'(older manifest format)')
    take = Path(manifest['take'])
    if not take.exists():
        alt = recordings / take.name
        if not alt.exists():
            die(f'master take not found: {take}')
        take = alt
    segment = manifest['segments'][clip['segment']]
    if clip['kind'] != 'section':
        print(f'WARNING: {cut_dir.name}/{clip["name"]} is a {clip["kind"]} '
              f'clip ({clip["beats"]} beats), not a full section')
    entry.update(cut_dir=cut_dir, clip=clip, take=take,
                 duration=clip['t_rec_end'] - clip['t_rec_start'],
                 period=segment['period'], bpm=segment['bpm'])
    return entry


def probe_duration(path):
    """Container duration (mkv streams report N/A per-stream)."""
    out = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'csv=p=0', str(path)],
        check=True, capture_output=True, text=True).stdout.strip()
    try:
        return float(out.splitlines()[0])
    except (IndexError, ValueError):
        return None


def probe_video(path):
    out = subprocess.run(
        ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
         'stream=width,height,avg_frame_rate', '-of', 'json', str(path)],
        check=True, capture_output=True, text=True).stdout
    stream = json.loads(out)['streams'][0]
    num, _, den = stream['avg_frame_rate'].partition('/')
    return stream['width'], stream['height'], float(num) / float(den or 1)


def measure_lufs(take, start, duration):
    """Integrated LUFS of [start, start+duration) of the master's audio."""
    result = subprocess.run(
        ['ffmpeg', '-hide_banner', '-nostats', '-ss', f'{start:.6f}',
         '-t', f'{duration:.6f}', '-i', str(take), '-map', '0:a:0',
         '-af', 'ebur128=framelog=quiet', '-f', 'null', '-'],
        check=True, capture_output=True, text=True)
    tail = result.stderr[result.stderr.rfind('Integrated loudness'):]
    m = re.search(r'I:\s*([-\d.]+)\s*LUFS', tail)
    if not m:
        die(f'could not measure LUFS of {take.name} @ {start:.2f}s')
    return float(m.group(1))


def build_plan(entries, fade_beats, target_lufs):
    """Extraction + splice plan. All grid arithmetic lives here.

    Each section is extracted at its manifest t_rec_start for
    duration + handle, where handle = fade * that section's beat period
    (0 for the last section — nothing follows). The crossfade into the
    next section consumes exactly the handle, so section k's downbeat
    lands at sum(duration[0..k-1]) in the output: planned_duration is
    that sum, and assemble() enforces it.
    """
    sections = []
    for index, entry in enumerate(entries):
        last = index == len(entries) - 1
        fade = entry['fade'] if entry['fade'] is not None else fade_beats
        handle = 0.0 if last else fade * entry['period']
        target = None if entry['no_gain'] else (
            entry['target'] if entry['target'] is not None else target_lufs)
        sections.append({
            'spec': entry['spec'], 'cut_dir': str(entry['cut_dir']),
            'clip': entry['clip']['name'], 'take': str(entry['take']),
            't_rec_start': entry['clip']['t_rec_start'],
            'duration': round(entry['duration'], 6),
            'bpm': entry['bpm'], 'period': entry['period'],
            'fade_beats': 0.0 if last else fade,
            'handle': round(handle, 6),
            'extract_duration': round(entry['duration'] + handle, 6),
            'target_lufs': target, 'gain_db': 0.0, 'measured_lufs': None,
        })
    return {'sections': sections,
            'planned_duration': round(sum(s['duration'] for s in sections), 6)}


def apply_gains(plan):
    """Boost-only normalization: measure, raise quiet sections to target."""
    for section in plan['sections']:
        if section['target_lufs'] is None:
            continue
        measured = measure_lufs(Path(section['take']), section['t_rec_start'],
                                section['duration'])
        section['measured_lufs'] = measured
        gain = section['target_lufs'] - measured
        section['gain_db'] = round(gain, 2) if gain > 0.05 else 0.0
        verdict = (f'+{section["gain_db"]}dB' if section['gain_db']
                   else 'already at/above target, untouched')
        print(f'  {section["clip"]} [{Path(section["cut_dir"]).name}]: '
              f'{measured:.1f} LUFS -> target {section["target_lufs"]} '
              f'({verdict})')


def build_ffmpeg(plan, out, drift_wav):
    """One-pass command: seek+trim each master, gain, chain fades, encode.

    The final audio is split: one branch is AAC-encoded into the mp4, the
    other written as PCM to drift_wav so assemble() can count samples —
    the only ms-accurate measure of the assembled duration.
    """
    sections = plan['sections']
    width, height, fps = probe_video(Path(sections[0]['take']))
    cmd = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y']
    for s in sections:
        cmd += ['-ss', f'{s["t_rec_start"]:.6f}',
                '-t', f'{s["extract_duration"] + 1.0:.6f}', '-i', s['take']]
    graph = []
    for i, s in enumerate(sections):
        graph.append(
            f'[{i}:v]trim=duration={s["extract_duration"]:.6f},'
            f'setpts=PTS-STARTPTS,fps={fps:g},scale={width}:{height},'
            f'format=yuv420p,settb=AVTB[v{i}]')
        # aresample pins decoded samples to container timestamps (the
        # lesson-15 discipline beatcut's analysis uses), atrim makes the
        # length sample-exact so acrossfade consumes exactly the handle.
        audio = (f'[{i}:a]aresample={RATE}:async=1000:first_pts=0,'
                 f'aformat=sample_fmts=fltp:channel_layouts=stereo,'
                 f'atrim=duration={s["extract_duration"]:.6f},'
                 f'asetpts=PTS-STARTPTS')
        if s['gain_db'] > 0:
            # level=0: ffmpeg 7.x auto-level default would renormalize the
            # whole section; latency=1 compensates the lookahead delay so
            # the limiter cannot shift the grid.
            audio += (f',volume={s["gain_db"]}dB'
                      f',alimiter=limit=0.97:latency=1:level=0')
        graph.append(audio + f'[a{i}]')
    current_v, current_a = '[v0]', '[a0]'
    elapsed = sections[0]['duration']
    for i in range(1, len(sections)):
        handle = sections[i - 1]['handle']
        if handle > 0:
            graph.append(f'{current_v}[v{i}]xfade=transition=fade:'
                         f'duration={handle:.6f}:offset={elapsed:.6f}[vx{i}]')
            graph.append(f'{current_a}[a{i}]acrossfade=d={handle:.6f}:'
                         f'c1=qsin:c2=qsin[ax{i}]')
        else:
            graph.append(f'{current_v}[v{i}]concat=n=2:v=1:a=0[vx{i}]')
            graph.append(f'{current_a}[a{i}]concat=n=2:v=0:a=1[ax{i}]')
        current_v, current_a = f'[vx{i}]', f'[ax{i}]'
        elapsed += sections[i]['duration']
    graph.append(f'{current_a}asplit=2[aout][acheck]')
    cmd += ['-filter_complex', ';'.join(graph),
            '-map', current_v, '-map', '[aout]',
            *VIDEO_OPTS, *AUDIO_OPTS, '-movflags', '+faststart', str(out),
            '-map', '[acheck]', '-c:a', 'pcm_f32le', str(drift_wav)]
    return cmd


def assemble(plan, out):
    """Run the one-pass assembly and enforce the grid arithmetic."""
    drift_wav = out.with_suffix('.drift_check.wav')
    cmd = build_ffmpeg(plan, out, drift_wav)
    print(f'assembling {len(plan["sections"])} sections -> {out} ...')
    subprocess.run(cmd, check=True)
    import soundfile
    actual = soundfile.info(str(drift_wav)).frames / RATE
    drift_wav.unlink()
    planned = plan['planned_duration']
    splices = len(plan['sections']) - 1
    tolerance = DRIFT_BASE + DRIFT_PER_SPLICE * splices
    drift = actual - planned
    print(f'planned {planned:.4f}s, assembled {actual:.4f}s '
          f'(drift {drift * 1000:+.1f}ms, tolerance '
          f'\u00b1{tolerance * 1000:.0f}ms over {splices} splices)')
    plan['assembled_duration'] = round(actual, 6)
    plan['drift_ms'] = round(drift * 1000, 2)
    if abs(drift) > tolerance:
        die(f'GRID DRIFT: assembled duration is off by '
            f'{drift * 1000:+.1f}ms (> {tolerance * 1000:.0f}ms) — '
            f'a splice consumed non-handle material; {out} is NOT '
            f'beat-aligned, do not use it')
    return actual


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='\n'.join(__doc__.splitlines()[1:]))
    parser.add_argument('sections', nargs='*',
                        help="take:section entries, e.g. 125936:3 "
                             "171223:2@-16 010307:4,fade=0")
    parser.add_argument('--file', type=Path,
                        help='sections file, one entry per line (# comments)')
    parser.add_argument('--fade-beats', type=float, default=1.0,
                        help='tail handle + crossfade length in beats '
                             '(default 1; 0 = hard cut). Per-entry '
                             'override: ...,fade=N')
    parser.add_argument('--target-lufs', type=float, default=None,
                        help='boost-only loudness target (integrated LUFS); '
                             'per-entry override take:sec@-16, disable with '
                             'take:sec@off')
    parser.add_argument('--out', type=Path, default=None,
                        help='output path (default '
                             'recordings/beatmix_<timestamp>.mp4)')
    parser.add_argument('--recordings', type=Path, default=Path('recordings'),
                        help='recordings root for resolving take ids')
    parser.add_argument('--force', action='store_true',
                        help='proceed despite mixed tempos')
    parser.add_argument('--dry-run', action='store_true',
                        help='print the plan without encoding')
    args = parser.parse_args(argv)

    if args.fade_beats < 0:
        die('--fade-beats must be >= 0')
    tokens = list(args.sections)
    if args.file:
        tokens += read_sections_file(args.file)
    if len(tokens) < 1:
        die('no sections given')
    manifests = {}
    entries = [resolve_section(parse_entry(t), args.recordings, manifests)
               for t in tokens]

    bpms = sorted({round(e['bpm'], 3) for e in entries})
    if bpms[-1] - bpms[0] > BPM_MISMATCH:
        detail = ', '.join(f'{e["spec"]}={e["bpm"]:.3f}' for e in entries)
        message = (f'MIXED TEMPOS: sections span {bpms[0]:.3f}-'
                   f'{bpms[-1]:.3f} bpm — their beat grids cannot align '
                   f'across a crossfade ({detail})')
        if not args.force:
            die(message + '. Pass --force to assemble anyway.')
        print(f'WARNING: {message} (continuing under --force)')

    plan = build_plan(entries, args.fade_beats, args.target_lufs)
    for section, entry in zip(plan['sections'], entries):
        take_duration = probe_duration(entry['take']) or float('inf')
        if section['t_rec_start'] + section['extract_duration'] > take_duration:
            die(f'{section["spec"]}: handle of {section["handle"]:.3f}s runs '
                f'past the end of {entry["take"].name} — use ,fade=0 on '
                f'this entry or pick an earlier section')
    if any(s['target_lufs'] is not None for s in plan['sections']):
        print('measuring section loudness ...')
        apply_gains(plan)

    out = args.out or args.recordings / (
        'beatmix_' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S') + '.mp4')
    for s in plan['sections']:
        print(f'  {s["spec"]:<28} {Path(s["cut_dir"]).name}/{s["clip"]} '
              f'{s["duration"]:.3f}s @{s["bpm"]:.3f}bpm '
              f'handle={s["handle"]:.3f}s gain=+{s["gain_db"]}dB')
    if args.dry_run:
        print(json.dumps(plan, indent=2))
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    assemble(plan, out)
    recipe = {'tool': 'beatmix', 'created': datetime.datetime.now().isoformat(
        timespec='seconds'), 'out': str(out),
        'fade_beats_default': args.fade_beats,
        'target_lufs_default': args.target_lufs, **plan}
    out.with_suffix(out.suffix + '.json').write_text(
        json.dumps(recipe, indent=2) + '\n')
    print(f'wrote {out} + recipe {out.name}.json')


if __name__ == '__main__':
    main()
