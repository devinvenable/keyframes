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
    assert fake.messages[-1][1] == START
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
