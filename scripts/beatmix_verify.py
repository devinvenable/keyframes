#!/usr/bin/env python3
"""Independent verifier for a beatmix output (task-233 pattern).

Checks a mix against its <out>.json recipe using only the masters — none
of beatmix's own arithmetic is trusted:

1. PLACEMENT: 2s of mid-section output audio is cross-correlated against
   the master take at the recipe position, searching only +-50ms (loop
   music is self-similar at 8-beat shifts; a wide search can lock onto
   the wrong repetition). |offset| <= 2ms + 0.2ms per preceding splice
   proves the section's content sits at its planned position (a benign
   ~0.2ms/splice settling is observed on long chains while the total
   duration stays sample-exact; the slack keeps the check honest at
   10+ sections without masking a real slid splice, which shows up as
   one full handle or more).
2. KICK GRID: the 40-130Hz kick-band amplitude envelope of the WHOLE
   output section is cross-correlated against the same window of the
   master. This aligns on the beat transients themselves and is immune
   to the limiter's attack reshaping (which makes onset-picker phase
   estimates drift tens of ms on limited audio). |offset| <= 5ms proves
   the downbeats are on the output grid.

Usage: beatmix_verify.py recordings/beatmix_X.mp4 [recordings/beatmix_X.mp4.json]
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

import numpy as np
from scipy.signal import fftconvolve
import soundfile

RATE = 48000
PLACEMENT_TOL_MS = 2.0      # + PER_SPLICE_MS per preceding splice
PER_SPLICE_MS = 0.2
KICK_TOL_MS = 5.0


def read_window(path, start, duration, pin=False):
    cmd = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
           '-ss', f'{start:.6f}', '-t', f'{duration:.6f}', '-i', str(path),
           '-map', '0:a:0', '-ac', '1', '-ar', str(RATE)]
    if pin:  # master side: pin decoded samples to container timestamps
        cmd += ['-af', 'aresample=async=1000:first_pts=0']
    with tempfile.NamedTemporaryFile(suffix='.wav') as wav:
        subprocess.run(cmd + ['-c:a', 'pcm_f32le', wav.name], check=True)
        data, _ = soundfile.read(wav.name)
    return data


def kick_envelope(samples):
    """40-130Hz band amplitude envelope at 1kHz, mean-removed."""
    spectrum = np.fft.rfft(samples)
    freqs = np.fft.rfftfreq(len(samples), 1 / RATE)
    spectrum[(freqs < 40) | (freqs > 130)] = 0
    band = np.fft.irfft(spectrum, len(samples))
    step = RATE // 1000
    frames = len(band) // step * step
    envelope = np.sqrt((band[:frames] ** 2).reshape(-1, step).mean(axis=1))
    return envelope - envelope.mean()


def best_offset_ms(haystack, needle, slack_s, rate):
    corr = fftconvolve(haystack, needle[::-1], mode='valid')
    return (int(np.argmax(corr)) / rate - slack_s) * 1000


def main():
    mix = Path(sys.argv[1])
    recipe_path = Path(sys.argv[2]) if len(sys.argv) > 2 else \
        mix.with_suffix(mix.suffix + '.json')
    recipe = json.loads(recipe_path.read_text())
    failed = False

    cum = 0.0
    for k, s in enumerate(recipe['sections']):
        slack = 0.05
        needle = read_window(mix, cum + 2.0, 2.0)
        hay = read_window(s['take'], s['t_rec_start'] + 2.0 - slack,
                          2.0 + 2 * slack, pin=True)
        offset = best_offset_ms(hay, needle, slack, RATE)
        placement_ok = abs(offset) <= PLACEMENT_TOL_MS + PER_SPLICE_MS * k

        slack = 0.06
        out_env = kick_envelope(read_window(mix, cum, s['duration']))
        master_env = kick_envelope(read_window(
            s['take'], s['t_rec_start'] - slack, s['duration'] + 2 * slack,
            pin=True))
        kick = best_offset_ms(master_env, out_env, slack, 1000)
        kick_ok = abs(kick) <= KICK_TOL_MS

        failed |= not (placement_ok and kick_ok)
        print(f'section {k} ({s["spec"]}): placement {offset:+.2f}ms '
              f'{"OK" if placement_ok else "FAIL"}, kick grid {kick:+.1f}ms '
              f'{"OK" if kick_ok else "FAIL"}')
        cum += s['duration']

    print('VERDICT:', 'FAIL' if failed else 'PASS')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
