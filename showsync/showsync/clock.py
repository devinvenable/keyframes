"""Absolute beat-index MIDI scheduling against an injected audio position."""
import math
import logging
import threading
import time

from .priority import raise_thread_priority
from .audio import RATE

CLOCK, START, STOP = 0xF8, 0xFA, 0xFC
LOG = logging.getLogger(__name__)


class ClockEngine:
    def __init__(self, maps, position, send, *, now=time.monotonic, sleep=time.sleep,
                 clock_offset_ms=0, send_transport=True, events=None, controls=None,
                 keystep_send=None, send_except_keystep=None, event_output=None,
                 keystep_start_quantize='bar'):
        if keystep_start_quantize not in ('off', 'beat', 'bar'):
            raise ValueError('keystep_start_quantize must be off, beat, or bar')
        self.maps, self.position, self.send = maps, position, send
        # Resume-only egress (MidiEgress.send_transport_except_keystep): a
        # mid-bar Start must reach everything but the KeyStep rig, which is
        # re-anchored on its own grid tick instead. Without it, resume keeps
        # the historical full-egress Start.
        self.send_except_keystep = send_except_keystep
        self.now, self.sleep = now, sleep
        # Optional per-song visual-control messages (indexable like maps, one
        # tuple of byte tuples per song — see visuals.song_controls). Sent on
        # the clock port at each song start so Keyframes cues share the
        # clock's transport and timebase without any per-song .mid dependency.
        self.controls = controls
        self.clock_offset_ms = clock_offset_ms
        self.send_transport = send_transport
        self.keystep_send = keystep_send
        self.keystep_start_quantize = keystep_start_quantize
        # Song meter is currently fixed at four quarter-note beats per bar;
        # MIDI file loop length is phrase length, not a time signature.
        self._keystep_grid = {'off': 0, 'beat': 24, 'bar': 96}[keystep_start_quantize]
        self._keystep_pending = False
        self._keystep_lock = threading.RLock()
        # Optional per-song MidiEvent lists (indexable like maps). File events
        # ride this thread on the same clock_time, so ramps and the clock
        # offset move ticks and file playback together.
        self.events = events
        self._song_events = ()
        self._cursor = 0
        self._loop_beats = None
        self._iteration = 0
        self._event_port = None
        self._open_event_output = event_output or open_midi_port
        self._default_event_send = (event_output(None).send_message
                                    if event_output is not None else send)
        self._event_send = self._default_event_send
        self._channels = set()
        self._key = None
        self._active = False
        self._tick = 0
        self._startup_until = -1
        self._last_sent_time = None
        self._last_target = None
        self._halt = threading.Event()
        self._thread = None
        self._transport_stamp = None
        self.error = None
        self.dropped_ticks = 0  # Vestigial status API: indices are never dropped.
        self.priority_raised = False

    def _send_transport_byte(self, byte):
        """Send Start/Stop, stamping first: a hardware thru path can echo the
        byte back onto our transport input while send() is still in flight."""
        self._transport_stamp = self.now()
        self.send(byte)

    def transport_egress_age(self):
        """Seconds since this clock last sent Start/Stop (inf before the first)."""
        if self._transport_stamp is None:
            return math.inf
        return self.now() - self._transport_stamp

    def relay_keystep_transport(self, status):
        """Arm Start on the clock grid; Stop always cancels and sends now."""
        with self._keystep_lock:
            if status == STOP:
                self._keystep_pending = False
            if not self.send_transport or self.keystep_send is None:
                return False
            if status == START and self._keystep_grid:
                self._keystep_pending = True
                if self._active:
                    LOG.info('Start armed (quantize=%s, fires in %d ticks)',
                             self.keystep_start_quantize, (-self._tick) % self._keystep_grid)
                else:
                    # Latched, not swallowed: a press while paused/idle keeps
                    # its arm and fires on the first grid tick after playback.
                    LOG.info('Start armed while playback idle (quantize=%s) — '
                             'latched until playback resumes', self.keystep_start_quantize)
                return True
            return self._send_keystep_transport(status)

    def _send_keystep_transport(self, status):
        # Stamp at emission, before even a synchronous DIN/TBOX echo.
        self._transport_stamp = self.now()
        return self.keystep_send(status)

    def step(self):
        """Process current state/tick; return seconds until next work (fake-clock API)."""
        p = self.position()
        key = (p.epoch, p.song_index)
        reset = key != self._key
        if self._active and (not p.playing or p.ended or reset):
            # Pause/skip/end: nothing may ring — release sustain, then silence.
            self._flush_notes()
            if self.send_transport:
                self._send_transport_byte(STOP)
            self._active = False
        if not p.playing or p.ended:
            # A Play arm made while paused/idle stays latched (task 304): it
            # fires on the first grid tick after playback, instead of the
            # press silently vanishing. Stop relays and song resets still
            # cancel it explicitly.
            return .001
        if reset:
            with self._keystep_lock:
                self._tick = 0
                # A new song/epoch sends its own Start; no stale button arm
                # may restart the sequencer later in that song.
                if self._key is not None:
                    self._keystep_pending = False
            self._last_sent_time = self._last_target = None
            self._song_events = ()
            self._loop_beats = None
            self._iteration = 0
            self._close_event_port()
            if hasattr(self.events, 'playback'):
                playback = self.events.playback(p.song_index, p.layout)
                self._song_events = playback.events
                self._loop_beats = playback.loop_beats if playback.events else None
                if playback.events and playback.port is not None:
                    try:
                        self._event_port = self._open_event_output(playback.port)
                        self._event_send = self._event_port.send_message
                    except Exception as exc:
                        LOG.warning('MIDI file output %r unavailable (%s) — playing without MIDI file',
                                    playback.port, exc)
                        self._song_events = ()
                        self._loop_beats = None
            elif self.events is not None:
                self._song_events = self.events[p.song_index]
            self._cursor = 0
            if self.controls is not None:
                # Emitted before this song's START/first tick: the bank must
                # be live before any note or clock the new song produces.
                for message in self.controls[p.song_index]:
                    self.send(message)
        # Position carries the same immutable layout as its audio frame.
        tempo = p.layout.maps[p.song_index] if p.layout is not None else self.maps[p.song_index]
        audio_time = p.song_time
        # Snapshot once: positive compensation advances MIDI, never audio.
        clock_time = audio_time + self.clock_offset_ms / 1000.0
        if not self._active:
            # A reset (new song/epoch/set) starts at tick 0, already on the
            # one, so the full-egress Start re-anchors every slave correctly.
            # A resume lands mid-bar: gear behind the KeyStep re-anchors its
            # pattern on Start, so that Start would put the rig's one at the
            # pause point for the rest of the song (task 304). Withhold it
            # from the KeyStep (its Stop was sent at pause) and re-anchor the
            # rig on the next grid tick via the quantize machinery.
            resume_on_grid = (not reset and self._keystep_grid
                              and self.keystep_send is not None
                              and self.send_except_keystep is not None)
            if self.send_transport:
                if resume_on_grid:
                    self._transport_stamp = self.now()
                    self.send_except_keystep(START)
                    with self._keystep_lock:
                        self._keystep_pending = True
                    LOG.info('Resume: KeyStep Start held for the next grid '
                             'tick (quantize=%s)', self.keystep_start_quantize)
                else:
                    self._send_transport_byte(START)
            self._active = True
            # Resume retains the next unsent index; intentional restarts reset.
            self._startup_until = math.floor(tempo.B(max(0.0, clock_time)) * 24 + 1e-8)
        self._key = key
        # File events share the clock's deadlines; cursor state survives a
        # pause (resume replays nothing) and resets with the tick index.
        while True:
            offset = self._iteration * (self._loop_beats or 0)
            if self._cursor < len(self._song_events):
                event = self._song_events[self._cursor]
                event_due = tempo.T(offset + event.beat) - clock_time
            elif self._loop_beats is not None:
                event_due = tempo.T((self._iteration + 1) * self._loop_beats) - clock_time
            else:
                event_due = math.inf
            if event_due > 1e-9:
                break
            if self._cursor < len(self._song_events):
                self._send_event(event.data)
                self._cursor += 1
            else:
                # Release the outgoing phrase before its beat-zero notes.
                # Integer iteration * length avoids accumulating timing error.
                self._flush_notes()
                self._iteration += 1
                self._cursor = 0
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
            emitted_start = False
            with self._keystep_lock:
                if self._keystep_pending and self._tick % self._keystep_grid == 0:
                    self._keystep_pending = False
                    if self.send_transport and self.keystep_send is not None:
                        emitted_start = self._send_keystep_transport(START)
                # Start resets the slave; this immediately following F8 is
                # its first tick. Keep arm/cancel out of this send pair.
                self.send(CLOCK)
                self._last_sent_time, self._last_target = audio_time, target
                self._tick += 1
            if emitted_start:
                LOG.info('Start emitted on grid')
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
        self._event_send(data)
        status = data[0] & 0xF0
        if status == 0x90 and len(data) > 2 and data[2] > 0:
            self._channels.add(data[0] & 0x0F)
        elif status == 0xB0 and len(data) > 2 and data[1] == 64 and data[2] >= 64:
            self._channels.add(data[0] & 0x0F)

    def _flush_notes(self):
        # Sustain off before All Notes Off: CC123 cannot silence pedal-held notes.
        for channel in sorted(self._channels):
            self._event_send((0xB0 | channel, 64, 0))
            self._event_send((0xB0 | channel, 123, 0))
        self._channels.clear()

    def _close_event_port(self):
        if self._event_port is not None:
            try:
                self._event_port.close_port()
            finally:
                self._event_port = None
                self._event_send = self._default_event_send

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
            try:
                self._stop()
            finally:
                self._close_event_port()

    def _stop(self):
        with self._keystep_lock:
            self._keystep_pending = False
        if self._active:
            try:
                try:
                    self._flush_notes()
                finally:
                    if self.send_transport:
                        self._send_transport_byte(STOP)
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
            try:
                self._stop()
            finally:
                self._close_event_port()


def resolve_midi_port(selection, ports):
    """Index of `selection` in `ports`: index, exact name, or unique substring.

    Exact rtmidi names are stage-brittle — ALSA appends a client:port id that
    changes across replugs, and CoreMIDI names differ entirely — so a set
    authored as 'Midi Out 2' must find the same jack on any host. An exact
    match always wins; otherwise a case-insensitive substring must single out
    one port, and an ambiguous or missing match raises with the candidates so
    the caller can fall back rather than guess.
    """
    if selection is None:
        if len(ports) != 1:
            raise ValueError(f'Choose --midi-port by index, name, or unique substring; '
                             f'available: {list(enumerate(ports))}')
        return 0
    if isinstance(selection, int) or str(selection).isdecimal():
        index = int(selection)
        if not 0 <= index < len(ports):
            raise ValueError(f'MIDI port index {index} is out of range: {list(enumerate(ports))}')
        return index
    exact = [i for i, name in enumerate(ports) if name == selection]
    if len(exact) == 1:
        return exact[0]
    matches = [i for i, name in enumerate(ports) if str(selection).lower() in name.lower()]
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise ValueError(f'MIDI port {selection!r} is ambiguous; matches: '
                         f'{[(i, ports[i]) for i in matches]}')
    raise ValueError(f'MIDI port {selection!r} does not match any output; '
                     f'available: {list(enumerate(ports))}')


def open_midi_port(selection=None):
    import rtmidi
    output = rtmidi.MidiOut()
    index = resolve_midi_port(selection, output.get_ports())
    output.open_port(index)
    return output
