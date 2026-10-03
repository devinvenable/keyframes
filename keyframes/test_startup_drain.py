"""Startup MIDI drain — stale events queued on an input port before launch
must be read-and-dropped before the main loop starts, or they replay as a
phantom scene cycle / media triggers with no key pressed (task 218)."""
import os

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')

import mido

from main import drain_startup_midi


class FakeClock:
    """Monotonic stand-in the sleep stub advances deterministically."""

    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class FakePort:
    """Input port whose queue can be refilled while the drain is polling."""

    def __init__(self, pending=(), late=None):
        self.pending = list(pending)
        # poll count -> messages that "arrive" on that poll, to model events
        # the OS delivers shortly after open rather than instantly.
        self.late = dict(late or {})
        self.polls = 0

    def iter_pending(self):
        self.polls += 1
        self.pending.extend(self.late.pop(self.polls, ()))
        while self.pending:
            yield self.pending.pop(0)


def note_on(note=60):
    return mido.Message('note_on', note=note, velocity=100)


def test_drain_discards_everything_pending_at_open():
    clock = FakeClock()
    port = FakePort(pending=[note_on(60 + i) for i in range(5)])
    drained = drain_startup_midi([port], settle_seconds=0.25,
                                 sleep=clock.sleep, clock=clock)
    assert drained == 5
    assert port.pending == []


def test_drain_keeps_polling_through_the_settle_window():
    # Messages arriving a few polls after open (OS-buffered delivery) are
    # still discarded — a single immediate read would miss them.
    clock = FakeClock()
    port = FakePort(pending=[note_on()], late={3: [note_on(), note_on()]})
    drained = drain_startup_midi([port], settle_seconds=0.25,
                                 sleep=clock.sleep, clock=clock)
    assert drained == 3
    assert port.pending == []
    assert port.polls > 3


def test_drain_covers_all_ports_and_reports_zero_when_clean():
    clock = FakeClock()
    a, b = FakePort(pending=[note_on()]), FakePort()
    assert drain_startup_midi([a, b], settle_seconds=0.05,
                              sleep=clock.sleep, clock=clock) == 1
    clock2 = FakeClock()
    assert drain_startup_midi([FakePort()], settle_seconds=0.05,
                              sleep=clock2.sleep, clock=clock2) == 0
