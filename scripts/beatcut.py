#!/usr/bin/env python3
"""Cut a performance take into beat-aligned N-measure clips from its mixer audio.

Reuses showsync's beat analyzer (onset extraction + robust grid fitting) on the
take's own audio track, so cut times live on the master timeline. Tempo is
assumed near-constant per song; a live set with several songs may re-anchor
phase between songs, so the grid is fit per phase-stable segment. Meter is
assumed 4/4 (--beats-per-bar); the downbeat is chosen per segment as the beat
phase carrying the most kick-band energy.

Beat PHASE is anchored to kick-drum attacks: in four-on-the-floor material the
kick is the quarter-note pulse, and the general onset population (hi-hats,
stabs, delayed synth attacks) can sit a 16th off it and pull an IRLS fit onto
the wrong phase. Kick onsets are extracted from a 40-130 Hz band envelope and
weighted by attack sharpness (envelope derivative), because sustained bass
shares the band at off-kick phases but swells instead of hitting. The general
onsets remain the fallback where kick density is too low, seeded with the
kick-derived phase so it carries through breakdowns.

Outputs <out>/section_XXX*.mp4 (re-encoded for frame-accurate cuts, share-mp4
settings + faststart) and <out>/manifest.json with the grids and cut times.

Usage: beatcut.py recordings/perform_YYYYMMDD_HHMMSS.mkv [options]
"""
import argparse
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'showsync'))
from showsync.bpmdetect import _features, _onsets  # noqa: E402

BUCKET = 10.0          # seconds per phase-track bucket
PHASE_STEP = 0.010     # sustained median-residual jump that splits segments (s)
INLIER = 0.08          # beat-fraction residual counted as on-grid


def ffprobe_json(path, *args):
    out = subprocess.run(['ffprobe', '-v', 'error', '-of', 'json', *args, str(path)],
                         check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def calibrate_timeline(take, wav_path, rate=48000):
    """Measured offset mapping analysis time to ffmpeg -ss master time.

    Cross-correlates short seek-decoded windows of the master against the
    analysis wav at three anchors. Returns (median offset, max deviation):
    master_time = analysis_time + offset. Trusting container start_time is
    not enough — live captures can drift between sample count and pts.
    """
    import soundfile
    info = soundfile.info(wav_path)
    duration = info.frames / info.samplerate
    offsets = []
    for fraction in (.2, .5, .8):
        ss = fraction * duration
        with tempfile.NamedTemporaryFile(suffix='.wav') as probe:
            subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                            '-ss', f'{ss:.6f}', '-i', str(take), '-map', '0:a:0',
                            '-t', '1.5', '-ac', '1', '-ar', str(rate),
                            '-c:a', 'pcm_f32le', probe.name], check=True)
            needle, _ = soundfile.read(probe.name)
        lo = max(0.0, ss - .3)
        window, _ = soundfile.read(wav_path, start=int(lo * info.samplerate),
                                   frames=int(2.1 * info.samplerate))
        if window.ndim > 1:
            window = window.mean(axis=1)
        if info.samplerate != rate:
            raise SystemExit('unexpected analysis wav rate')
        needle = needle[:rate]
        if len(window) < len(needle) + 100 or float(np.abs(needle).max()) < 1e-5:
            continue
        corr = np.correlate(window, needle, mode='valid')
        offsets.append(ss - (lo + int(np.argmax(corr)) / rate))
    if not offsets:
        return 0.0, 0.0
    median = float(np.median(offsets))
    return median, float(max(abs(o - median) for o in offsets))


def kick_onsets(wav_path, lo_hz=40.0, hi_hz=130.0):
    """Kick attack times + sharpness weights from the 40-130 Hz band.

    Band-pass by FFT, square to a 1 kHz power envelope, then peak-pick the
    POSITIVE DERIVATIVE of the amplitude envelope. The derivative is the
    discriminator: bass lines share this band — often louder than the kick —
    but swell over ~100ms where a kick rises in a few ms, so attack slope
    separates them where peak energy cannot.
    """
    import soundfile
    data, rate = soundfile.read(wav_path, dtype='float32')
    if data.ndim > 1:
        data = data.mean(axis=1)
    spectrum = np.fft.rfft(data)
    bins = np.fft.rfftfreq(len(data), 1 / rate)
    spectrum[(bins < lo_hz) | (bins > hi_hz)] = 0
    band = np.fft.irfft(spectrum, len(data))
    step = rate // 1000
    frames = len(band) // step * step
    envelope = (band[:frames] ** 2).reshape(-1, step).mean(axis=1)
    envelope = np.convolve(envelope, np.full(10, .1), mode='same')
    slope = np.diff(np.sqrt(envelope), prepend=0)
    slope = np.convolve(np.maximum(slope, 0), np.full(5, .2), mode='same')
    if not len(slope) or np.percentile(slope, 99) < 1e-8:
        return np.empty(0), np.empty(0)
    threshold = np.percentile(slope, 99) * .15
    peaks = np.flatnonzero((slope >= np.roll(slope, 1)) &
                           (slope > np.roll(slope, -1)) & (slope > threshold))
    times, weights = [], []
    for peak in peaks:
        if times and peak / 1000 - times[-1] < .25:
            if slope[peak] > weights[-1]:
                times[-1], weights[-1] = peak / 1000, float(slope[peak])
        else:
            times.append(peak / 1000)
            weights.append(float(slope[peak]))
    return np.asarray(times), np.asarray(weights)


def irls_fit(times, weights, period, offset, iterations=12):
    """Robust period/offset refinement, same scheme as bpmdetect._fit."""
    for _ in range(iterations):
        beats = np.rint((times - offset) / period)
        residual = times - (offset + beats * period)
        mask = np.abs(residual) < period * INLIER
        if mask.sum() < 12:
            return None
        x, y = beats[mask], times[mask]
        w = weights[mask] / np.maximum(1, np.abs(residual[mask]) / .008)
        xm, ym = np.average(x, weights=w), np.average(y, weights=w)
        period = np.sum(w * (x - xm) * (y - ym)) / np.sum(w * (x - xm) ** 2)
        offset = ym - period * xm
    return period, offset


def global_grid(times, weights):
    """Coherence scan over autocorrelation-free candidate range, then IRLS."""
    span = times[-1] - times[0]
    best = None
    frequencies = np.arange(60 / 60, 200 / 60, .01 / span)
    for start in range(0, len(frequencies), 64):
        trial = frequencies[start:start + 64]
        phases = np.exp(2j * np.pi * trial[:, None] * times)
        coherence = phases @ weights / weights.sum()
        index = int(np.argmax(np.abs(coherence)))
        if best is None or abs(coherence[index]) > best[0]:
            best = (abs(coherence[index]), trial[index],
                    np.angle(coherence[index]) / (2 * np.pi))
    _, frequency, phase = best
    period = 1 / frequency
    offset = (phase / frequency) % period
    # Prefer the quarter-note pulse: a fast grid whose odd beats carry little
    # onset weight is really 8th notes of the half tempo.
    fit = irls_fit(times, weights, period, offset)
    if fit is None:
        raise SystemExit('no stable beat grid found')
    period, offset = fit
    if 60 / period > 140:
        beats = np.rint((times - offset) / period)
        residual = times - (offset + beats * period)
        mask = np.abs(residual) < period * INLIER
        for shift in (0, 1):
            halved = irls_fit(times, weights, period * 2, offset + shift * period)
            if halved is None:
                continue
            on = weights[mask & (np.rint((times - offset) / period) % 2 == shift)].sum()
            total = weights[mask].sum()
            if on > .40 * total:
                return halved
    return period, offset


def phase_track(times, weights, residual, duration):
    """Weighted median residual per bucket; None where support is thin."""
    track = []
    mask = np.abs(residual) < INLIER
    for b0 in np.arange(0, duration, BUCKET):
        sel = mask & (times >= b0) & (times < b0 + BUCKET)
        track.append(float(np.median(residual[sel])) if sel.sum() >= 5 else None)
    return track


def split_segments(track, times, residual, period, duration):
    """Boundaries where the bucket phase steps and stays stepped."""
    boundaries = []
    previous = None
    for i, value in enumerate(track):
        if value is None:
            continue
        if previous is not None and abs(value - previous[1]) > PHASE_STEP:
            following = [v for v in track[i:i + 3] if v is not None]
            if following and all(abs(v - previous[1]) > PHASE_STEP for v in following):
                boundaries.append(refine_boundary(times, residual, period,
                                                  previous[0] * BUCKET, (i + 1) * BUCKET,
                                                  previous[1], value))
        previous = (i, value)
    edges = [0.0, *boundaries, duration]
    return [(edges[i], edges[i + 1]) for i in range(len(edges) - 1)]


def refine_boundary(times, residual, period, lo, hi, phase_a, phase_b):
    """Place the split where onsets stop matching phase A and start matching B."""
    sel = (times >= lo) & (times <= hi) & (np.abs(residual) < INLIER)
    if sel.sum() < 4:
        return (lo + hi) / 2
    t = times[sel]
    closer_b = np.abs(residual[sel] - phase_b) < np.abs(residual[sel] - phase_a)
    best = (len(t) + 1, (lo + hi) / 2)
    for k in range(len(t) + 1):
        wrong = int(closer_b[:k].sum() + (~closer_b[k:]).sum())
        cut = t[k - 1] + 1e-3 if k else t[0] - 1e-3
        if wrong < best[0]:
            best = (wrong, cut)
    return best[1]


def downbeat_phase(kick, period, offset, start, stop, beats_per_bar):
    """Beat index mod beats_per_bar with strongest kick-band support."""
    first = math.ceil((start - offset) / period)
    last = math.floor((stop - offset) / period)
    scores = np.zeros(beats_per_bar)
    for beat in range(first, last + 1):
        center = int(round((offset + beat * period) * 100 + 1.13))
        window = kick[max(0, center - 3):center + 4]
        if len(window):
            scores[beat % beats_per_bar] += window.max()
    return int(np.argmax(scores))


def music_entry(times, period):
    """First onset with sustained rhythmic support after it.

    Deliberately no on-grid condition: the general onset population may sit a
    16th off the kick-anchored grid, which says nothing about where music
    starts — the sustained-support requirement already rejects stray noise.
    """
    for t in times:
        if ((times >= t) & (times < t + 8 * period)).sum() >= 4:
            return float(t)
    return float(times[0]) if len(times) else 0.0


def loud_entry(power, lo, hi, threshold=.15):
    """First sustained loud activity inside [lo, hi); None when there is none.

    Same idea as bpmdetect._music_entry: brief hits (count-ins, swells) cross
    the level briefly; the real entry keeps most of the following second
    active. Used to anchor the 8-measure phrase grid on the drop rather than
    on quiet intro material.
    """
    smooth = np.convolve(power[int(lo * 1000):int(hi * 1000)],
                         np.full(100, .01), mode='same')
    if len(smooth) < 1500:
        return None
    loud = np.percentile(smooth, 95)
    if loud < 1e-8:
        return None
    active = smooth > loud * threshold
    busy = np.convolve(active, np.full(1000, .001), mode='valid')
    hits = np.flatnonzero(active[:len(busy)] & (busy > .7))
    return lo + hits[0] / 1000 if len(hits) else None


def encode_clip(master, start, duration, out, with_click=None, bitrate='2300k'):
    """Frame-accurate re-encode cut matching the share-mp4 settings."""
    cmd = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
           '-ss', f'{start:.6f}', '-i', str(master)]
    if with_click is not None:
        cmd += ['-i', str(with_click),
                '-filter_complex', '[0:a][1:a]amix=inputs=2:duration=first:normalize=0[a]',
                '-map', '0:v:0', '-map', '[a]']
    else:
        cmd += ['-map', '0:v:0', '-map', '0:a:0']
    cmd += ['-t', f'{duration:.6f}',
            '-c:v', 'libx264', '-preset', 'medium',
            '-b:v', bitrate, '-maxrate', '2900k', '-bufsize', '5800k',
            '-g', '60', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-b:a', '160k', '-movflags', '+faststart', str(out)]
    subprocess.run(cmd, check=True)


def write_click_wav(path, duration, beat_times, beats_per_bar, phase, rate=48000):
    """Tick track: accented sine on downbeats, softer on other beats."""
    samples = np.zeros(int(duration * rate), dtype=np.float32)
    tick = (np.sin(2 * np.pi * 1600 * np.arange(int(.03 * rate)) / rate)
            * np.exp(-np.arange(int(.03 * rate)) / (.006 * rate))).astype(np.float32)
    accent = (np.sin(2 * np.pi * 2400 * np.arange(int(.04 * rate)) / rate)
              * np.exp(-np.arange(int(.04 * rate)) / (.008 * rate))).astype(np.float32)
    for index, t in beat_times:
        at = int(round(t * rate))
        pulse = accent if index % beats_per_bar == phase else tick * .5
        end = min(len(samples), at + len(pulse))
        if at >= 0 and at < len(samples):
            samples[at:end] += pulse[:end - at]
    import soundfile
    soundfile.write(str(path), samples * .5, rate)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('take', type=Path, help='master take (.mkv)')
    parser.add_argument('--out', type=Path, default=None,
                        help='output dir (default recordings/cuts_<take-id>/)')
    parser.add_argument('--measures', type=int, default=8, help='measures per section')
    parser.add_argument('--beats-per-bar', type=int, default=4, help='assumed meter')
    parser.add_argument('--clicks', type=int, default=3,
                        help='render N sample clips with click overlay for verification')
    parser.add_argument('--analyze-only', action='store_true',
                        help='print grids and cut plan without encoding')
    args = parser.parse_args()

    take = args.take.resolve()
    take_id = take.stem.replace('perform_', '')
    out = args.out or take.parent / f'cuts_{take_id}'
    section_beats = args.measures * args.beats_per_bar

    print(f'analyzing {take.name} ...')
    with tempfile.NamedTemporaryFile(suffix='.wav', delete_on_close=False) as temp:
        temp.close()
        # aresample pins the decoded samples to the container timestamps
        # (live captures drift tens of ppm between sample count and pts), so
        # analysis time and ffmpeg -ss cut time share one timeline.
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                        '-i', str(take), '-map', '0:a:0',
                        '-af', 'aresample=async=1000:first_pts=0',
                        '-c:a', 'pcm_f32le', temp.name], check=True)
        envelope, power, kick = _features(temp.name, lambda: None)
        start_correction, spread = calibrate_timeline(take, temp.name)
        kick_times, kick_weights = kick_onsets(temp.name)
    print(f'timeline calibration: analysis -> master {start_correction * 1000:+.1f}ms '
          f'(spread {spread * 1000:.1f}ms)')
    if spread > 0.005:
        print('WARNING: nonuniform timeline drift; cuts may be off by up to '
              f'{spread * 1000:.0f}ms')
    duration = len(power) / 1000
    onsets = _onsets(envelope, power)
    if onsets is None:
        raise SystemExit('no rhythmic content found')
    _, times, weights = onsets
    weights = np.minimum(weights, np.percentile(weights, 90))

    # Primary phase population: kick attacks. The general onsets only drive
    # the grid when the whole take is kick-sparse (ambient material).
    use_kick = len(kick_times) >= 100
    if use_kick:
        kick_weights = np.minimum(kick_weights, np.percentile(kick_weights, 90))
        fit_times, fit_weights = kick_times, kick_weights
    else:
        print(f'only {len(kick_times)} kick onsets; anchoring to general onsets')
        fit_times, fit_weights = times, weights

    period, offset = global_grid(fit_times, fit_weights)
    beats = np.rint((fit_times - offset) / period)
    residual = fit_times - (offset + beats * period)
    track = phase_track(fit_times, fit_weights, residual, duration)
    segments = split_segments(track, fit_times, residual, period, duration)

    def fit_span(lo, hi):
        sel = (fit_times >= lo) & (fit_times < hi)
        t, w = fit_times[sel], fit_weights[sel]
        source = 'kick' if use_kick else 'onsets'
        if use_kick and sel.sum() < 30:
            # Too few kicks to fit (breakdown / ambient span): refit on the
            # general onsets seeded with the kick-derived grid. IRLS only
            # admits inliers near the seed phase, so if the general
            # population sits off the kick phase it simply keeps the seed —
            # the kick phase is carried through the gap either way.
            source = 'onsets-kick-seeded'
            gsel = (times >= lo) & (times < hi)
            t, w = times[gsel], weights[gsel]
        fit = irls_fit(t, w, period, offset) or (period, offset)
        p, o = fit
        sel_in = np.abs(t - (o + np.rint((t - o) / p) * p)) < p * INLIER
        res = t[sel_in] - (o + np.rint((t[sel_in] - o) / p) * p)
        return {'start': lo, 'stop': hi, 'period': p, 'offset': o, 'bpm': 60 / p,
                'phase_source': source,
                'onsets_on_grid': int(sel_in.sum()),
                'residual_p90_ms': float(np.quantile(np.abs(res), .9) * 1000)
                if sel_in.sum() else None}

    def boundary_gap(a, b, at):
        """Disagreement (s) between two grids' nearest beat at a boundary."""
        beat_a = a['offset'] + round((at - a['offset']) / a['period']) * a['period']
        beat_b = b['offset'] + round((at - b['offset']) / b['period']) * b['period']
        return abs(beat_a - beat_b)

    grids = [fit_span(lo, hi) for lo, hi in segments]
    # The bucket tracker over-splits: support gaps let sub-threshold wander
    # accumulate into an apparent step. Keep a boundary only when the grids
    # fit independently on each side genuinely disagree there. 8ms sits
    # between IRLS fit noise (~1-3ms) and a real live re-anchor (14ms+).
    index = 0
    while index + 1 < len(grids):
        a, b = grids[index], grids[index + 1]
        if boundary_gap(a, b, b['start']) < .008:
            grids[index:index + 2] = [fit_span(a['start'], b['stop'])]
        else:
            index += 1
    # A short or thinly-supported segment (a beat-sparse transition) cannot
    # anchor a phrase grid; let the better-matching neighbor cut across it.
    index = 0
    while len(grids) > 1 and index < len(grids):
        g = grids[index]
        if g['stop'] - g['start'] >= 30 and g['onsets_on_grid'] >= 60:
            index += 1
            continue
        before = grids[index - 1] if index > 0 else None
        after = grids[index + 1] if index + 1 < len(grids) else None
        if before is not None and (after is None or
                boundary_gap(before, g, g['start'])
                <= boundary_gap(g, after, g['stop'])):
            before['stop'] = g['stop']
        else:
            after['start'] = g['start']
        grids.pop(index)
    for g in grids:
        g['downbeat_phase'] = downbeat_phase(kick, g['period'], g['offset'],
                                             g['start'], g['stop'],
                                             args.beats_per_bar)
        sel = (kick_times >= g['start']) & (kick_times < g['stop'])
        kres = kick_times[sel] - (g['offset'] + np.rint(
            (kick_times[sel] - g['offset']) / g['period']) * g['period'])
        kres = kres[np.abs(kres) < g['period'] * INLIER]
        g['kick_residual_median_ms'] = (round(float(np.median(kres)) * 1000, 1)
                                        if len(kres) else None)
        print(f'  segment {g["start"]:7.2f}-{g["stop"]:7.2f}s: '
              f'bpm={g["bpm"]:.4f} offset={g["offset"]:.4f} '
              f'downbeat=beat{g["downbeat_phase"]} '
              f'p90|resid|={g["residual_p90_ms"]:.1f}ms n={g["onsets_on_grid"]} '
              f'[{g["phase_source"]}] kick-median='
              f'{g["kick_residual_median_ms"]}ms')

    entry = music_entry(times, period)

    # Phrase anchoring per segment: the first downbeat of the segment head
    # (first segment: at/after the music entry), plus — when the segment has
    # a distinctly later sustained-loud entry (a drop after a quiet build) —
    # the downbeat nearest that entry. Sections count forward from the anchor
    # and back-fill toward the head, so the drop lands on a clip boundary.
    starts = []
    for index, grid in enumerate(grids):
        p, o, phase = grid['period'], grid['offset'], grid['downbeat_phase']
        lo = max(grid['start'], entry) if index == 0 else grid['start']
        beat0 = math.ceil((lo - o) / p - .25)
        while beat0 % args.beats_per_bar != phase:
            beat0 += 1
        anchor = beat0
        loud = loud_entry(power, grid['start'], grid['stop'])
        if loud is not None and loud - (o + beat0 * p) > 2 * section_beats * p:
            near = round((loud - o) / p)
            near -= (near - phase) % args.beats_per_bar
            if abs(o + near * p - loud) > abs(o + near * p
                                              + args.beats_per_bar * p - loud):
                near += args.beats_per_bar
            anchor = near
        first = anchor - (anchor - beat0) // section_beats * section_beats
        starts.append((beat0, first, o + first * p))

    # Build the cut plan: continuous numbering, gap-free coverage. Full
    # sections are exactly section_beats long; leftovers before a segment's
    # first full section or after its last become partial clips.
    # Hand-off point at each segment boundary: a substantial pre-anchor head
    # becomes the next segment's own partial; a sub-2-beat sliver is absorbed
    # into the previous segment's tail instead of becoming a tiny clip.
    handoff = [0.0]
    for index in range(1, len(grids)):
        _, _, t0 = starts[index]
        head = grids[index]['start']
        handoff.append(head if t0 - head > 2 * grids[index]['period'] else t0)
    handoff.append(duration)

    cuts = []
    for index, grid in enumerate(grids):
        p, o = grid['period'], grid['offset']
        beat0, first, t0 = starts[index]
        head = handoff[index]
        if t0 - head > 0.02:
            cuts.append({'kind': 'intro' if index == 0 else 'partial',
                         'start': head, 'end': t0, 'segment': index})
        stop = handoff[index + 1]
        last_beat = math.floor((min(grid['stop'], stop) - o) / p + .25)
        full = max(0, (last_beat - first) // section_beats)
        for s in range(full):
            cuts.append({'kind': 'section', 'segment': index,
                         'start': t0 + s * section_beats * p,
                         'end': t0 + (s + 1) * section_beats * p})
        tail_start = t0 + full * section_beats * p
        if stop - tail_start > 0.02:
            cuts.append({'kind': 'tail' if index == len(grids) - 1 else 'partial',
                         'segment': index, 'start': tail_start, 'end': stop})

    number = 0
    for cut in cuts:
        suffix = {'intro': '_intro', 'partial': '_partial', 'tail': '_tail',
                  'section': ''}[cut['kind']]
        cut['name'] = f'section_{number:03d}{suffix}.mp4'
        number += 1

    plan = {
        'take': str(take), 'take_id': take_id,
        'duration': duration,
        'assumptions': [
            f'{args.beats_per_bar}/4 meter assumed; section = {args.measures} '
            f'measures = {section_beats} beats',
            'beat phase anchored to kick-band (40-130Hz) attack onsets'
            if use_kick else
            'too few kick onsets; beat phase fit to general onset population',
            'downbeat chosen per segment by kick-band energy, not score data',
            'analysis timeline mapped to master by cross-correlation '
            f'calibration: {start_correction * 1000:+.1f}ms '
            f'(spread {spread * 1000:.1f}ms)'],
        'music_entry': entry,
        'timeline_correction': round(start_correction, 5),
        'segments': [{**g, 'bpm': round(g['bpm'], 4)} for g in grids],
        'clips': [{'name': c['name'], 'kind': c['kind'], 'segment': c['segment'],
                   't_rec_start': round(max(0.0, c['start'] + start_correction), 4),
                   't_rec_end': round(c['end'] + start_correction, 4),
                   'duration': round(c['end'] - c['start'], 4),
                   'beats': round((c['end'] - c['start'])
                                  / grids[c['segment']]['period'], 2)}
                  for c in cuts],
    }

    print(f'\n{sum(c["kind"] == "section" for c in cuts)} full '
          f'{args.measures}-measure sections, '
          f'{sum(c["kind"] != "section" for c in cuts)} partial clips')
    if args.analyze_only:
        print(json.dumps(plan, indent=2))
        return

    out.mkdir(parents=True, exist_ok=True)
    (out / 'manifest.json').write_text(json.dumps(plan, indent=2) + '\n')
    for cut in cuts:
        master_start = max(0.0, cut['start'] + start_correction)
        encode_clip(take, master_start, cut['end'] - cut['start'], out / cut['name'])
        print(f'  wrote {cut["name"]} '
              f'[{master_start:.3f} +{cut["end"] - cut["start"]:.3f}s]')

    # Verification renders: click overlay on the first full section of each
    # segment (covers the take's start and every re-anchor boundary), then
    # the last section if the click budget allows.
    full_sections = [c for c in cuts if c['kind'] == 'section']
    picks, covered = [], set()
    for cut in full_sections:
        if cut['segment'] not in covered:
            picks.append(cut)
            covered.add(cut['segment'])
    if full_sections and full_sections[-1] not in picks:
        picks.append(full_sections[-1])
    picks = picks[:args.clicks]
    if len(picks) < args.clicks:
        remaining = [c for c in full_sections if c not in picks]
        stride = max(1, len(remaining) // max(1, args.clicks - len(picks)))
        picks.extend(remaining[::stride][:args.clicks - len(picks)])
    picks.sort(key=lambda c: c['start'])
    for cut in picks:
        grid = grids[cut['segment']]
        p, o, phase = grid['period'], grid['offset'], grid['downbeat_phase']
        first = round((cut['start'] - o) / p)
        beat_times = [(first + b, o + (first + b) * p - cut['start'])
                      for b in range(section_beats + 1)]
        click = out / (cut['name'].replace('.mp4', '_clicktrack.wav'))
        write_click_wav(click, cut['end'] - cut['start'], beat_times,
                        args.beats_per_bar, phase)
        encode_clip(take, cut['start'] + start_correction,
                    cut['end'] - cut['start'],
                    out / cut['name'].replace('.mp4', '_click.mp4'),
                    with_click=click)
        click.unlink()
        print(f'  wrote {cut["name"].replace(".mp4", "_click.mp4")} (verification)')


if __name__ == '__main__':
    main()
