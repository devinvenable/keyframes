"""Generate demo click-track audio for trying showsync with live MIDI gear.

Each file is a click track whose clicks follow the exact tempo declared in
demo-setlist.yaml (including the ramp), so hardware locked to the MIDI clock
should land audibly on the clicks. Downbeats (every 4th) are higher-pitched.
"""

import numpy as np
import soundfile as sf
from pathlib import Path

RATE = 48000
HERE = Path(__file__).parent


def click(freq, dur=0.03, amp=0.8):
    t = np.arange(int(RATE * dur)) / RATE
    return (amp * np.sin(2 * np.pi * freq * t) * np.exp(-t * 90)).astype(np.float32)


def render(path, seconds, bpm_of_t):
    """Click track where bpm_of_t(t) gives instantaneous BPM at time t."""
    audio = np.zeros(int(RATE * seconds), dtype=np.float32)
    dt = 1.0 / RATE
    phase, beat = 0.0, 0
    for i in range(len(audio)):
        phase += bpm_of_t(i * dt) / 60.0 * dt
        if phase >= beat:
            c = click(1600 if beat % 4 == 0 else 800)
            end = min(i + len(c), len(audio))
            audio[i:end] += c[: end - i]
            beat += 1
    sf.write(path, np.column_stack([audio, audio]), RATE)
    print(f"wrote {path} ({seconds}s)")


render(HERE / "demo-100.wav", 40, lambda t: 100.0)
# 10s at 120, then linear ramp to 140 over 20s, then 140 to the end
render(
    HERE / "demo-ramp.wav",
    45,
    lambda t: 120.0 if t < 10 else (120.0 + (t - 10) / 20 * 20 if t < 30 else 140.0),
)
render(HERE / "demo-140.wav", 30, lambda t: 140.0)
