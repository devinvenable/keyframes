"""Realtime transport drives the set; KeyStep button CCs control only its rig."""
import logging

START, CONTINUE, STOP = 0xFA, 0xFB, 0xFC
NAMES = {START: 'Start', CONTINUE: 'Continue', STOP: 'Stop'}
# Incoming transport this soon after our own Start/Stop egress is treated as
# a hardware thru echo of that egress, not a performer's press.
ECHO_WINDOW = 1.0


class TransportControl:
    """Map incoming realtime Start/Continue/Stop bytes to set controls.

    Idempotent by design: ShowSync's own clock egress emits Start/Stop, and
    a hardware thru path can echo those back onto the input port. Acting
    only when the set is NOT already in the requested state breaks that
    loop — an echoed Start lands while playing (no-op), and the Stop echoed
    by a pause or a set ending lands while playback is already stopped
    (no-op). That is also why Stop only acts while genuinely playing.

    State-based idempotence has one hole: the bar-quantized song handover,
    where the clock sends Stop then Start while the set IS genuinely
    playing. Echoed back, that Stop stopped the set and the Start restarted
    it from song 1 (task 169) — so incoming transport within ECHO_WINDOW of
    our own egress is dropped via `egress_age`. The gate sits here, in
    handle(), so it covers every open input port (task 152 listens on all
    hardware ports, which widened the echo path — any of them can carry the
    echo). Trade-off, accepted: a genuine performer press landing inside
    the window right after a boundary is ignored; pressing again works."""

    def __init__(self, *, is_active, is_playing, is_paused, start, resume, stop,
                 egress_age=None, relay=None, keystep_stop_cc=51, keystep_start_cc=54):
        self.is_active, self.is_playing, self.is_paused = is_active, is_playing, is_paused
        self.start, self.resume, self.stop = start, resume, stop
        self.egress_age = egress_age
        self.relay = relay
        self.keystep_ccs = {keystep_stop_cc: STOP, keystep_start_cc: START}
        self._pressed = set()

    def handle(self, status):
        """Apply one transport byte; return the action taken, or None."""
        if isinstance(status, tuple):
            return self._keystep_cc(status)
        if status in NAMES and self.egress_age is not None:
            age = self.egress_age()
            if age < ECHO_WINDOW:
                logging.info('MIDI transport %s (0x%02X): suppressed as an echo of '
                             'our own clock egress (%.3fs after Start/Stop egress)',
                             NAMES[status], status, age)
                return None
        action = self._action(status)
        if status in NAMES:
            logging.info('MIDI transport %s (0x%02X): %s',
                         NAMES[status], status, action or 'ignored (already in state)')
        return action

    def _keystep_cc(self, message):
        # Only connect_transport's KeyStep USB callback supplies CC tuples.
        # Share the latch across channels/ports to debounce mirrored presses.
        _, cc, value = message
        if cc not in self.keystep_ccs:
            return None
        if value == 0:
            self._pressed.discard(cc)
        elif value == 127 and cc not in self._pressed:
            self._pressed.add(cc)
            status = self.keystep_ccs[cc]
            if self.relay is not None and self.relay(status):
                logging.info('KeyStep CC%d value 127: translated to realtime %s '
                             '(0x%02X), relay-only', cc, NAMES[status], status)
                return 'relayed ' + NAMES[status]
            logging.info('KeyStep CC%d: relay unavailable (no active KeyStep '
                         'transport egress)', cc)
        return None

    def _action(self, status):
        if status == START:
            if not self.is_active():
                self.start()
                return 'started set'
            if self.is_paused():
                self.resume()
                return 'resumed'
        elif status == CONTINUE:
            if self.is_paused():
                self.resume()
                return 'resumed'
            if not self.is_active():
                self.start()
                return 'started set'
        elif status == STOP:
            if self.is_playing():
                self.stop()
                return 'stopped set'
        return None


class TransportInputs:
    """The set of open transport input ports, closed as one."""

    def __init__(self, inputs):
        self.inputs = inputs

    def close_port(self):
        for midi_in in self.inputs:
            midi_in.close_port()
        self.inputs = []


def connect_transport(owner, control, preferred=None):
    """Route realtime transport and KeyStep USB button CCs to `control`.

    `owner` must expose a `transport_received` object signal; emitting through it
    hops from the rtmidi callback thread to the GUI thread. Returns the open
    inputs as one closeable object (caller calls close_port()), or None when
    no input could be opened."""
    try:
        inputs = open_midi_inputs(preferred)
    except Exception as exc:
        logging.warning('--midi-transport: could not open MIDI input: %s', exc)
        return None
    if not inputs:
        logging.warning('--midi-transport: no MIDI input port available')
        return None
    owner.transport_received.connect(control.handle)
    transport_bytes = (START, CONTINUE, STOP)

    def callback(event, source):
        message = event[0]
        if message and message[0] in transport_bytes:
            owner.transport_received.emit(message[0])
        elif ('keystep' in source.lower() and len(message) == 3
              and message[0] & 0xF0 == 0xB0
              and message[1] in control.keystep_ccs):
            owner.transport_received.emit(tuple(message))

    for name, midi_in in inputs:
        midi_in.set_callback(callback, name)
    return TransportInputs([midi_in for _, midi_in in inputs])


def open_midi_inputs(preferred=None):
    """Open every hardware MIDI input, returning (name, input) pairs.

    The Start-sending device can enter through any jack of a multi-port
    interface (a KeyStep behind a TBOX 2x2 shows up on whichever of its two
    ports it is plugged into), so opening one guessed port risks a set that
    never starts — open them all; TransportControl.handle is idempotent, so
    hearing the same byte on several ports is safe. An exact match on
    `preferred` (the configured MIDI output name) is ordered first but never
    excludes the rest. Ports named through/virtual/loopback are skipped to
    avoid our own clock egress looping back, and so is our own 'ShowSync
    Cues' virtual egress port — listening to it would feed every Start/Stop
    we send straight back into this input. Incoming clock/sysex/sensing
    stay ignored (rtmidi default), so only channel and transport messages
    reach the callback."""
    import rtmidi
    from .egress import VIRTUAL_PORT_NAME
    probe = rtmidi.MidiIn()
    ports = probe.get_ports()
    probe.delete()
    skipped = ('through', 'virtual', 'loopback', VIRTUAL_PORT_NAME.lower())
    candidates = [i for i, name in enumerate(ports)
                  if (name == preferred and VIRTUAL_PORT_NAME.lower() not in name.lower())
                  or not any(word in name.lower() for word in skipped)]
    candidates.sort(key=lambda i: ports[i] != preferred)
    inputs = []
    for index in candidates:
        midi_in = rtmidi.MidiIn()
        try:
            midi_in.open_port(index)
        except Exception as exc:
            logging.warning('MIDI transport input: could not open %r: %s',
                            ports[index], exc)
            midi_in.delete()
            continue
        logging.info('MIDI transport input: listening on %r', ports[index])
        inputs.append((ports[index], midi_in))
    return inputs
