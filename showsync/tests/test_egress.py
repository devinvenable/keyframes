"""Multi-port MIDI egress: resolution, mirroring, and live-set survivability."""
import sys
from types import SimpleNamespace

import pytest

from showsync.clock import resolve_midi_port
from showsync.egress import VIRTUAL_PORT_NAME, MidiEgress, open_egress

PORTS = ['MIDIPLUS TBOX 2x2:MIDIPLUS TBOX 2x2 Midi Out 1 36:0',
         'MIDIPLUS TBOX 2x2:MIDIPLUS TBOX 2x2 Midi Out 2 36:1',
         'Arturia KeyStep 32:KeyStep 32 28:0']


class FakeOutput:
    """Stands in for rtmidi.MidiOut; the module-level log records every call."""
    ports = list(PORTS)
    log = []
    fail_virtual = False

    def __init__(self, name=None):
        self.opened = None

    def get_ports(self):
        return list(self.ports)

    def open_port(self, index):
        self.opened = self.ports[index]
        FakeOutput.log.append(('open', self.opened))

    def open_virtual_port(self, name):
        if FakeOutput.fail_virtual:
            raise RuntimeError('no virtual ports on this API')
        self.opened = name
        FakeOutput.log.append(('open-virtual', name))

    def send_message(self, data):
        FakeOutput.log.append(('send', self.opened, tuple(data)))

    def close_port(self):
        FakeOutput.log.append(('close', self.opened))


@pytest.fixture
def fake_rtmidi(monkeypatch):
    FakeOutput.ports = list(PORTS)
    FakeOutput.log = []
    FakeOutput.fail_virtual = False
    monkeypatch.setitem(sys.modules, 'rtmidi', SimpleNamespace(MidiOut=FakeOutput))
    return FakeOutput


# --- resolve_midi_port (task 258: stage-stable matching) ---

def test_exact_name_still_resolves():
    assert resolve_midi_port(PORTS[1], PORTS) == 1


def test_unique_substring_resolves_case_insensitively():
    assert resolve_midi_port('midi out 2', PORTS) == 1
    assert resolve_midi_port('KeyStep', PORTS) == 2


def test_ambiguous_substring_raises_with_candidates():
    with pytest.raises(ValueError) as caught:
        resolve_midi_port('Midi Out', PORTS)
    assert 'ambiguous' in str(caught.value)
    assert 'Midi Out 1' in str(caught.value) and 'Midi Out 2' in str(caught.value)


def test_no_match_raises_listing_available():
    with pytest.raises(ValueError) as caught:
        resolve_midi_port('Missing synth', PORTS)
    assert 'KeyStep' in str(caught.value)


def test_index_selection_unchanged():
    assert resolve_midi_port('2', PORTS) == 2
    assert resolve_midi_port(0, PORTS) == 0
    with pytest.raises(ValueError):
        resolve_midi_port('9', PORTS)


def test_exact_name_wins_over_substring_of_another():
    # A port whose full name is a substring of a sibling must resolve to itself.
    ports = ['Synth', 'Synth XL']
    assert resolve_midi_port('Synth', ports) == 0


# --- open_egress ---

def test_egress_opens_mirrors_and_virtual_port(fake_rtmidi):
    egress = open_egress(['midi out 1', 'Midi Out 2', 'KeyStep'])
    assert egress.hardware_names == PORTS
    assert any(VIRTUAL_PORT_NAME in name for name in egress.names)
    assert ('open-virtual', VIRTUAL_PORT_NAME) in fake_rtmidi.log


def test_identical_bytes_reach_every_port(fake_rtmidi):
    egress = open_egress(['midi out 1', 'KeyStep'])
    egress.send(0xF8)
    egress.send((0xC0, 3))
    sends = [entry for entry in fake_rtmidi.log if entry[0] == 'send']
    destinations = {entry[1] for entry in sends}
    assert destinations == {PORTS[0], PORTS[2], VIRTUAL_PORT_NAME}
    for destination in destinations:
        assert [e[2] for e in sends if e[1] == destination] == [(0xF8,), (0xC0, 3)]


def test_missing_and_ambiguous_ports_warn_but_play(fake_rtmidi, caplog):
    egress = open_egress(['Missing synth', 'Midi Out', 'KeyStep'])
    assert egress.hardware_names == [PORTS[2]]
    assert 'Missing synth' in caplog.text and 'Midi Out' in caplog.text
    egress.send(0xF8)  # the surviving ports still carry the clock
    assert ('send', PORTS[2], (0xF8,)) in fake_rtmidi.log


def test_duplicate_selections_open_the_jack_once(fake_rtmidi):
    egress = open_egress(['midi out 2', PORTS[1], '1'])
    assert egress.hardware_names == [PORTS[1]]
    egress.send(0xF8)
    assert [e for e in fake_rtmidi.log if e == ('send', PORTS[1], (0xF8,))] \
        == [('send', PORTS[1], (0xF8,))]


def test_virtual_port_failure_degrades_to_hardware_only(fake_rtmidi, caplog):
    fake_rtmidi.fail_virtual = True
    egress = open_egress(['KeyStep'])
    assert egress.names == [PORTS[2]]
    assert VIRTUAL_PORT_NAME in caplog.text


def test_dead_port_is_dropped_and_the_show_goes_on(fake_rtmidi, caplog):
    egress = open_egress(['midi out 1', 'KeyStep'])
    victim = next(port for name, port in egress.ports if name == PORTS[0])
    def explode(data):
        raise RuntimeError('USB gone')
    victim.send_message = explode
    egress.send(0xF8)
    assert PORTS[0] not in egress.names
    assert 'continuing without it' in caplog.text
    before = len(fake_rtmidi.log)
    egress.send(0xFA)
    sends = [e for e in fake_rtmidi.log[before:] if e[0] == 'send']
    assert {e[1] for e in sends} == {PORTS[2], VIRTUAL_PORT_NAME}


def test_close_closes_every_port_and_empties_the_egress(fake_rtmidi):
    egress = open_egress(['midi out 1'])
    egress.close()
    closed = {entry[1] for entry in fake_rtmidi.log if entry[0] == 'close'}
    assert closed == {PORTS[0], VIRTUAL_PORT_NAME}
    assert egress.names == []


def test_empty_selection_still_offers_the_virtual_cue_port(fake_rtmidi):
    egress = open_egress([])
    assert egress.hardware_names == []
    assert egress.names == [f'{VIRTUAL_PORT_NAME} (virtual)']
    egress.send(0xF8)
    assert ('send', VIRTUAL_PORT_NAME, (0xF8,)) in fake_rtmidi.log
