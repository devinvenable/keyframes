"""Song-boundary re-anchor under the live rig wiring (task 304).

These tests run the ClockEngine against the production egress shape from the
D17 config: a KeyStep hardware mirror filtered to clock+transport, a full
mirror, and the shared ShowSync Cues virtual port, with the KeyStep relay and
--keystep-start-quantize wired exactly as cli.start_engines does. A slave
model counts what the KeyStep port actually hears, the way a drum machine
does: Start resets the pattern, the first following F8 is its one.
"""
from bisect import bisect_right
from pathlib import Path
from types import SimpleNamespace

import pytest

from showsync.audio import AudioEngine, Layout, Position, RATE
from showsync.clock import CLOCK, START, STOP, ClockEngine
from showsync.egress import MidiEgress, CLOCK_BIT, TRANSPORT_BIT
from showsync.setlist import Setlist, Song
from showsync.tempomap import TempoEvent


def layout(songs, durations):
    lengths = tuple(round(d * RATE) for d in durations)
    maps = tuple(s.tempo_map(d) for s, d in zip(songs, durations))
    starts, total = AudioEngine._positions(songs, lengths, maps)
    return Layout(Setlist('Test', tuple(songs)), tuple(range(len(songs))), starts,
                  lengths, tuple(durations), maps, total)


class Slave:
    """Pattern-anchored transport slave: Start arms, the next F8 is the one."""

    def __init__(self):
        self.running = False
        self.awaiting_first_tick = False
        self.anchor = None  # time of the F8 the pattern is anchored on
        self.transport = []  # (time, 'START'|'STOP')
        self.ticks = []

    def recv(self, time, data):
        status = data[0]
        if status == START:
            self.running = self.awaiting_first_tick = True
            self.transport.append((time, 'START'))
        elif status == STOP:
            self.running = self.awaiting_first_tick = False
            self.transport.append((time, 'STOP'))
        elif status == CLOCK:
            self.ticks.append(time)
            if self.awaiting_first_tick:
                self.anchor = time
                self.awaiting_first_tick = False


class LiveRig:
    """Deterministic set walker with the live.sh egress and relay wiring."""

    def __init__(self, timeline, quantize='bar', clock_offset_ms=0):
        self.layout = timeline
        self.time = 0.0
        self.playing = True
        self.slave = Slave()
        self.mirror = []  # full-egress hardware mirror (David's line)
        self.cues = []    # shared ShowSync Cues virtual port
        egress = MidiEgress(
            [('Arturia KeyStep 37', self._port(self.slave_recv), CLOCK_BIT | TRANSPORT_BIT),
             ('TBOX Out 2', self._port(lambda d: self.mirror.append((self.time, d))))],
            shared=[('ShowSync Cues (virtual)',
                     self._port(lambda d: self.cues.append((self.time, d))))])
        self.clock = ClockEngine(timeline.maps, self.position, egress.send,
                                 clock_offset_ms=clock_offset_ms,
                                 keystep_send=egress.send_keystep_transport,
                                 send_except_keystep=egress.send_transport_except_keystep,
                                 keystep_start_quantize=quantize)

    @staticmethod
    def _port(receive):
        return SimpleNamespace(send_message=lambda data: receive(tuple(data)))

    def slave_recv(self, data):
        self.slave.recv(self.time, data)

    def position(self):
        frame = self.time * RATE
        if abs(frame - round(frame)) < 1e-7:
            frame = round(frame)
        index = min(len(self.layout.starts) - 1, bisect_right(self.layout.starts, frame) - 1)
        local = (frame - self.layout.starts[index]) / RATE
        ended = frame >= self.layout.total_frames
        return Position(index, local, self.playing and not ended, 0, ended,
                        local >= self.layout.durations[index], frame, self.layout)

    def run_until(self, end):
        for _ in range(4_000_000):
            delay = self.clock.step()
            if self.time >= end:
                return
            self.time = min(end, self.time + min(.002, max(delay, 1e-12)))
        pytest.fail('clock failed to make progress')

    def pause(self):
        self.playing = False
        self.clock.step()

    def resume(self):
        self.playing = True


def bed_and_banger():
    """A ramping interlude bed into a straight song with a lead-in offset."""
    bed = Song('Bed', Path('x.wav'), 112.0,
               tempo=(TempoEvent(20.0, 120.0, 10.0),), gap=1.5)
    banger = Song('Banger', Path('y.wav'), 120.003456, offset=.25)
    return layout([bed, banger], [45.3, 30.0])


@pytest.mark.parametrize('clock_offset_ms', [0, -20])
def test_boundary_sends_stop_start_to_keystep_with_start_on_new_grid(clock_offset_ms):
    timeline = bed_and_banger()
    boundary = timeline.starts[1] / RATE
    rig = LiveRig(timeline, 'bar', clock_offset_ms=clock_offset_ms)
    rig.run_until(boundary + 6.0)
    # The per-port filter must pass boundary transport: exactly set-start
    # Start, then Stop+Start at the boundary, in that order, at that time.
    assert [kind for _, kind in rig.slave.transport] == ['START', 'STOP', 'START']
    assert [t for t, _ in rig.slave.transport][1:] == pytest.approx([boundary, boundary], abs=2e-3)
    # The slave's one is the first F8 after the boundary Start — it must land
    # on tick 0 of the NEW song's grid: its lead-in offset shifted by the rig
    # compensation, not the old song's ramped map or a stale tick index.
    tick_zero = boundary + timeline.maps[1].offset - clock_offset_ms / 1000.0
    assert rig.slave.anchor == pytest.approx(tick_zero, abs=2e-3)
    # The outgoing bed (ramp + gap padding) ticked whole bars on the KeyStep
    # port, so a counting slave arrives at the boundary on a bar as well.
    before = [t for t in rig.slave.ticks if t < boundary - 1e-9]
    assert len(before) % 96 == 0 and before
    # The shared cue port still hears full transport (Keyframes timebase).
    assert [d[0] for _, d in rig.cues if d[0] != CLOCK] == [START, STOP, START]


def test_resume_holds_keystep_start_until_the_next_bar_tick():
    timeline = layout([Song('One', Path('x.wav'), 120.0)], [8.0])
    rig = LiveRig(timeline, 'bar')
    rig.run_until(1.3)
    rig.pause()
    assert rig.slave.transport[-1][1] == 'STOP'
    paused_at = len(rig.slave.transport)
    rig.resume()
    rig.run_until(3.1)
    # The KeyStep port must NOT hear the mid-bar resume Start; its re-anchor
    # comes on the next bar tick (bar 2 of a 120 BPM song starts at 2.0s).
    resumed = rig.slave.transport[paused_at:]
    assert resumed == [(pytest.approx(2.0, abs=2e-3), 'START')]
    assert rig.slave.anchor == pytest.approx(2.0, abs=2e-3)
    # Every other destination keeps the immediate resume Start.
    mirror_transport = [(t, d[0]) for t, d in rig.mirror if d[0] in (START, STOP)]
    assert (pytest.approx(1.3, abs=2e-3), START) == mirror_transport[-1]
    cue_transport = [(t, d[0]) for t, d in rig.cues if d[0] in (START, STOP)]
    assert (pytest.approx(1.3, abs=2e-3), START) == cue_transport[-1]


def test_play_arm_made_while_paused_is_latched_not_swallowed():
    timeline = layout([Song('One', Path('x.wav'), 120.0)], [8.0])
    rig = LiveRig(timeline, 'bar')
    rig.run_until(1.3)
    rig.pause()
    assert rig.clock.relay_keystep_transport(START) is True
    # Extra scheduler passes while paused must not clear the arm (I79a: the
    # press used to vanish silently in the not-playing branch).
    for _ in range(5):
        rig.clock.step()
    rig.resume()
    rig.run_until(3.1)
    starts = [t for t, kind in rig.slave.transport if kind == 'START' and t >= 1.3]
    assert starts == [pytest.approx(2.0, abs=2e-3)]


def test_quantize_off_keeps_immediate_resume_start_on_keystep():
    timeline = layout([Song('One', Path('x.wav'), 120.0)], [8.0])
    rig = LiveRig(timeline, 'off')
    rig.run_until(1.3)
    rig.pause()
    paused_at = len(rig.slave.transport)
    rig.resume()
    rig.run_until(2.5)
    resumed = rig.slave.transport[paused_at:]
    assert resumed[0] == (pytest.approx(1.3, abs=2e-3), 'START')
