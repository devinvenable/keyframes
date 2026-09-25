"""--midi-transport: hardware Start/Continue/Stop drive the set (task 140)."""
import sys
from types import SimpleNamespace

from showsync.transport import (CONTINUE, START, STOP, TransportControl,
                                connect_transport, open_midi_inputs)


class Rig:
    """Set-state fake: records actions and tracks the state they imply."""

    def __init__(self, *, active=False, playing=False):
        self.active, self.playing = active, playing
        self.actions = []
        self.control = TransportControl(
            is_active=lambda: self.active,
            is_playing=lambda: self.active and self.playing,
            is_paused=lambda: self.active and not self.playing,
            start=lambda: self._apply('start'),
            resume=lambda: self._apply('resume'),
            stop=lambda: self._apply('stop'))

    def _apply(self, action):
        self.actions.append(action)
        self.active = action != 'stop'
        self.playing = action != 'stop'

    def handle(self, status):
        return self.control.handle(status)


def test_start_while_stopped_starts():
    rig = Rig()
    assert rig.handle(START) == 'started set'
    assert rig.actions == ['start']


def test_start_while_playing_is_idempotent():
    rig = Rig(active=True, playing=True)
    assert rig.handle(START) is None
    assert rig.actions == []


def test_start_while_paused_resumes():
    rig = Rig(active=True, playing=False)
    assert rig.handle(START) == 'resumed'
    assert rig.actions == ['resume']


def test_continue_resumes_when_paused_else_starts():
    paused = Rig(active=True, playing=False)
    assert paused.handle(CONTINUE) == 'resumed'
    stopped = Rig()
    assert stopped.handle(CONTINUE) == 'started set'
    playing = Rig(active=True, playing=True)
    assert playing.handle(CONTINUE) is None


def test_stop_while_playing_stops():
    rig = Rig(active=True, playing=True)
    assert rig.handle(STOP) == 'stopped set'
    assert rig.actions == ['stop']


def test_stop_while_stopped_or_paused_is_ignored():
    # A pause makes the clock egress emit Stop; a hardware thru path can
    # echo that back. Reacting would kill the paused set — never act on
    # Stop unless playback is genuinely running.
    stopped = Rig()
    assert stopped.handle(STOP) is None
    paused = Rig(active=True, playing=False)
    assert paused.handle(STOP) is None
    assert stopped.actions == paused.actions == []


def test_own_egress_echo_does_not_feed_back():
    # Our clock emits Start when the set starts. If the interface loops it
    # back to the input, it arrives while already playing: no-op.
    rig = Rig()
    rig.handle(START)
    assert rig.handle(START) is None
    assert rig.actions == ['start']


def test_unknown_status_is_ignored():
    rig = Rig(active=True, playing=True)
    assert rig.handle(0xF8) is None
    assert rig.actions == []


class FakeMidiIn:
    def __init__(self, ports):
        self.ports = ports
        self.opened = None
        self.deleted = False
        self.closed = False
        self.callback = None

    def get_ports(self):
        return self.ports

    def open_port(self, index):
        self.opened = index

    def set_callback(self, callback):
        self.callback = callback

    def close_port(self):
        self.closed = True

    def delete(self):
        self.deleted = True


def fake_rtmidi(monkeypatch, ports):
    """Install a fake rtmidi whose MidiIn() yields a fresh instance per call."""
    instances = []

    def make():
        instance = FakeMidiIn(ports)
        instances.append(instance)
        return instance

    monkeypatch.setitem(sys.modules, 'rtmidi', SimpleNamespace(MidiIn=make))
    return instances


def test_opens_every_hardware_port(monkeypatch):
    # The KeyStep can enter on either TBOX jack — both must be heard.
    ports = ['Midi Through 14:0', 'TBOX 2X2 MIDI 1', 'TBOX 2X2 MIDI 2']
    fake_rtmidi(monkeypatch, ports)
    inputs = open_midi_inputs(None)
    assert [i.opened for i in inputs] == [1, 2]


def test_exact_configured_name_orders_first_but_excludes_nothing(monkeypatch):
    ports = ['Midi Through 14:0', 'TBOX 2X2 MIDI 1', 'TBOX 2X2 MIDI 2']
    fake_rtmidi(monkeypatch, ports)
    inputs = open_midi_inputs('TBOX 2X2 MIDI 2')
    assert [i.opened for i in inputs] == [2, 1]


def test_input_skips_software_ports(monkeypatch):
    ports = ['Midi Through 14:0', 'Virtual Raw MIDI 0-0', 'TBOX 2X2 MIDI 1']
    fake_rtmidi(monkeypatch, ports)
    assert [i.opened for i in open_midi_inputs('not-connected')] == [2]


def test_input_returns_empty_without_hardware(monkeypatch):
    instances = fake_rtmidi(monkeypatch, ['Midi Through 14:0'])
    assert open_midi_inputs(None) == []
    (probe,) = instances
    assert probe.deleted and probe.opened is None


def test_failed_port_open_does_not_block_the_others(monkeypatch):
    instances = fake_rtmidi(monkeypatch, ['TBOX 2X2 MIDI 1', 'TBOX 2X2 MIDI 2'])
    original = FakeMidiIn.open_port

    def open_port(self, index):
        if index == 0:
            raise RuntimeError('busy')
        original(self, index)

    monkeypatch.setattr(FakeMidiIn, 'open_port', open_port)
    inputs = open_midi_inputs(None)
    assert [i.opened for i in inputs] == [1]
    # instances[0] is the get_ports probe; instances[1] hit 'busy'.
    assert instances[1].deleted


class FakeSignal:
    """Queued-connection stand-in: emits queue until flush(), like Qt hopping
    from the rtmidi thread to the GUI thread."""

    def __init__(self):
        self.slots, self.pending = [], []

    def connect(self, slot):
        self.slots.append(slot)

    def emit(self, value):
        self.pending.append(value)

    def flush(self):
        while self.pending:
            value = self.pending.pop(0)
            for slot in self.slots:
                slot(value)


def test_connect_transport_hears_every_port_and_closes_all(monkeypatch):
    instances = fake_rtmidi(monkeypatch, ['TBOX 2X2 MIDI 1', 'TBOX 2X2 MIDI 2'])
    owner = SimpleNamespace(transport_received=FakeSignal())
    rig = Rig()
    opened = connect_transport(owner, rig.control)
    listeners = [i for i in instances if i.callback is not None]
    assert len(listeners) == 2
    listeners[1].callback(([START], 0.0))  # Start arriving on the SECOND port
    owner.transport_received.flush()
    assert rig.actions == ['start']
    opened.close_port()
    assert all(i.closed for i in listeners)


def test_start_on_both_ports_queued_together_starts_once(monkeypatch):
    # Both emits land on the queue before the first is handled; the second
    # must be a no-op once handling flips is_active().
    instances = fake_rtmidi(monkeypatch, ['TBOX 2X2 MIDI 1', 'TBOX 2X2 MIDI 2'])
    owner = SimpleNamespace(transport_received=FakeSignal())
    rig = Rig()
    connect_transport(owner, rig.control)
    listeners = [i for i in instances if i.callback is not None]
    for listener in listeners:
        listener.callback(([START], 0.0))
    owner.transport_received.flush()
    assert rig.actions == ['start']


def test_connect_transport_returns_none_without_hardware(monkeypatch):
    fake_rtmidi(monkeypatch, ['Midi Through 14:0'])
    owner = SimpleNamespace(transport_received=FakeSignal())
    assert connect_transport(owner, Rig().control) is None
    assert owner.transport_received.slots == []
