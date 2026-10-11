"""KeyStep CC -> targeted realtime egress -> DIN/TBOX echo regression."""
from types import SimpleNamespace
from dataclasses import replace
import threading
from unittest.mock import Mock

import pytest

from showsync import cli
from showsync.clock import CLOCK, ClockEngine
from showsync.tempomap import TempoEvent, TempoMap
from showsync.egress import MidiEgress, CLOCK_BIT, TRANSPORT_BIT
from showsync.transport import START, STOP, connect_transport
from test_headless import show_factory, loop_recorder, saved_setlist
from test_transport import Rig, FakeSignal, fake_rtmidi
from test_clock import Fake


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
                        keystep_start_quantize='off',
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
                              keystep_start_quantize='off',
                              keystep_send=lambda status: sent.append(status) or True)
    listener = next(i for i in instances if i.callback is not None)
    for cc in (51, 54):
        listener.callback(([0xB0, cc, 127], 0))
    assert sent == []  # remapping must disable the old CCs, not just emit two bytes
    for cc in (20, 21):
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
    ['--keystep-start-quantize', 'measure'],
])
def test_invalid_cc_configuration_is_rejected(args, monkeypatch):
    loop_recorder(monkeypatch, 'main_loop')
    with pytest.raises(SystemExit):
        cli.main(args)


def relay_clock(mode=None, *, offset=0, ramp=False):
    tempo = TempoMap(120, [TempoEvent(.3, 180, .7)] if ramp else [], offset=.1)
    fake = Fake([tempo, tempo])
    relayed, wire = [], []
    rig = Rig(active=True, playing=True)

    def send(status):
        # The suppression stamp belongs to emission, potentially seconds
        # after the press. Exercise a synchronous echo through real control.
        assert fake.engine.transport_egress_age() == 0
        relayed.append((fake.engine._tick, status, fake.time, threading.get_ident()))
        wire.append(('relay', status, fake.engine._tick))
        rig.handle(status)
        return True

    fake.engine = ClockEngine([tempo, tempo], lambda: fake.p,
                              lambda b: wire.append(('clock', b, fake.engine._tick)),
                              now=lambda: fake.time, sleep=fake.advance,
                              keystep_send=send, clock_offset_ms=offset,
                              **({'keystep_start_quantize': mode} if mode is not None else {}))
    rig.control.egress_age = fake.engine.transport_egress_age
    return fake, relayed, wire, rig


def ticks(fake, count):
    target = fake.engine._tick + count
    while fake.engine._tick < target:
        delay = fake.engine.step()
        if fake.engine._tick < target:
            fake.advance(delay)


@pytest.mark.parametrize('mode,grid', [('beat', 24), ('bar', 96)])
@pytest.mark.parametrize('phase', [1, 23, 24, 25, 95, 96, 97])
@pytest.mark.parametrize('offset,ramp', [(0, False), (32, True), (-32, True)])
def test_start_precedes_exact_boundary_f8(mode, grid, phase, offset, ramp, caplog):
    fake, relayed, wire, rig = relay_clock(mode, offset=offset, ramp=ramp)
    ticks(fake, phase)
    fake.advance(.001)  # press between F8s, including just before a boundary
    target = ((phase + grid - 1) // grid) * grid
    old_stamp = fake.engine._transport_stamp
    with caplog.at_level('INFO'):
        assert fake.engine.relay_keystep_transport(START)
        assert relayed == []
        assert fake.engine._transport_stamp == old_stamp
        assert f'Start armed (quantize={mode}, fires in {target - phase} ticks)' in caplog.text
        ticks(fake, target - phase + grid + 1)
    assert [(tick, status) for tick, status, _, _ in relayed] == [(target, START)]
    assert relayed[0][2] == pytest.approx(fake.engine.maps[0].T(target / 24) - offset / 1000)
    i = wire.index(('relay', START, target))
    assert wire[i - 1] == ('clock', CLOCK, target - 1)
    assert wire[i + 1] == ('clock', CLOCK, target)
    assert 'Start emitted on grid' in caplog.text
    assert rig.actions == []


def test_rearm_then_stop_cancels_without_stopping_clock():
    fake, relayed, wire, _ = relay_clock()
    ticks(fake, 31)
    fake.engine.relay_keystep_transport(START)
    ticks(fake, 11)
    fake.engine.relay_keystep_transport(START)
    ticks(fake, 55)
    assert [(tick, b) for tick, b, _, _ in relayed] == [(96, START)]
    fake.engine.relay_keystep_transport(START)
    fake.engine.relay_keystep_transport(STOP)
    assert [(tick, b) for tick, b, _, _ in relayed] == [(96, START), (97, STOP)]
    ticks(fake, 200)
    assert len(relayed) == 2
    assert wire[-1] == ('clock', CLOCK, 296)


@pytest.mark.parametrize('kind', ['gui', 'headless'])
def test_live_cc_play_uses_default_bar_grid(kind, window_factory, show_factory, monkeypatch):
    instances = fake_rtmidi(monkeypatch, ['KeyStep'])
    owner = (window_factory if kind == 'gui' else show_factory)(midi_transport=True)
    fake, relayed, _, _ = relay_clock()
    owner.clock = fake.engine
    ticks(fake, 25)
    listener = next(i for i in instances if i.callback is not None)
    listener.callback(([0xB0, 54, 127], 0))
    assert relayed == []
    ticks(fake, 72)
    assert [(tick, b) for tick, b, _, _ in relayed] == [(96, START)]
    assert owner.audio is None  # CC Play never starts/restarts the backing set


@pytest.mark.parametrize('change', ['pause', 'end', 'song', 'epoch', 'close'])
def test_show_lifecycle_discards_pending_start(change):
    fake, relayed, _, _ = relay_clock()
    ticks(fake, 13)
    fake.engine.relay_keystep_transport(START)
    if change == 'close':
        fake.engine.close()
    else:
        updates = {'pause': {'playing': False}, 'end': {'ended': True},
                   'song': {'song_index': 1, 'song_time': 0},
                   'epoch': {'epoch': 1, 'song_time': 0}}[change]
        fake.p = replace(fake.p, **updates)
        fake.engine.step()
    assert fake.engine._keystep_pending is False
    fake.p = replace(fake.p, playing=True, ended=False)
    ticks(fake, 200)
    assert relayed == []


def test_off_sends_immediately_between_ticks():
    fake, relayed, _, _ = relay_clock('off')
    ticks(fake, 13)
    fake.engine.relay_keystep_transport(START)
    fake.engine.relay_keystep_transport(STOP)
    assert [(tick, b, t) for tick, b, t, _ in relayed] == [
        (13, START, fake.time), (13, STOP, fake.time)]


def test_deferred_start_runs_on_scheduler_thread():
    fake, relayed, _, _ = relay_clock()
    ticks(fake, 13)
    fake.engine.relay_keystep_transport(START)
    caller = threading.get_ident()

    def now():
        fake.advance(.0001)
        if fake.engine._tick > 96:
            fake.engine._halt.set()
        return fake.time

    fake.engine.now = now
    # now() must not advance when checking the suppression stamp in send().
    fake.engine.keystep_send = lambda b: relayed.append((fake.engine._tick, b, threading.get_ident())) or True
    fake.engine.start()
    fake.engine._thread.join(timeout=5)
    assert not fake.engine._thread.is_alive()
    assert fake.engine.error is None
    assert relayed == [(96, START, fake.engine._thread.ident)]
    assert relayed[0][2] != caller


@pytest.mark.parametrize('headless', [False, True])
def test_quantize_cli_reaches_engine_in_both_modes(headless, monkeypatch, tmp_path):
    seen = loop_recorder(monkeypatch, 'headless_loop' if headless else 'main_loop')
    clock = Mock()
    monkeypatch.setattr(cli, 'ClockEngine', clock)
    monkeypatch.setattr(cli, 'AudioEngine', Mock())
    monkeypatch.setattr(cli, 'open_egress', Mock())
    monkeypatch.setattr(cli, 'open_virtual_cue_port', lambda: None)
    args = [saved_setlist(tmp_path)] + (['--headless'] if headless else [])
    for mode in ('off', 'beat', 'bar'):
        assert cli.main(args + ['--keystep-start-quantize', mode]) == 0
        _, _, close = seen['start_engines'](None)
        assert clock.call_args.kwargs.get('keystep_start_quantize') == mode
        close()
    assert cli.build_parser().parse_args([]).keystep_start_quantize == 'bar'
