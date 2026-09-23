"""Absolute beat-index MIDI scheduling against an injected audio position."""
import math
import threading
import time

from .priority import raise_thread_priority
from .audio import RATE

CLOCK, START, STOP = 0xF8, 0xFA, 0xFC


class ClockEngine:
    def __init__(self, maps, position, send, *, now=time.monotonic, sleep=time.sleep,
                 clock_offset_ms=0, send_transport=True, events=None):
        self.maps, self.position, self.send = maps, position, send
        self.now, self.sleep = now, sleep
        self.clock_offset_ms = clock_offset_ms
        self.send_transport = send_transport
        # Optional per-song MidiEvent lists (indexable like maps). File events
        # ride this thread on the same clock_time, so ramps and the clock
        # offset move ticks and file playback together.
        self.events = events
        self._song_events = ()
        self._cursor = 0
        self._channels = set()
        self._key = None
        self._active = False
        self._tick = 0
        self._startup_until = -1
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
        reset = key != self._key
        if self._active and (not p.playing or p.ended or reset):
            # Pause/skip/end: nothing may ring — release sustain, then silence.
            self._flush_notes()
            if self.send_transport:
                self.send(STOP)
            self._active = False
        if not p.playing or p.ended:
            return .001
        if reset:
            self._tick = 0
            self._last_sent_time = self._last_target = None
            self._song_events = self.events[p.song_index] if self.events is not None else ()
            self._cursor = 0
        # Position carries the same immutable layout as its audio frame.
        tempo = p.layout.maps[p.song_index] if p.layout is not None else self.maps[p.song_index]
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
        # File events share the clock's deadlines; cursor state survives a
        # pause (resume replays nothing) and resets with the tick index.
        while self._cursor < len(self._song_events):
            event = self._song_events[self._cursor]
            if tempo.T(event.beat) - clock_time > 1e-9:
                break
            self._send_event(event.data)
            self._cursor += 1
        if self._cursor < len(self._song_events):
            event_due = tempo.T(self._song_events[self._cursor].beat) - clock_time
        else:
            event_due = math.inf
        if p.layout is not None and p.song_index + 1 < len(p.layout.starts):
            boundary = p.layout.starts[p.song_index + 1]
            span = (boundary - p.layout.starts[p.song_index]) / RATE
            ticks = round(tempo.B(span) / 4) * 96
            if self._tick >= ticks:
                # The downbeat belongs to the incoming song, even when frame
                # rounding puts the old map's next tick just before the cut.
                return max(0, min((boundary - p.frame) / RATE, event_due))
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
        if p.layout is not None:
            # Wake at the audio boundary even if the next outgoing tick lies
            # beyond it (rounding, compensation, or a final partial bar).
            boundary = (p.layout.starts[p.song_index + 1]
                        if p.song_index + 1 < len(p.layout.starts) else p.layout.total_frames)
            remaining = min(remaining, (boundary - p.frame) / RATE)
        return max(0, min(remaining, event_due))

    def _send_event(self, data):
        self.send(data)
        status = data[0] & 0xF0
        if status == 0x90 and len(data) > 2 and data[2] > 0:
            self._channels.add(data[0] & 0x0F)
        elif status == 0xB0 and len(data) > 2 and data[1] == 64 and data[2] >= 64:
            self._channels.add(data[0] & 0x0F)

    def _flush_notes(self):
        # Sustain off before All Notes Off: CC123 cannot silence pedal-held notes.
        for channel in sorted(self._channels):
            self.send((0xB0 | channel, 64, 0))
            self.send((0xB0 | channel, 123, 0))
        self._channels.clear()

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
                try:
                    self._flush_notes()
                finally:
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
