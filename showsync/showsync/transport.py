"""MIDI realtime transport input: hardware Play/Stop drives the set."""
import logging

START, CONTINUE, STOP = 0xFA, 0xFB, 0xFC
NAMES = {START: 'Start', CONTINUE: 'Continue', STOP: 'Stop'}


class TransportControl:
    """Map incoming realtime Start/Continue/Stop bytes to set controls.

    Idempotent by design: ShowSync's own clock egress emits Start/Stop, and
    a hardware thru path can echo those back onto the input port. Acting
    only when the set is NOT already in the requested state breaks that
    loop — an echoed Start lands while playing (no-op), and the Stop echoed
    by a pause or a set ending lands while playback is already stopped
    (no-op). That is also why Stop only acts while genuinely playing."""

    def __init__(self, *, is_active, is_playing, is_paused, start, resume, stop):
        self.is_active, self.is_playing, self.is_paused = is_active, is_playing, is_paused
        self.start, self.resume, self.stop = start, resume, stop

    def handle(self, status):
        """Apply one transport byte; return the action taken, or None."""
        action = self._action(status)
        if status in NAMES:
            logging.info('MIDI transport %s (0x%02X): %s',
                         NAMES[status], status, action or 'ignored (already in state)')
        return action

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


def open_midi_input(preferred=None):
    """Open a MIDI input port for transport listening.

    Prefers an exact match on `preferred` (the configured MIDI output name —
    the KeyStep arrives through the same interface, so the input side shares
    its name), else the first hardware port. Returns None when no suitable
    input exists. Incoming clock/sysex/sensing stay ignored (rtmidi default),
    so only channel and transport messages reach the callback."""
    import rtmidi
    midi_in = rtmidi.MidiIn()
    ports = midi_in.get_ports()
    candidates = [i for i, name in enumerate(ports) if name == preferred]
    if not candidates:
        candidates = [i for i, name in enumerate(ports)
                      if not any(word in name.lower()
                                 for word in ('through', 'virtual', 'loopback'))]
    if not candidates:
        midi_in.delete()
        return None
    midi_in.open_port(candidates[0])
    logging.info('MIDI transport input: listening on %r', ports[candidates[0]])
    return midi_in
