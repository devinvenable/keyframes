"""Audible metronome mixed into the main output inside the audio callback.

The click is synthesized from the same immutable Layout tempo maps and the
same frame counter that position() anchors the MIDI clock to, so it cannot
drift from what hardware hears. Beat 1 of each (fixed four-beat) bar is
accented. A testing aid for David, not a performer feature: default OFF,
toggled from the GUI by writing `enabled`; everything else runs on the
callback thread only.
"""
import math

import numpy as np


def _tone(frequency, amplitude, rate, seconds=0.03):
    """Short decaying cosine burst with a 1 ms attack to avoid a DC pop.

    The first sample is already nonzero, so the onset frame itself is audible
    (and assertable) rather than starting one sample late on a sine zero."""
    samples = round(seconds * rate)
    t = np.arange(samples, dtype=np.float32) / rate
    burst = amplitude * np.cos(2 * np.pi * frequency * t) * np.exp(-t / 0.006)
    attack = min(samples, round(rate / 1000))
    burst[:attack] *= np.linspace(1.0 / attack, 1.0, attack, dtype=np.float32)
    return burst.astype(np.float32)


class ClickTrack:
    def __init__(self, rate):
        self.enabled = False
        self._rate = rate
        self._accent = _tone(1760.0, 0.5, rate)
        self._beat = _tone(880.0, 0.35, rate)
        self._active = []  # (absolute onset frame, tone) spanning this block
        self._expected = None

    def mix(self, out, frame, index, layout):
        """Add clicks for song `index` into `out`, which starts at set frame `frame`.

        Called per contiguous span from the audio callback: no allocation
        beyond small slice views, no locks, no logging. A frame discontinuity
        (skip/restart/re-enable) drops ringing tails instead of replaying them.
        """
        if frame != self._expected:
            self._active.clear()
        count = len(out)
        self._expected = frame + count
        tempo = layout.maps[index]
        start = layout.starts[index]
        # B() clamps to 0 through a lead-in, so beat 0's onset (at the
        # first-beat offset) is simply found in the future until due. Starting
        # one beat early costs one skipped iteration; onset >= frame dedups.
        beat = max(0, math.floor(tempo.B(max(0.0, (frame - start) / self._rate))))
        while True:
            onset = start + round(tempo.T(beat) * self._rate)
            if onset >= frame + count:
                break
            if onset >= frame:
                self._active.append((onset, self._accent if beat % 4 == 0 else self._beat))
            beat += 1
        keep = []
        for onset, tone in self._active:
            at = max(0, onset - frame)
            src = max(0, frame - onset)
            n = min(count - at, len(tone) - src)
            if n > 0:
                out[at:at + n] += tone[src:src + n, None]
            if onset + len(tone) > frame + count:
                keep.append((onset, tone))
        self._active = keep
