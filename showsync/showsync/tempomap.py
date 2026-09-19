"""Closed-form seconds ↔ beats. No playback dependencies or accumulated ticks."""

from bisect import bisect_right
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class TempoEvent:
    at: float
    bpm: float
    ramp: float = 0.0


@dataclass(frozen=True)
class Segment:
    t0: float
    t1: float
    bpm0: float
    bpm1: float
    beats_before: float

    @property
    def slope(self):
        return 0.0 if self.bpm0 == self.bpm1 else (self.bpm1 - self.bpm0) / (self.t1 - self.t0)

    def beats(self, t):
        x = t - self.t0
        return self.beats_before + x * (self.bpm0 + self.slope * x / 2) / 60

    def time(self, b):
        y = 60 * (b - self.beats_before)
        # Rationalized quadratic root avoids cancellation for near-flat ramps.
        return self.t0 + 2 * y / (self.bpm0 + math.sqrt(max(0, self.bpm0**2 + 2 * self.slope * y)))


def validate_events(bpm, events, duration=None, offset=0.0):
    if not math.isfinite(bpm) or bpm <= 0:
        raise ValueError("bpm must be finite and positive")
    if duration is not None and (not math.isfinite(duration) or duration <= 0):
        raise ValueError("duration must be finite and positive")
    if not math.isfinite(offset) or offset < 0:
        raise ValueError("offset must be finite and nonnegative")
    if duration is not None and offset >= duration:
        raise ValueError(f"offset must be less than file duration ({duration:g}s)")
    previous = -1.0
    end = 0.0
    for i, event in enumerate(events):
        prefix = f"tempo[{i}]"
        if not math.isfinite(event.at) or event.at < 0:
            raise ValueError(f"{prefix}.at must be finite and nonnegative")
        if offset and event.at <= offset:
            raise ValueError(f"{prefix}.at must be after the first-beat offset ({offset:g}s)")
        if event.at <= previous:
            raise ValueError(f"{prefix}.at must be strictly ascending")
        if event.at < end:
            raise ValueError(f"{prefix}.at overlaps the previous ramp")
        if not math.isfinite(event.bpm) or event.bpm <= 0:
            raise ValueError(f"{prefix}.bpm must be finite and positive")
        if not math.isfinite(event.ramp) or event.ramp < 0:
            raise ValueError(f"{prefix}.ramp must be finite and nonnegative")
        if duration is not None and (event.at >= duration or event.at + event.ramp > duration):
            raise ValueError(f"{prefix} lies outside file duration ({duration:g}s)")
        previous, end = event.at, event.at + event.ramp


class TempoMap:
    """Beat 0 anchors `offset` seconds into the file; audio before it is lead-in.

    B(t) is clamped to 0 through the lead-in, so the clock engine emits no
    ticks until the offset point, where tick 0 fires (T(0) == offset). Slaves
    reset on Start and step on the next F8: their first step lands on the
    song's true downbeat with no special-casing in the clock.
    """

    def __init__(self, bpm, events=(), duration=None, offset=0.0):
        events = tuple(events)
        validate_events(bpm, events, duration, offset)
        self.offset = float(offset)
        segments = []
        t, beats, current = self.offset, 0.0, float(bpm)

        def append(end, target):
            nonlocal t, beats, current
            segment = Segment(t, end, current, target, beats)
            segments.append(segment)
            beats = segment.beats(end) if math.isfinite(end) else beats
            t, current = end, target

        for event in events:
            if event.at > t:
                append(event.at, current)
            if event.ramp:
                append(event.at + event.ramp, event.bpm)
            else:
                current = event.bpm
        append(math.inf, current)
        self.segments = tuple(segments)
        self._times = tuple(s.t0 for s in segments)
        self._beats = tuple(s.beats_before for s in segments)

    @staticmethod
    def _check(value):
        if not math.isfinite(value) or value < 0:
            raise ValueError("position must be finite and nonnegative")

    def segment_at(self, t):
        self._check(t)
        return self.segments[max(0, bisect_right(self._times, t) - 1)]

    def B(self, t):
        return max(0.0, self.segment_at(t).beats(t))

    def T(self, b):
        self._check(b)
        return self.segments[bisect_right(self._beats, b) - 1].time(b)

    def bpm_at(self, t):
        s = self.segment_at(t)
        return s.bpm0 + s.slope * (t - s.t0)

    def ramp_target(self, t):
        s = self.segment_at(t)
        return s.bpm1 if s.bpm0 != s.bpm1 else None
