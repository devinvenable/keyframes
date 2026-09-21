"""Regenerate the original cropped-attack regression pair (requires ffmpeg).

Sixteen seconds of 120 BPM kicks, cut 15 ms into the first attack. Both files
contain the same trim; MP3 delay/padding is handled by the normal decoder.
"""
from pathlib import Path
import subprocess

import numpy as np
import soundfile as sf


def main():
    root = Path(__file__).resolve().parents[1] / 'tests' / 'fixtures'
    rate = 24000
    t = np.arange(round(.06 * rate)) / rate
    kick = .7 * np.sin(2 * np.pi * 90 * t) * np.exp(-t * 60)
    audio = np.zeros(16 * rate)
    for beat in np.arange(-.015, 15.9, .5):
        start = round(beat * rate)
        lo, hi = max(0, start), min(len(audio), start + len(kick))
        audio[lo:hi] += kick[lo - start:hi - start]
    wav = root / 'cropped-beat.wav'
    sf.write(wav, audio, rate, subtype='PCM_16')
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(wav),
                    '-codec:a', 'libmp3lame', '-b:a', '96k',
                    str(root / 'cropped-beat.mp3')], check=True)


if __name__ == '__main__':
    main()
