"""Mirrored MIDI egress: one clock timebase fanned out to many destinations.

The ClockEngine keeps a single send callback; this module makes that callback
a fan-out over pre-opened rtmidi outputs — the setlist's `midi_outputs`
mirrors plus an always-on virtual port named 'ShowSync Cues' that Keyframes
picks up by name, so clock, transport, and visual cues arrive with no
hardware return loop (the DIN echo path that has wedged the TBOX; task 259).

Everything here is sized for the clock thread's tick loop: ports open once at
engine start, send() is a bare for-loop of non-blocking C calls, and a port
that dies mid-show is warned about once and dropped — a bad cable must never
raise into clock.error and kill a live set.
"""
import logging

from .clock import resolve_midi_port

LOG = logging.getLogger(__name__)

# Keyframes always listens to a port containing this name (in addition to its
# hardware/--port selection), and ShowSync's transport input always skips it
# (it is our own egress; listening would echo our Start/Stop back at us).
VIRTUAL_PORT_NAME = 'ShowSync Cues'


class MidiEgress:
    """Open MIDI outputs sent to as one; identical bytes on every port."""

    def __init__(self, ports, shared=()):
        # [(display name, rtmidi output)] — lists mutate only on send failure.
        # `ports` (the mirrors) are owned and closed with the egress; `shared`
        # (the virtual cue port) outlives it — Keyframes enumerates its inputs
        # once at startup, so that port must exist for the whole process, not
        # just while a set is playing.
        self.ports = list(ports)
        self.shared = list(shared)

    @property
    def names(self):
        return [name for name, _ in self.ports + self.shared]

    @property
    def hardware_names(self):
        return [name for name, _ in self.ports]

    def send(self, message):
        data = [message] if isinstance(message, int) else message
        for destinations in (self.ports, self.shared):
            for entry in list(destinations):
                name, port = entry
                try:
                    port.send_message(data)
                except Exception as exc:
                    # Mid-show failure (unplugged interface): drop the mirror
                    # and play on — the remaining ports keep the show alive.
                    destinations.remove(entry)
                    LOG.warning('MIDI output %r failed (%s) — continuing without it',
                                name, exc)

    def close(self):
        ports, self.ports = self.ports, []
        self.shared = []
        for name, port in ports:
            try:
                port.close_port()
            except Exception as exc:
                LOG.warning('MIDI output %r did not close cleanly: %s', name, exc)


def open_virtual_cue_port(name=VIRTUAL_PORT_NAME):
    """The process-lifetime virtual egress port, or None where unsupported.

    Opened once at application startup — before any set plays — so Keyframes,
    which lists MIDI inputs once when it launches, always finds it. Pass the
    result to every open_egress call; it is closed by process exit, never by
    an egress."""
    import rtmidi
    try:
        output = rtmidi.MidiOut(name='ShowSync')
        output.open_virtual_port(name)
    except Exception as exc:
        # Windows MM has no virtual ports; hardware mirrors still carry the
        # full egress there.
        LOG.warning('Virtual MIDI port %r unavailable (%s) — hardware outputs only',
                    name, exc)
        return None
    LOG.info('MIDI egress: %s (virtual port, open for the process life)', name)
    return (f'{name} (virtual)', output)


def open_egress(selections, virtual=None):
    """Egress over `selections` (names/substrings/indices) plus `virtual`.

    Resolution failures warn and skip — a port missing on this host (or an
    ambiguous substring) must never gate the show. Duplicate selections that
    resolve to the same jack open it once, so no destination ever hears a
    doubled clock. Returns the egress even when nothing opens: the caller
    decides whether silence is acceptable.
    """
    import rtmidi
    ports = []
    opened = set()
    for selection in selections:
        try:
            output = rtmidi.MidiOut()
            index = resolve_midi_port(selection, output.get_ports())
            if index in opened:
                LOG.info('MIDI output %r duplicates an already-open port — skipped', selection)
                continue
            name = output.get_ports()[index]
            output.open_port(index)
        except Exception as exc:
            LOG.warning('MIDI output %r unavailable (%s) — continuing without it',
                        selection, exc)
            continue
        opened.add(index)
        ports.append((name, output))
        LOG.info('MIDI egress: %s', name)
    return MidiEgress(ports, shared=[virtual] if virtual is not None else [])
