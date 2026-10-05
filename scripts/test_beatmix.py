"""beatmix tests on small synthetic takes (seconds, not minutes).

Each synthetic "master" is unique seeded noise (so cross-correlation
placement is unambiguous) with click transients on a 120bpm grid, muxed
with a flat color video. Manifests are fabricated with known-true t_rec
values, so every grid position in the output has an exact ground truth.

Run: python3 -m pytest scripts/test_beatmix.py
"""
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest
import soundfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import beatmix  # noqa: E402

RATE = 48000
PERIOD = 0.5          # 120 bpm
SECTION_BEATS = 4     # tiny sections: 2s


def make_take(path, seed, level=0.3, duration=12.0):
    """Master take: seeded noise + beat clicks, color video, aac/mp4."""
    rng = np.random.default_rng(seed)
    samples = rng.standard_normal(int(duration * RATE)).astype(np.float32) * level
    # band-limit below 8kHz: AAC's HF cutoff on full-band noise would
    # read as a level change under ebur128's K-weighting
    spectrum = np.fft.rfft(samples)
    spectrum[int(8000 * duration):] = 0
    samples = np.fft.irfft(spectrum, len(samples)).astype(np.float32)
    click = np.hanning(960).astype(np.float32)
    for beat in np.arange(0.0, duration, PERIOD):
        at = int(beat * RATE)
        samples[at:at + 960] += click[:len(samples) - at] * level * 3
    wav = path.with_suffix('.wav')
    stereo = np.stack([samples, samples], axis=1)  # real masters are stereo
    soundfile.write(str(wav), np.clip(stereo, -0.99, 0.99), RATE)
    subprocess.run(
        ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
         '-f', 'lavfi', '-i', f'color=c=gray:s=160x90:r=30:d={duration}',
         '-i', str(wav), '-shortest', '-c:v', 'libx264', '-preset',
         'ultrafast', '-c:a', 'aac', '-b:a', '192k', str(path)], check=True)
    wav.unlink()


def make_cut_dir(recordings, take_id, seed, bpm=120.0, level=0.3):
    take = recordings / f'perform_{take_id}.mkv'
    make_take(take, seed, level=level)
    period = 60.0 / bpm
    clips = []
    for n in range(1, 4):
        start = 2.0 + (n - 1) * SECTION_BEATS * period
        clips.append({'name': f'section_{n:03d}.mp4', 'kind': 'section',
                      'segment': 0, 't_rec_start': round(start, 4),
                      't_rec_end': round(start + SECTION_BEATS * period, 4),
                      'duration': SECTION_BEATS * period,
                      'beats': SECTION_BEATS})
    cut_dir = recordings / f'cuts_{take_id}_v2'
    cut_dir.mkdir(parents=True)
    (cut_dir / 'manifest.json').write_text(json.dumps({
        'take': str(take), 'take_id': take_id, 'timeline_correction': 0.0,
        'segments': [{'start': 0.0, 'stop': 12.0, 'period': period,
                      'offset': 0.0, 'bpm': bpm, 'downbeat_phase': 0}],
        'clips': clips}))
    return cut_dir


@pytest.fixture(scope='module')
def rig(tmp_path_factory):
    recordings = tmp_path_factory.mktemp('recordings')
    make_cut_dir(recordings, 'AAAA', seed=1, level=0.3)
    make_cut_dir(recordings, 'BBBB', seed=2, level=0.03)   # quiet take
    make_cut_dir(recordings, 'CCCC', seed=3, bpm=99.0)     # other tempo
    return recordings


def decode(path, out, start=None, duration=None):
    cmd = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y']
    if start is not None:
        cmd += ['-ss', f'{start:.6f}', '-t', f'{duration:.6f}']
    cmd += ['-i', str(path), '-map', '0:a:0', '-ac', '1', '-ar', str(RATE),
            '-c:a', 'pcm_f32le', str(out)]
    subprocess.run(cmd, check=True)


def placement_offset_ms(mix, take, out_start, rec_start, tmp):
    """Cross-correlation offset of the output window vs its master source."""
    a, b = tmp / 'out.wav', tmp / 'src.wav'
    decode(mix, a, out_start + 0.2, 1.2)
    decode(take, b, rec_start + 0.2 - 0.05, 1.3)
    needle, _ = soundfile.read(str(a))
    hay, _ = soundfile.read(str(b))
    corr = np.correlate(hay, needle[:RATE], mode='valid')
    return (int(np.argmax(corr)) / RATE - 0.05) * 1000


def lufs(path, start, duration):
    return beatmix.measure_lufs(Path(path), start, duration)


# ---------------------------------------------------------------- parsing

def test_parse_entry_forms():
    e = beatmix.parse_entry('125936:3')
    assert (e['base'], e['target'], e['no_gain'], e['fade']) == \
        ('125936:3', None, False, None)
    e = beatmix.parse_entry('125936:3@-16.5')
    assert e['target'] == -16.5 and not e['no_gain']
    e = beatmix.parse_entry('125936:3@off,fade=0')
    assert e['no_gain'] and e['fade'] == 0.0
    e = beatmix.parse_entry('dir/section_003.mp4,fade=2')
    assert e['base'] == 'dir/section_003.mp4' and e['fade'] == 2.0
    with pytest.raises(SystemExit):
        beatmix.parse_entry('125936:3,bogus=1')


def test_resolve_newest_version(rig):
    v3 = rig / 'cuts_AAAA_v3'
    v3.mkdir()
    try:
        assert beatmix.resolve_cut_dir('AAAA', rig) == v3
    finally:
        v3.rmdir()
    assert beatmix.resolve_cut_dir('AAAA', rig) == rig / 'cuts_AAAA_v2'


def test_mixed_tempo_guard(rig, tmp_path):
    with pytest.raises(SystemExit, match='MIXED TEMPOS'):
        beatmix.main(['--recordings', str(rig), '--dry-run',
                      'AAAA:1', 'CCCC:1'])
    # --force downgrades it to a warning
    beatmix.main(['--recordings', str(rig), '--dry-run', '--force',
                  'AAAA:1', 'CCCC:1'])


def test_handle_past_take_end(rig):
    # section_003 of AAAA ends at 8.0s of a 12s take: a 10-beat handle
    # (5s) cannot be extracted.
    with pytest.raises(SystemExit, match='runs past the end'):
        beatmix.main(['--recordings', str(rig), '--fade-beats', '10',
                      'AAAA:3', 'BBBB:1'])


# ---------------------------------------------------------------- assembly

def test_assembly_grid_and_loudness(rig, tmp_path):
    """3 cross-take sections, one fade + one hard cut, boost-only gain."""
    out = tmp_path / 'mix.mp4'
    beatmix.main(['--recordings', str(rig), '--target-lufs', '-18',
                  'AAAA:1', 'BBBB:2,fade=0', 'AAAA:3@off',
                  '--out', str(out)])
    recipe = json.loads(out.with_suffix('.mp4.json').read_text())
    sections = recipe['sections']
    duration = sections[0]['duration']
    assert abs(recipe['drift_ms']) < 2.0
    assert abs(recipe['assembled_duration'] - 3 * duration) < 0.005

    # every section's content sits exactly at its planned grid position
    for k, s in enumerate(sections):
        off = placement_offset_ms(out, s['take'], k * duration,
                                  s['t_rec_start'], tmp_path)
        assert abs(off) <= 3.0, f'section {k} placed {off:+.1f}ms off'

    # quiet section boosted to target +-1 LU in the OUTPUT (measured
    # after the incoming fade window, which still carries hot handle
    # material from section 0 — negligible on real 19s sections, not on
    # 2s test ones)
    assert sections[1]['gain_db'] > 3.0
    fade = sections[0]['handle']
    boosted = lufs(out, 1 * duration + fade + 0.05, duration - fade - 0.1)
    assert abs(boosted - (-18.0)) <= 1.0
    # hot section not lowered; @off section's level untouched
    assert sections[0]['gain_db'] == 0.0 and sections[2]['gain_db'] == 0.0
    untouched = lufs(out, 2 * duration + 0.1, duration - 0.2)
    source = lufs(sections[2]['take'], sections[2]['t_rec_start'] + 0.1,
                  duration - 0.2)
    assert abs(untouched - source) <= 0.5

    # sidecar carries the full recipe
    assert [s['spec'] for s in sections] == \
        ['AAAA:1', 'BBBB:2,fade=0', 'AAAA:3@off']
    assert sections[0]['handle'] > 0 and sections[1]['handle'] == 0


def test_drift_assertion_fails_on_mishandled_extract(rig, tmp_path):
    """A mis-sized extract MUST fail the grid assertion, loudly."""
    entries = [beatmix.resolve_section(beatmix.parse_entry(t), rig, {})
               for t in ('AAAA:1', 'BBBB:1')]
    plan = beatmix.build_plan(entries, 1.0, None)
    # extract 60ms short without telling the planner: the acrossfade then
    # eats non-handle material and every later downbeat slides early.
    plan['sections'][0]['extract_duration'] -= 0.060
    with pytest.raises(SystemExit, match='GRID DRIFT'):
        beatmix.assemble(plan, tmp_path / 'bad.mp4')
    good = beatmix.build_plan(entries, 1.0, None)
    beatmix.assemble(good, tmp_path / 'good.mp4')  # control: passes
