"""--midi-transport: hardware Start/Continue/Stop drive the set (task 140)."""
import sys
from types import SimpleNamespace

from showsync.transport import CONTINUE, START, STOP, TransportControl, open_midi_input


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

    def get_ports(self):
        return self.ports

    def open_port(self, index):
        self.opened = index

    def delete(self):
        self.deleted = True


def fake_rtmidi(monkeypatch, ports):
    instance = FakeMidiIn(ports)
    monkeypatch.setitem(sys.modules, 'rtmidi', SimpleNamespace(MidiIn=lambda: instance))
    return instance


def test_input_prefers_exact_configured_name(monkeypatch):
    ports = ['Midi Through 14:0', 'TBOX 2X2 MIDI 1', 'TBOX 2X2 MIDI 2']
    instance = fake_rtmidi(monkeypatch, ports)
    assert open_midi_input('TBOX 2X2 MIDI 2') is instance
    assert instance.opened == 2


def test_input_falls_back_to_first_hardware_port(monkeypatch):
    ports = ['Midi Through 14:0', 'Virtual Raw MIDI 0-0', 'TBOX 2X2 MIDI 1']
    instance = fake_rtmidi(monkeypatch, ports)
    assert open_midi_input('not-connected') is instance
    assert instance.opened == 2


def test_input_returns_none_without_hardware(monkeypatch):
    instance = fake_rtmidi(monkeypatch, ['Midi Through 14:0'])
    assert open_midi_input(None) is None
    assert instance.deleted and instance.opened is None
