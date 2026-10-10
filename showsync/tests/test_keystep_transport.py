"""KeyStep CC -> targeted realtime egress -> DIN/TBOX echo regression."""
from types import SimpleNamespace

import pytest

from showsync import cli
from showsync.clock import ClockEngine
from showsync.egress import MidiEgress, CLOCK_BIT, TRANSPORT_BIT
from showsync.transport import START, STOP, connect_transport
from test_headless import show_factory, loop_recorder, saved_setlist
from test_transport import Rig, FakeSignal, fake_rtmidi


@pytest.mark.parametrize('playing', [False, True])
def test_press_edges_relay_only_and_suppress_round_trip(monkeypatch, caplog, playing):
    instances = fake_rtmidi(monkeypatch, ['Arturia KeyStep USB', 'TBOX In 1'])
    owner = SimpleNamespace(transport_received=FakeSignal())
    rig = Rig(active=playing, playing=playing)
    sent, other, virtual = [], [], []
    now = [100.0]
    clock = None

    def send(data):
        # The stamp must precede the actual send, including synchronous echoes.
        assert clock.transport_egress_age() == 0
        sent.append(data)
        rig.handle(data[0])

    egress = MidiEgress([
        ('Arturia KeyStep USB', SimpleNamespace(send_message=send), CLOCK_BIT | TRANSPORT_BIT),
        ('TBOX Out 2', SimpleNamespace(send_message=other.append)),
    ], shared=[('ShowSync Cues', SimpleNamespace(send_message=virtual.append))])
    clock = ClockEngine([], lambda: None, egress.send, now=lambda: now[0],
                        keystep_send=egress.send_keystep_transport)
    rig.control.egress_age = clock.transport_egress_age
    rig.control.relay = clock.relay_keystep_transport
    connect_transport(owner, rig.control)
    key, tbox = [i for i in instances if i.callback is not None]

    def incoming(port, message):
        port.callback((message, 0.0))
        owner.transport_received.flush()

    with caplog.at_level('INFO'):
        # Non-KeyStep CCs, other CCs, notes, partial packets and non-press
        # values cannot relay. Channel 16 presses work just like channel 1.
        for port, message in [(tbox, [0xB0, 51, 127]), (key, [0xB0, 50, 127]),
                              (key, [0x90, 51, 127]), (key, [0xB0, 51]),
                              (key, [0xB0, 51, 64]), (key, [0xB0, 51, 0])]:
            incoming(port, message)
        assert sent == []
        for cc in (51, 54):
            incoming(key, [0xBF, cc, 127])
            incoming(key, [0xBF, cc, 127])  # duplicate while held
            incoming(key, [0xBF, cc, 0])    # release never sends
        assert sent == [[STOP], [START]]
        now[0] += .95  # delayed return via DIN -> thru -> TBOX
        incoming(tbox, [STOP])
        incoming(tbox, [START])
        assert rig.actions == []
        incoming(key, [0xB0, 51, 127])  # release rearmed Stop, even inside gate
    assert sent == [[STOP], [START], [STOP]]
    assert other == virtual == []
    assert rig.actions == [] and rig.playing == playing
    assert sum('translated to realtime' in r.message for r in caplog.records) == 3
    # Relay leaves the clock scheduler untouched, then real transport works
    # again once the echo window has elapsed.
    assert clock._active is False and clock._tick == 0
    now[0] += 1.01
    incoming(tbox, [STOP if playing else START])
    assert rig.actions == ['stop' if playing else 'start']


@pytest.mark.parametrize('send_transport,mask', [(False, 3), (True, CLOCK_BIT)])
def test_relay_respects_transport_preference_and_port_filter(send_transport, mask):
    sent = []
    egress = MidiEgress([('KeyStep', SimpleNamespace(send_message=sent.append), mask)])
    clock = ClockEngine([], lambda: None, egress.send, send_transport=send_transport,
                        keystep_send=egress.send_keystep_transport)
    assert clock.relay_keystep_transport(STOP) is False
    assert sent == []


@pytest.mark.parametrize('kind', ['gui', 'headless'])
def test_cc_remaps_reach_live_gui_and_headless_handlers(
        kind, window_factory, show_factory, monkeypatch):
    instances = fake_rtmidi(monkeypatch, ['KeyStep'])
    factory = window_factory if kind == 'gui' else show_factory
    owner = factory(midi_transport=True, keystep_stop_cc=20, keystep_start_cc=21)
    sent = []
    owner.clock = ClockEngine([], lambda: None, lambda _: None,
                              keystep_send=lambda status: sent.append(status) or True)
    listener = next(i for i in instances if i.callback is not None)
    for cc in (51, 54, 20, 21):
        listener.callback(([0xB0, cc, 127], 0))
    assert sent == [STOP, START]
    assert owner.audio is None  # a KeyStep Play press never starts the set


@pytest.mark.parametrize('headless', [False, True])
def test_cli_passes_cc_remaps_to_both_modes(monkeypatch, tmp_path, headless):
    seen = loop_recorder(monkeypatch, 'headless_loop' if headless else 'main_loop')
    args = [saved_setlist(tmp_path), '--keystep-stop-cc', '22', '--keystep-start-cc', '23']
    assert cli.main(args + (['--headless'] if headless else [])) == 0
    assert (seen['keystep_stop_cc'], seen['keystep_start_cc']) == (22, 23)


@pytest.mark.parametrize('args', [
    ['--keystep-stop-cc', '-1'], ['--keystep-start-cc', '128'],
    ['--keystep-stop-cc', '54'],
])
def test_invalid_cc_configuration_is_rejected(args, monkeypatch):
    loop_recorder(monkeypatch, 'main_loop')
    with pytest.raises(SystemExit):
        cli.main(args)
