"""Multi-port MIDI egress: resolution, mirroring, and live-set survivability."""
import sys
from types import SimpleNamespace

import pytest

from showsync.clock import resolve_midi_port
from showsync.egress import (VIRTUAL_PORT_NAME, MidiEgress, open_egress,
                             open_virtual_cue_port)

PORTS = ['MIDIPLUS TBOX 2x2:MIDIPLUS TBOX 2x2 Midi Out 1 36:0',
         'MIDIPLUS TBOX 2x2:MIDIPLUS TBOX 2x2 Midi Out 2 36:1',
         'Arturia KeyStep 32:KeyStep 32 28:0']


class FakeOutput:
    """Stands in for rtmidi.MidiOut; the module-level log records every call."""
    ports = list(PORTS)
    log = []
    fail_virtual = False

    def __init__(self, name=None):
        self.name = name
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
    egress = open_egress(['midi out 1', 'Midi Out 2', 'KeyStep'],
                         virtual=open_virtual_cue_port())
    assert egress.hardware_names == PORTS
    assert [port.name for _, port, _ in egress.ports] == ['ShowSync Egress'] * len(PORTS)
    assert any(VIRTUAL_PORT_NAME in name for name in egress.names)
    assert ('open-virtual', VIRTUAL_PORT_NAME) in fake_rtmidi.log


def test_identical_bytes_reach_every_port(fake_rtmidi):
    egress = open_egress(['midi out 1', 'KeyStep'], virtual=open_virtual_cue_port())
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
    assert open_virtual_cue_port() is None
    assert VIRTUAL_PORT_NAME in caplog.text
    egress = open_egress(['KeyStep'], virtual=None)
    assert egress.names == [PORTS[2]]


def test_dead_port_is_dropped_and_the_show_goes_on(fake_rtmidi, caplog):
    egress = open_egress(['midi out 1', 'KeyStep'], virtual=open_virtual_cue_port())
    victim = next(port for name, port, _ in egress.ports if name == PORTS[0])
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


def test_close_closes_mirrors_but_never_the_shared_virtual_port(fake_rtmidi):
    # Keyframes lists its inputs once at launch: the virtual cue port lives
    # for the whole process, across GUI set stops and restarts.
    egress = open_egress(['midi out 1'], virtual=open_virtual_cue_port())
    egress.close()
    closed = {entry[1] for entry in fake_rtmidi.log if entry[0] == 'close'}
    assert closed == {PORTS[0]}
    assert egress.names == []


def test_empty_selection_still_offers_the_virtual_cue_port(fake_rtmidi):
    egress = open_egress([], virtual=open_virtual_cue_port())
    assert egress.hardware_names == []
    assert egress.names == [f'{VIRTUAL_PORT_NAME} (virtual)']
    egress.send(0xF8)
    assert ('send', VIRTUAL_PORT_NAME, (0xF8,)) in fake_rtmidi.log


# --- per-port egress filtering (task 261: rig topology v3) ---

# Every class of byte the engine actually emits: clock, the three realtime
# transport bytes, and cue traffic (PC, the Keyframes CCs, file-event notes).
CLASSED = [((0xF8,), 'clock'),
           ((0xFA,), 'transport'), ((0xFB,), 'transport'), ((0xFC,), 'transport'),
           ((0xC0, 3), 'cues'), ((0xB0 | 15, 102, 1), 'cues'),
           ((0x90, 60, 100), 'cues')]


def sends_to(log, destination):
    return [entry[2] for entry in log if entry[0] == 'send' and entry[1] == destination]


def test_clock_only_port_hears_clock_and_nothing_else(fake_rtmidi):
    from showsync.setlist import EgressFilter
    egress = open_egress([EgressFilter('KeyStep', ('clock',)), 'midi out 1'],
                         virtual=open_virtual_cue_port())
    for message, _ in CLASSED:
        egress.send(list(message) if len(message) > 1 else message[0])
    assert sends_to(fake_rtmidi.log, PORTS[2]) == [(0xF8,)]
    # Bare entries and the virtual cue port still carry the full egress.
    everything = [message for message, _ in CLASSED]
    assert sends_to(fake_rtmidi.log, PORTS[0]) == everything
    assert sends_to(fake_rtmidi.log, VIRTUAL_PORT_NAME) == everything


def test_transport_and_cues_subset(fake_rtmidi):
    from showsync.setlist import EgressFilter
    egress = open_egress([EgressFilter('midi out 2', ('transport', 'cues'))])
    for message, _ in CLASSED:
        egress.send(list(message) if len(message) > 1 else message[0])
    expected = [message for message, kind in CLASSED if kind != 'clock']
    assert sends_to(fake_rtmidi.log, PORTS[1]) == expected


def test_duplicate_selections_merge_their_filters(fake_rtmidi):
    from showsync.setlist import EgressFilter
    egress = open_egress([EgressFilter('midi out 2', ('clock',)),
                          EgressFilter(PORTS[1], ('transport',))])
    assert egress.hardware_names == [PORTS[1]]  # the jack opened once
    egress.send(0xF8)
    egress.send(0xFA)
    egress.send([0xC0, 3])
    assert sends_to(fake_rtmidi.log, PORTS[1]) == [(0xF8,), (0xFA,)]


@pytest.mark.parametrize('target', [None, 'KeyStep', PORTS[2], 2,
                                     'Midi Out 2', PORTS[1], 1,
                                     'Missing synth', 'Midi Out', 99])
def test_file_playback_obeys_filters_through_cli(target, fake_rtmidi, monkeypatch, tmp_path):
    """Real file + CLI wiring + scheduler, with hardware replaced by fakes.

    File PC/CC bytes deliberately match visual cues: only origin differs.
    """
    from dataclasses import replace
    import mido
    from showsync import cli
    from showsync.audio import Position
    from showsync.clock import ClockEngine
    from showsync.midifile import load_midi_events
    from showsync.setlist import Setlist, Song, EgressFilter
    from showsync.tempomap import TempoMap
    from showsync.visuals import KeyframesCue, song_controls

    path = tmp_path / 'song.mid'
    source = mido.MidiFile()
    source.tracks.append(mido.MidiTrack([
        mido.Message('program_change', channel=15, program=1),
        mido.Message('control_change', channel=15, control=102, value=0),
        mido.Message('sysex', data=(0x7e, 0x7f, 9, 1)),
        mido.Message('note_on', note=60, velocity=100),
        mido.Message('note_off', note=60, time=480),
    ]))
    source.save(path)
    song = Song('Intro', tmp_path / 'audio.wav', 120, midi=path, midi_port=target,
                keyframes=KeyframesCue(bank='visuals'))
    setlist = Setlist('Show', (song,), keyframes_banks=('visuals',), midi_outputs=(
        EgressFilter('KeyStep', ('clock', 'transport')),
        EgressFilter('Midi Out 2', ('clock', 'file')),
    ))
    position = [Position(0, 0, True)]
    audio = SimpleNamespace(maps=[TempoMap(120)], position=lambda: position[0],
                            _layout=SimpleNamespace(setlist=setlist),
                            start=lambda: None, close=lambda: None)
    monkeypatch.setattr(cli, 'AudioEngine', lambda *a, **kw: audio)
    monkeypatch.setattr(ClockEngine, 'start', lambda self: None)
    monkeypatch.setattr(cli, 'last_setlist', lambda: None)
    callbacks = {}
    monkeypatch.setattr(cli, 'main_loop', lambda doc, **kw: callbacks.update(kw) or 0)
    assert cli.main([]) == 0
    _, clock, close = callbacks['start_engines'](setlist)
    clock.step()
    position[0] = replace(position[0], song_time=.5)
    clock.step()
    close()

    file = [event.data for event in load_midi_events(path)]
    flush = [(0xB0, 64, 0), (0xB0, 123, 0)]
    cues = list(song_controls(setlist)[0])
    assert sends_to(fake_rtmidi.log, PORTS[2]) == [(0xFA,), (0xF8,), (0xF8,), (0xFC,)]
    gets_file = target in (None, 'Midi Out 2', PORTS[1], 1)
    assert sends_to(fake_rtmidi.log, PORTS[1]) == (
        file[:-1] + [(0xF8,), file[-1], (0xF8,)] + flush
        if gets_file else [(0xF8,), (0xF8,)])
    assert sends_to(fake_rtmidi.log, VIRTUAL_PORT_NAME) == (
        cues + [(0xFA,)] + file[:-1] + [(0xF8,), file[-1], (0xF8,)] + flush + [(0xFC,)]
        if target is None else cues + [(0xFA,), (0xF8,), (0xF8,), (0xFC,)])
    assert sends_to(fake_rtmidi.log, PORTS[0]) == []
    assert fake_rtmidi.log.count(('open', PORTS[1])) == 1
    assert fake_rtmidi.log.count(('open', PORTS[2])) == 1


def test_file_route_keeps_dead_mirror_dropped(fake_rtmidi):
    from showsync.setlist import EgressFilter
    egress = open_egress([EgressFilter('Midi Out 2', ('clock', 'file'))],
                         virtual=open_virtual_cue_port())
    route = egress.open_file_output('Midi Out 2')
    port = egress.ports[0][1]
    def unplugged(message):
        raise RuntimeError('disconnected')
    port.send_message = unplugged
    route.send_message((0x90, 60, 100))
    # A later song must not reopen a failed mirror as an unfiltered output.
    egress.open_file_output(1).send_message((0x90, 61, 100))
    egress.send(0xF8)
    assert egress.hardware_names == []
    assert sends_to(fake_rtmidi.log, PORTS[1]) == []
    assert sends_to(fake_rtmidi.log, VIRTUAL_PORT_NAME) == [(0xF8,)]
    assert fake_rtmidi.log.count(('open', PORTS[1])) == 1


def test_file_route_close_preserves_mirror_and_owns_separate_synth(fake_rtmidi):
    from showsync.setlist import EgressFilter
    egress = open_egress([EgressFilter('KeyStep', ('clock', 'transport'))])
    egress.open_file_output('KeyStep').close_port()
    assert not [e for e in fake_rtmidi.log if e[0] == 'close']
    route = egress.open_file_output('Midi Out 2')
    route.send_message((0x90, 60, 100))
    route.close_port()
    egress.send(0xF8)
    assert sends_to(fake_rtmidi.log, PORTS[1]) == [(0x90, 60, 100)]
    assert sends_to(fake_rtmidi.log, PORTS[2]) == [(0xF8,)]
    assert [e for e in fake_rtmidi.log if e[0] == 'close'] == [('close', PORTS[1])]


@pytest.mark.parametrize('failure', ['open', 'missing', 'ambiguous'])
def test_failed_mirror_open_cannot_be_reopened_unfiltered(failure, fake_rtmidi, monkeypatch):
    from showsync.setlist import EgressFilter
    original = fake_rtmidi.open_port
    def fail_once(self, index):
        monkeypatch.setattr(fake_rtmidi, 'open_port', original)
        raise RuntimeError('busy')
    if failure == 'open':
        monkeypatch.setattr(fake_rtmidi, 'open_port', fail_once)
    elif failure == 'missing':
        fake_rtmidi.ports = PORTS[:2]
    else:
        fake_rtmidi.ports = PORTS + ['KeyStep Second']
    egress = open_egress([EgressFilter('KeyStep', ('clock', 'transport'))])
    fake_rtmidi.ports = list(PORTS)
    egress.open_file_output(PORTS[2]).send_message((0x90, 60, 100))
    assert sends_to(fake_rtmidi.log, PORTS[2]) == []
    assert ('open', PORTS[2]) not in fake_rtmidi.log
