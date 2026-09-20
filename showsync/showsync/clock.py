"""Absolute beat-index MIDI scheduling against an injected audio position."""
import math
from bisect import bisect_right
from dataclasses import dataclass
import threading
import time

from .priority import raise_thread_priority
from .audio import RATE

CLOCK, START, STOP = 0xF8, 0xFA, 0xFC


@dataclass(frozen=True)
class ClockSection:
    song: int
    tempo: object
    anchor: float  # absolute audio seconds of this map's beat zero
    beat: int     # beat zero's index since the last intentional restart

    def T(self, beat):
        return self.anchor + self.tempo.T(beat - self.beat) - self.tempo.offset

    def B(self, seconds):
        return self.beat + self.tempo.B(max(0, seconds - self.anchor + self.tempo.offset))


class ClockTimeline:
    """Absolute audio-time schedule, ending at the next explicit pattern reset.

    Quantize each incoming *actual* first beat to the closest existing beat
    in time (ties go earlier), then translate that song's entire tempo map.
    The error is local, never added to the next song's audio anchor. Several
    very short songs can share a beat: the last map wins that boundary.
    """
    def __init__(self, layout, first):
        tempo = layout.maps[first]
        self.sections = [ClockSection(first, tempo, layout.starts[first] / RATE + tempo.offset, 0)]
        for song in range(first + 1, len(layout.maps)):
            if layout.setlist.songs[song].restart:
                break
            tempo = layout.maps[song]
            desired = layout.starts[song] / RATE + tempo.offset
            lower = math.floor(self.B(desired) + 1e-9)
            beat = min((lower, lower + 1), key=lambda b: abs(self.T(b) - desired))
            anchor = self.T(beat)
            # A short incoming song can supersede a still-future handover.
            while self.sections and self.sections[-1].beat >= beat:
                self.sections.pop()
            self.sections.append(ClockSection(song, tempo, anchor, beat))
        self.sections = tuple(self.sections)

    def T(self, beat):
        index = bisect_right(self.sections, beat, key=lambda s: s.beat) - 1
        return self.sections[max(0, index)].T(beat)

    def B(self, seconds):
        index = bisect_right(self.sections, seconds, key=lambda s: s.anchor) - 1
        return self.sections[max(0, index)].B(seconds)


class ClockEngine:
    def __init__(self, maps, position, send, *, now=time.monotonic, sleep=time.sleep,
                 clock_offset_ms=0, send_transport=True):
        self.maps, self.position, self.send = maps, position, send
        self.now, self.sleep = now, sleep
        self.clock_offset_ms = clock_offset_ms
        self.send_transport = send_transport
        self._key = None
        self._active = False
        self._tick = 0
        self._startup_until = -1
        self._timeline = None
        self._layout = None
        self._first_song = 0
        self._last_sent_time = None
        self._last_target = None
        self._halt = threading.Event()
        self._thread = None
        self.error = None
        self.dropped_ticks = 0  # Vestigial status API: indices are never dropped.
        self.priority_raised = False

    def step(self):
        """Process current state/tick; return seconds until next work (fake-clock API)."""
        p = self.position()
        key = (p.epoch, p.song_index)
        first_song = p.song_index
        reset = self._key is None or p.epoch != self._key[0]
        if self._key is not None and p.layout is not None and not reset:
            for index in range(self._key[1] + 1, p.song_index + 1):
                if p.layout.setlist.songs[index].restart:
                    # A stall may cross the reset and another natural boundary.
                    # Recover from the last requested reset, not the later song.
                    reset, first_song = True, index
        if self._active and (not p.playing or p.ended or reset):
            if self.send_transport:
                self.send(STOP)
            self._active = False
        if not p.playing or p.ended:
            return .001
        if reset:
            self._first_song = first_song
            self._tick = 0
            self._last_sent_time = self._last_target = None
        if p.layout is not None:
            if reset or p.layout is not self._layout:
                self._timeline = ClockTimeline(p.layout, self._first_song)
                self._layout = p.layout
            tempo = self._timeline
            audio_time = p.frame / RATE
        else:
            # Injected single-song/intentional-transport tests need no layout.
            # Natural transitions require future starts for early handovers.
            if not reset and p.song_index != self._key[1]:
                raise ValueError('Continuous song transitions require Position.layout')
            tempo = self.maps[p.song_index]
            audio_time = p.song_time
        # Snapshot once: positive compensation advances MIDI, never audio.
        clock_time = audio_time + self.clock_offset_ms / 1000.0
        if not self._active:
            if self.send_transport:
                self.send(START)
            self._active = True
            # Resume retains the next unsent index; intentional restarts reset.
            self._startup_until = math.floor(tempo.B(max(0.0, clock_time)) * 24 + 1e-8)
        self._key = key
        target = tempo.T(self._tick / 24)
        remaining = target - clock_time
        if self._tick > self._startup_until + 1 and self._last_sent_time is not None:
            # Catch up at no more than twice the scheduled rate. Every F8 is
            # retained; after recovery the absolute audio deadlines win again.
            interval = max(0, target - self._last_target)
            remaining = max(remaining, self._last_sent_time + interval / 2 - audio_time)
        if remaining <= 1e-9:
            self.send(CLOCK)
            self._last_sent_time, self._last_target = audio_time, target
            self._tick += 1
            remaining = tempo.T(self._tick / 24) - clock_time
            if self._tick > self._startup_until + 1:
                remaining = max(remaining, (tempo.T(self._tick / 24) - target) / 2)
        return max(0, remaining)

    def _run(self):
        self.priority_raised = raise_thread_priority()
        try:
            while not self._halt.is_set():
                remaining = self.step()
                if not self._active:
                    self.sleep(.001)
                elif remaining > .002 + 1e-9:
                    # Short cap also bounds transport-response time at very low BPM.
                    self.sleep(min(remaining - .002, .01))
                else:
                    # Re-read the audio anchor at every spin: no free-running clock.
                    self.now()
        except Exception as exc:
            self.error = f'MIDI clock failed: {exc}'
        finally:
            self._stop()

    def _stop(self):
        if self._active:
            try:
                if self.send_transport:
                    self.send(STOP)
            finally:
                self._active = False

    def start(self):
        self._thread = threading.Thread(target=self._run, name='showsync-clock', daemon=True)
        self._thread.start()

    def close(self):
        self._halt.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            if self._thread.is_alive():
                raise RuntimeError('MIDI sender did not stop within 5 seconds')
        else:
            self._stop()


def open_midi_port(selection=None):
    import rtmidi
    output = rtmidi.MidiOut()
    ports = output.get_ports()
    if selection is None:
        if len(ports) != 1:
            raise ValueError(f'Choose --midi-port by index or exact name; available: {list(enumerate(ports))}')
        index = 0
    elif str(selection).isdecimal():
        index = int(selection)
    else:
        matches = [i for i, name in enumerate(ports) if name == selection]
        if len(matches) != 1:
            raise ValueError(f'MIDI port must match one exact name; available: {list(enumerate(ports))}')
        index = matches[0]
    if not 0 <= index < len(ports):
        raise ValueError(f'MIDI port index {index} is out of range: {list(enumerate(ports))}')
    output.open_port(index)
    return output
