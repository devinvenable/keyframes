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

# Per-port egress classes (task 261): a setlist midi_outputs entry may limit
# a mirror to a subset. 'cues' is everything that is neither clock nor
# realtime transport — the Keyframes PC/CC cues and any file events routed
# through the clock port. The virtual cue port always carries all three.
CLOCK_BIT, TRANSPORT_BIT, CUES_BIT = 1, 2, 4
ALL_CLASSES = CLOCK_BIT | TRANSPORT_BIT | CUES_BIT
CLASS_BITS = {'clock': CLOCK_BIT, 'transport': TRANSPORT_BIT, 'cues': CUES_BIT}


def classes_mask(send):
    """Bitmask for a midi_outputs `send:` list; None/empty = full egress."""
    if not send:
        return ALL_CLASSES
    mask = 0
    for name in send:
        mask |= CLASS_BITS[name]
    return mask


def _normalize(entries):
    # (name, output) 2-tuples are full-egress legacy spellings.
    return [entry if len(entry) == 3 else (entry[0], entry[1], ALL_CLASSES)
            for entry in entries]


class MidiEgress:
    """Open MIDI outputs sent to as one; identical bytes on every port
    (minus each port's class filter)."""

    def __init__(self, ports, shared=()):
        # [(display name, rtmidi output, class mask)] — lists mutate only on
        # send failure. `ports` (the mirrors) are owned and closed with the
        # egress; `shared` (the virtual cue port) outlives it — Keyframes
        # enumerates its inputs once at startup, so that port must exist for
        # the whole process, not just while a set is playing.
        self.ports = _normalize(ports)
        self.shared = _normalize(shared)

    @property
    def names(self):
        return [name for name, _, _ in self.ports + self.shared]

    @property
    def hardware_names(self):
        return [name for name, _, _ in self.ports]

    def send(self, message):
        self._send(message, (self.ports, self.shared))

    def send_keystep_transport(self, status):
        """Relay only to already-open KeyStep hardware; keep its class filter."""
        return self._send(status, (self.ports,), keystep_only=True)

    def _send(self, message, groups, *, keystep_only=False):
        data = [message] if isinstance(message, int) else message
        status = data[0]
        # 0xFA Start / 0xFB Continue / 0xFC Stop are the transport class.
        bit = CLOCK_BIT if status == 0xF8 else \
            TRANSPORT_BIT if 0xFA <= status <= 0xFC else CUES_BIT
        sent = False
        for destinations in groups:
            for entry in list(destinations):
                name, port, mask = entry
                if keystep_only and 'keystep' not in name.lower():
                    continue
                if not mask & bit:
                    continue
                try:
                    port.send_message(data)
                    sent = True
                except Exception as exc:
                    # Mid-show failure (unplugged interface): drop the mirror
                    # and play on — the remaining ports keep the show alive.
                    destinations.remove(entry)
                    LOG.warning('MIDI output %r failed (%s) — continuing without it',
                                name, exc)
        return sent

    def close(self):
        ports, self.ports = self.ports, []
        self.shared = []
        for name, port, _ in ports:
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

    A selection may also be a filtered entry (anything with `port` and `send`
    attributes, e.g. setlist.EgressFilter) limiting that mirror to a subset of
    the egress classes; bare selections carry everything. Resolution failures
    warn and skip — a port missing on this host (or an ambiguous substring)
    must never gate the show. Duplicate selections that resolve to the same
    jack open it once (their class filters are merged), so no destination
    ever hears a doubled clock. Returns the egress even when nothing opens:
    the caller decides whether silence is acceptable.
    """
    import rtmidi
    ports = []
    opened = {}  # resolved port index -> position in `ports`
    for selection in selections:
        matcher = getattr(selection, 'port', selection)
        mask = classes_mask(getattr(selection, 'send', None))
        try:
            output = rtmidi.MidiOut(name='ShowSync Egress')
            index = resolve_midi_port(matcher, output.get_ports())
            if index in opened:
                name, port, had = ports[opened[index]]
                ports[opened[index]] = (name, port, had | mask)
                LOG.info('MIDI output %r duplicates an already-open port — merged', matcher)
                continue
            name = output.get_ports()[index]
            output.open_port(index)
        except Exception as exc:
            LOG.warning('MIDI output %r unavailable (%s) — continuing without it',
                        matcher, exc)
            continue
        opened[index] = len(ports)
        ports.append((name, output, mask))
        LOG.info('MIDI egress: %s%s', name,
                 '' if mask == ALL_CLASSES else
                 f" ({'+'.join(c for c in CLASS_BITS if CLASS_BITS[c] & mask)} only)")
    return MidiEgress(ports, shared=[virtual] if virtual is not None else [])
