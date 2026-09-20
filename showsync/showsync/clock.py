"""Absolute beat-index MIDI scheduling against an injected audio position."""
import math
import threading
import time

from .priority import raise_thread_priority

CLOCK, START, STOP = 0xF8, 0xFA, 0xFC


class ClockEngine:
    def __init__(self, maps, position, send, *, now=time.monotonic, sleep=time.sleep, clock_offset_ms=0):
        self.maps, self.position, self.send = maps, position, send
        self.now, self.sleep = now, sleep
        self.clock_offset_ms = clock_offset_ms
        self._key = None
        self._active = False
        self._tick = 0
        self._halt = threading.Event()
        self._thread = None
        self.error = None
        self.dropped_ticks = 0
        self.priority_raised = False

    def step(self):
        """Process current state/tick; return seconds until next work (fake-clock API)."""
        p = self.position()
        key = (p.epoch, p.song_index)
        if self._active and (not p.playing or p.ended or key != self._key):
            self.send(STOP)
            self._active = False
        if not p.playing or p.ended:
            return .001
        tempo = self.maps[p.song_index]
        # Snapshot once: positive compensation advances MIDI, never audio.
        clock_time = p.song_time + self.clock_offset_ms / 1000.0
        if not self._active:
            self.send(START)
            self._active = True
            self._key = key
            self._tick = max(0, math.ceil(tempo.B(max(0.0, clock_time)) * 24 - 1e-8))
        target = tempo.T(self._tick / 24)
        remaining = target - clock_time
        if remaining <= 1e-9:
            # Do not emit a burst of stale ticks after an OS stall. Absolute phase
            # is retained; diagnostic count makes missed clocks visible.
            latest = max(self._tick, math.floor(tempo.B(max(0.0, clock_time)) * 24 + 1e-8))
            self.dropped_ticks += latest - self._tick
            self._tick = latest
            self.send(CLOCK)
            self._tick += 1
            remaining = tempo.T(self._tick / 24) - clock_time
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
