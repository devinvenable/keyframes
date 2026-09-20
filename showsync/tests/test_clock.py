from dataclasses import replace
from unittest.mock import Mock

import pytest

from showsync.audio import Position
from showsync.clock import CLOCK, START, STOP, ClockEngine
from showsync.priority import raise_thread_priority
from showsync.tempomap import TempoEvent as E, TempoMap


class Fake:
    def __init__(self, maps):
        self.time = 0.0
        self.p = Position(0, 0, True)
        self.messages = []
        self.engine = ClockEngine(maps, lambda: self.p,
                                  lambda b: self.messages.append((self.time, b)),
                                  now=lambda: self.time, sleep=self.advance)

    def advance(self, dt):
        self.time += dt
        self.p = replace(self.p, song_time=self.p.song_time + dt)


@pytest.mark.parametrize('events', [[], [E(.3, 180, .7)], [E(.1, 60, .8), E(1, 140)]])
def test_exact_tick_times_through_ramps(events):
    tempo = TempoMap(120, events)
    fake = Fake([tempo])
    for _ in range(120):
        delay = fake.engine.step()
        fake.advance(delay)
    ticks = [t for t, b in fake.messages if b == CLOCK]
    assert len(ticks) == 120
    assert ticks == pytest.approx([tempo.T(k / 24) for k in range(120)], abs=1e-9)
    assert fake.messages[0] == (0, START)


def test_pause_resume_skip_end_order():
    fake = Fake([TempoMap(120), TempoMap(90)])
    fake.engine.step()
    fake.p = replace(fake.p, playing=False)
    fake.engine.step()
    fake.engine.step()
    assert [b for _, b in fake.messages] == [START, CLOCK, STOP]
    fake.p = replace(fake.p, playing=True, song_time=.2)
    fake.engine.step()
    assert [b for _, b in fake.messages][-2:] == [START, CLOCK]
    assert fake.engine._tick == 2  # resume emitted the next unsent index, 1
    fake.p = Position(1, 0, True, epoch=1)
    fake.engine.step()
    assert [b for _, b in fake.messages][-3:] == [STOP, START, CLOCK]
    fake.p = replace(fake.p, playing=False, ended=True)
    fake.engine.step()
    fake.engine.close()
    assert [b for _, b in fake.messages][-1] == STOP
    assert all(b in (START, CLOCK, STOP) for _, b in fake.messages)


def test_gap_keeps_ticks_and_next_song_restarts():
    fake = Fake([TempoMap(120, [E(.2, 180, .4)]), TempoMap(90)])
    fake.engine.step()
    fake.p = replace(fake.p, song_time=.8, gap=True)
    fake.engine.step()
    assert sum(b == START for _, b in fake.messages) == 1
    assert fake.messages[-1][1] == CLOCK
    fake.p = Position(1, 0, True)
    fake.engine.step()
    assert [b for _, b in fake.messages][-3:] == [STOP, START, CLOCK]


def test_end_of_set_restart_stop_then_start_at_song_one_tempo():
    fake = Fake([TempoMap(100), TempoMap(140)])
    fake.p = Position(1, 0, True, epoch=1)
    fake.engine.step()
    fake.p = replace(fake.p, playing=False, ended=True)
    fake.engine.step()
    assert [b for _, b in fake.messages] == [START, CLOCK, STOP]
    base = fake.time
    fake.p = Position(0, 0, True, epoch=2)  # restart: audio back at song 1
    for _ in range(24):
        fake.advance(fake.engine.step())
    resumed = fake.messages[3:]
    assert resumed[0][1] == START
    ticks = [t - base for t, b in resumed if b == CLOCK]
    assert len(ticks) == 24
    # Clock resumes at song 1's 100 BPM, not the 140 BPM the set ended on.
    assert ticks == pytest.approx([TempoMap(100).T(k / 24) for k in range(24)], abs=1e-9)


def test_late_tick_does_not_shift_following_ticks_or_burst():
    fake = Fake([TempoMap(120)])
    fake.engine.step()
    fake.advance(.2)
    delay = fake.engine.step()
    assert len(fake.messages) == 3
    assert fake.engine.dropped_ticks == 8
    assert fake.time + delay == pytest.approx(10 / 48)


def test_sleep_then_spin_is_driven_by_audio():
    fake = Fake([TempoMap(120)])
    def now():
        fake.advance(.0001)
        if fake.time >= .065:
            fake.engine._halt.set()
        return fake.time
    sleeps = []
    def sleep(dt):
        sleeps.append(dt)
        fake.advance(dt)
    fake.engine.now, fake.engine.sleep = now, sleep
    fake.engine._run()
    assert sleeps and max(sleeps) <= .01
    assert [b for _, b in fake.messages][-1] == STOP
    ticks = [t for t, b in fake.messages if b == CLOCK]
    assert ticks == pytest.approx([k / 48 for k in range(len(ticks))], abs=.00011)


@pytest.mark.parametrize('allowed', [True, False])
def test_windows_priority_mock(allowed):
    api = Mock()
    api.GetCurrentThread.return_value = 42
    api.SetThreadPriority.return_value = int(allowed)
    assert raise_thread_priority(platform='win32', windows=api) is allowed
    api.SetThreadPriority.assert_called_once_with(42, 2)


def test_posix_priority_denial_nonfatal():
    api = Mock()
    api.sched_setscheduler.side_effect = PermissionError('denied')
    assert raise_thread_priority(platform='linux', posix=api) is False


def test_mac_priority_mock():
    api = Mock()
    api.pthread_setschedparam.return_value = 0
    assert raise_thread_priority(platform='darwin', posix=api)
    assert api.pthread_setschedparam.call_args.args[1] == 2


def test_lead_in_sends_start_but_no_ticks_until_offset():
    # First-beat offset: Start still opens the song (slaves reset and wait for
    # F8), the lead-in is tick-free, and tick 0 fires exactly at the offset.
    fake = Fake([TempoMap(120, offset=2.0)])
    while fake.p.song_time < 3:
        fake.advance(fake.engine.step())
    assert fake.messages[0] == (0, START)
    ticks = [t for t, b in fake.messages if b == CLOCK]
    assert ticks[0] == pytest.approx(2.0)
    assert min(ticks) >= 2.0
    assert ticks[1] - ticks[0] == pytest.approx(60 / 120 / 24)


@pytest.mark.parametrize('offset', [-250, -32, 32, 250])
@pytest.mark.parametrize('events', [[], [E(.5, 180, 1)]])
def test_clock_offset_shifts_ticks_exactly(offset, events):
    tempo = TempoMap(120, events, offset=.5)
    fake = Fake([tempo])
    fake.engine.clock_offset_ms = offset
    while len([b for _, b in fake.messages if b == CLOCK]) < 80:
        fake.advance(fake.engine.step())
    ticks = [t for t, b in fake.messages if b == CLOCK]
    assert ticks == pytest.approx([tempo.T(k / 24) - offset / 1000 for k in range(80)], abs=1e-9)


@pytest.mark.parametrize('offset', [-32, 32])
def test_live_offset_keeps_transport_and_absolute_phase(offset):
    tempo = TempoMap(120)
    fake = Fake([tempo])
    for _ in range(48):
        fake.advance(fake.engine.step())
    before = fake.p
    fake.engine.clock_offset_ms = offset
    for _ in range(30):
        fake.advance(fake.engine.step())
    assert fake.p.epoch == before.epoch
    assert [b for _, b in fake.messages if b != CLOCK] == [START]
    ticks = [t for t, b in fake.messages if b == CLOCK][-20:]
    # Settled timestamps are on the shifted absolute grid, including after drops.
    assert [(t + offset / 1000) * 48 for t in ticks] == pytest.approx(
        [round((t + offset / 1000) * 48) for t in ticks], abs=1e-8)
    assert fake.engine.dropped_ticks == (1 if offset > 0 else 0)


@pytest.mark.parametrize('offset', [-32, 32])
def test_offset_survives_skip_restart(offset):
    maps = [TempoMap(120, offset=.5), TempoMap(90, offset=.5)]
    fake = Fake(maps)
    fake.engine.clock_offset_ms = offset
    for epoch, song in enumerate([0, 1, 0]):
        fake.p = Position(song, 0, True, epoch=epoch)
        fake.messages.clear()
        base = fake.time
        for _ in range(4):
            fake.advance(fake.engine.step())
        ticks = [t - base for t, b in fake.messages if b == CLOCK]
        assert ticks == pytest.approx([maps[song].T(k / 24) - offset / 1000 for k in range(3)])


@pytest.mark.parametrize('offset', [32, 250])
@pytest.mark.parametrize('events', [[], [E(.3, 180, .7)]])
def test_positive_offset_preserves_startup_indices_and_slave_steps(offset, events):
    tempo = TempoMap(100, events)
    fake = Fake([tempo, tempo])
    fake.engine.clock_offset_ms = offset
    indices = []
    def send(byte):
        fake.messages.append((fake.time, byte))
        if byte == CLOCK:
            indices.append(fake.engine._tick)
    fake.engine.send = send
    # Initial play, gap -> next song, and restart all reset the slave counter.
    for epoch, song in [(0, 0), (0, 1), (1, 0)]:
        fake.p = Position(song, 0, True, epoch=epoch)
        fake.messages.clear()
        indices.clear()
        base = fake.time
        for _ in range(96):
            fake.advance(fake.engine.step())
        ticks = [t - base for t, b in fake.messages if b == CLOCK]
        expected = [max(0, tempo.T(k / 24) - offset / 1000) for k in range(96)]
        assert indices == list(range(96))
        assert ticks == pytest.approx(expected, abs=1e-9)
        assert ticks[0] == ticks[1] == 0
        assert fake.engine.dropped_ticks == 0
        # Model a six-clocks-per-step slave using ONLY received clock counts.
        slave_steps = [t for count, t in enumerate(ticks) if count % 6 == 0]
        assert slave_steps == pytest.approx(
            [max(0, tempo.T(step / 4) - offset / 1000) for step in range(16)], abs=1e-9)
        fake.p = replace(fake.p, gap=True)
        fake.advance(fake.engine.step())


@pytest.mark.parametrize('enabled', [True, False])
@pytest.mark.parametrize('close_active', [True, False])
def test_transport_toggle_message_sequences(enabled, close_active):
    fake = Fake([TempoMap(100), TempoMap(100)])
    fake.engine.send_transport = enabled
    fake.engine.clock_offset_ms = 32
    expected = []
    for epoch, song in [(0, 0), (0, 1), (1, 0)]:
        fake.p = Position(song, 0, True, epoch=epoch)
        for _ in range(3):
            fake.advance(fake.engine.step())
        if expected:
            expected.append(STOP)
        expected.extend([START, CLOCK, CLOCK, CLOCK])
    fake.p = replace(fake.p, playing=False)
    fake.engine.step()
    expected.append(STOP)
    fake.p = replace(fake.p, playing=True)
    fake.advance(fake.engine.step())
    fake.engine.step()
    expected.extend([START, CLOCK, CLOCK])
    if not close_active:
        fake.p = replace(fake.p, ended=True)
        fake.engine.step()
    fake.engine.close()
    expected.append(STOP)
    assert [b for _, b in fake.messages] == (expected if enabled else [b for b in expected if b == CLOCK])
