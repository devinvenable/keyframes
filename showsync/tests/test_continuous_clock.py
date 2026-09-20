"""Audio-master simulations: count actual emitted bytes like a hardware slave."""
from bisect import bisect_right
import math
from pathlib import Path

import pytest

from showsync.audio import Anchor, AudioEngine, Layout, Position, RATE
from showsync.clock import CLOCK, START, STOP, ClockEngine
from showsync.setlist import Setlist, Song
from showsync.tempomap import TempoEvent


def layout(songs, durations):
    lengths = tuple(round(d * RATE) for d in durations)
    starts, total = AudioEngine._positions(songs, lengths)
    return Layout(Setlist('Test', tuple(songs)), tuple(range(len(songs))), starts,
                  lengths, tuple(durations), tuple(s.tempo_map(d) for s, d in zip(songs, durations)), total)


def song(bpm, **kwargs):
    return Song('Test', Path('unused.wav'), bpm, **kwargs)


class SetClock:
    def __init__(self, timeline, offset=0, transport=True):
        self.layout = timeline
        self.time = 0.0
        self.epoch = 0
        self.playing = True
        self.events, self.indices, self.steps = [], [], []
        self.slave_count = 0
        self.clock = ClockEngine(timeline.maps, self.position, self.send,
                                 clock_offset_ms=offset, send_transport=transport)

    def position(self):
        frame = self.time * RATE
        index = min(len(self.layout.starts) - 1, bisect_right(self.layout.starts, frame) - 1)
        local = self.time - self.layout.starts[index] / RATE
        ended = frame >= self.layout.total_frames
        return Position(index, local, self.playing and not ended, self.epoch, ended,
                        local >= self.layout.durations[index], frame, self.layout)

    def send(self, byte):
        self.events.append((self.time, byte))
        if byte == START:
            self.slave_count = 0
        elif byte == CLOCK:
            self.indices.append(self.clock._tick)
            if self.slave_count % 6 == 0:
                self.steps.append((self.time, (self.slave_count // 6) % 16))
            self.slave_count += 1

    def run_until(self, end):
        # Poll as the real engine does, but land exactly on requested deadlines.
        for _ in range(200000):
            delay = self.clock.step()
            if self.time >= end:
                return
            self.time = min(end, self.time + min(.005, max(delay, 1e-8)))
        pytest.fail('clock failed to make progress')


@pytest.mark.parametrize('offset', [-250, 0, 32, 250])
@pytest.mark.parametrize('transport', [False, True])
def test_four_songs_ramp_gap_leadin_keep_slave_phrase_and_quantized_tempo(offset, transport):
    songs = [song(120, gap=.27), song(120, tempo=(TempoEvent(0, 180, 2),)),
             song(90, offset=.11, gap=.35), song(150, offset=.07)]
    timeline = layout(songs, [2.13, 2.23, 2.07, 2])
    fake = SetClock(timeline, offset, transport)
    fake.run_until(timeline.total_frames / RATE)
    assert [b for _, b in fake.events if b != CLOCK] == ([START, STOP] if transport else [])
    assert fake.indices == list(range(len(fake.indices)))
    assert fake.clock.dropped_ticks == 0
    # Independent analytic handovers: 2.4 -> 2.5; 4.74 -> 4 5/6;
    # 7.12 -> 6 5/6. The last one happens BEFORE the incoming audio starts.
    beats = [0, 5, 11, 14]
    anchors = [0, 2.5, 29 / 6, 41 / 6]
    expected = []
    for k in fake.indices:
        section = bisect_right(beats, k / 24) - 1
        tempo = timeline.maps[section]
        due = anchors[section] + tempo.T(k / 24 - beats[section]) - tempo.offset - offset / 1000
        expected.append(max(0, due))
    ticks = [t for t, b in fake.events if b == CLOCK]
    assert ticks == pytest.approx(expected, abs=2e-7)
    assert [step for _, step in fake.steps] == [n % 16 for n in range(len(fake.steps))]
    assert [t for t, _ in fake.steps] == pytest.approx(expected[::6], abs=2e-7)
    # Audio layout is unchanged, including the gap. Gap clocks stay alive.
    assert timeline.starts == (0, 115200, 222240, 338400)
    assert any(2.13 < t < 2.4 for t in ticks)
    assert fake.position().epoch == 0


def test_many_handover_errors_are_bounded_without_accumulating():
    timeline = layout([song(120)] * 80, [1.13] * 80)
    fake = SetClock(timeline)
    fake.clock.step()
    sections = fake.clock._timeline.sections
    assert len(sections) == 80
    for i, section in enumerate(sections):
        actual = timeline.starts[i] / RATE
        assert abs(section.anchor - actual) <= .25 + 1e-9
        assert section.anchor == pytest.approx(math.floor(actual * 2 + .5 - 1e-9) / 2)
        assert section.beat == math.floor(actual * 2 + .5 - 1e-9)
    assert sections[-1].anchor == pytest.approx(89.5)


def test_ramping_handover_selects_nearest_time_not_nearest_beat_number():
    # The first handover shifts the ramp +.185s. At the third song's start,
    # the ramp's beat count is 1.479225, but beat 2 is closer in *time*.
    timeline = layout([song(120), song(60, tempo=(TempoEvent(0, 180, 1),)), song(120)], [.815, 1, 2])
    fake = SetClock(timeline)
    fake.clock.step()
    sections = fake.clock._timeline.sections
    assert [s.beat for s in sections] == [0, 2, 4]
    assert [s.anchor for s in sections] == pytest.approx([0, 1, 2])
    previous_beat = 1 + (math.sqrt(5) - 1) / 2
    assert abs(sections[2].anchor - 1.815) <= (2 - previous_beat) / 2


def test_short_songs_sharing_a_beat_do_not_duplicate_or_skip_ticks():
    fake = SetClock(layout([song(120), song(90), song(60)], [.1, .1, 2]))
    fake.run_until(2.2)
    assert [b for _, b in fake.events if b != CLOCK] == [START, STOP]
    assert fake.indices == list(range(53))
    ticks = [t for t, b in fake.events if b == CLOCK]
    assert ticks == pytest.approx([k / 24 for k in range(53)], abs=1e-8)


@pytest.mark.parametrize('transport', [False, True])
def test_explicit_restart_resets_only_that_boundary_and_respects_transport(transport):
    timeline = layout([song(120), song(90, offset=.12, restart=True), song(150)], [1.13, 1.7, 2])
    fake = SetClock(timeline, transport=transport)
    fake.run_until(timeline.total_frames / RATE)
    messages = [(t, b) for t, b in fake.events if b != CLOCK]
    assert [b for _, b in messages] == ([START, STOP, START, STOP] if transport else [])
    if transport:
        assert messages[1][0] == pytest.approx(1.13, abs=.005)
        assert messages[2][0] == messages[1][0]
    reset = fake.indices.index(0, 1)
    assert fake.indices[:reset] == list(range(reset))
    assert fake.indices[reset:] == list(range(len(fake.indices) - reset))
    ticks = [t for t, b in fake.events if b == CLOCK]
    assert ticks[reset] == pytest.approx(1.25, abs=1e-8)
    assert not any(1.13 <= t < 1.25 - 1e-8 for t in ticks)


def test_skip_restart_pause_keep_intentional_transport_with_real_layout():
    timeline = layout([song(120), song(90), song(150)], [2.13, 2.2, 2])
    fake = SetClock(timeline)
    fake.run_until(.4)
    fake.time = timeline.starts[1] / RATE
    fake.epoch += 1
    fake.clock.step()
    assert [b for _, b in fake.events][-3:] == [STOP, START, CLOCK]
    assert fake.indices[-1] == 0
    fake.time = 0
    fake.epoch += 1
    fake.clock.step()
    assert [b for _, b in fake.events][-3:] == [STOP, START, CLOCK]
    fake.playing = False
    fake.clock.step()
    assert fake.events[-1][1] == STOP
    tick = fake.clock._tick
    fake.playing = True
    fake.clock.step()
    fake.run_until(.1)
    assert [b for _, b in fake.events if b != CLOCK][-2:] == [STOP, START]
    assert fake.indices[-1] >= tick


def test_multi_second_stall_catches_up_at_twice_rate_then_locks_to_audio():
    fake = SetClock(layout([song(120)], [12]))
    fake.run_until(1)
    fake.time += 3
    fake.run_until(9)
    assert fake.indices == list(range(433))
    ticks = [t for t, b in fake.events if b == CLOCK]
    recovery = [t for t in ticks if 4 <= t <= 6]
    assert len(recovery) >= 190
    assert [b - a for a, b in zip(recovery, recovery[1:])] == pytest.approx([1 / 96] * (len(recovery) - 1))
    assert ticks[-48:] == pytest.approx([k / 48 for k in range(385, 433)], abs=1e-8)
    assert [b for _, b in fake.events if b != CLOCK] == [START]


def test_reorder_snapshot_and_lookahead_guard_keep_clock_coherent():
    tone = Path(__file__).parent / 'fixtures' / 'tone.wav'
    engine = AudioEngine(Setlist('Reorder', tuple(Song(str(i), tone, bpm, gap=2) for i, bpm in enumerate([30, 120, 90]))),
                         now=lambda: 0)
    engine._requested = (True, 0, 0)
    engine._anchors.append(Anchor(0, 0, 0, True, 0))
    position = engine.position()
    assert position.layout is engine._layout
    messages = []
    clock = ClockEngine(engine.maps, lambda: position, messages.append)
    clock.step()
    assert engine.move(2, -1) == 1
    # The old Position must still carry its old maps even after MapsView changes.
    clock.step()
    assert clock._timeline.sections[1].tempo.bpm_at(0) == 120
    position = engine.position()
    clock.step()
    assert clock._timeline.sections[1].tempo.bpm_at(0) == 90
    assert [b for b in messages if b != CLOCK] == [START]
    assert engine._layout.reorder_margin == 1.25
    engine.frames_played = round(1.8 * RATE)  # 1.2s before boundary: > old .5s guard
    assert engine.move(2, -1) is None
    engine._requested = (False, 0, 0)
    assert engine.move(2, -1) is None  # pausing cannot retract early clocks


def test_audio_callback_publishes_continuous_layout_and_epoch_across_boundary():
    from types import SimpleNamespace
    import numpy as np
    tone = Path(__file__).parent / 'fixtures' / 'tone.wav'
    now = [0.0]
    engine = AudioEngine(Setlist('Audio', (Song('A', tone, 120), Song('B', tone, 90))), now=lambda: now[0])
    engine._requested = (True, 0, 0)
    engine._callback(np.empty((2 * RATE, 2), dtype=np.float32), 2 * RATE,
                     SimpleNamespace(currentTime=0, outputBufferDacTime=0), False)
    assert engine.position().layout is engine._layout
    messages = []
    clock = ClockEngine(engine.maps, engine.position, messages.append)
    for n in range(2001):
        now[0] = n / 1000
        clock.step()
    assert [b for b in messages if b != CLOCK] == [START, STOP]
    assert engine.position().epoch == 0
    assert clock._tick == 84  # 48 clocks at 120 BPM, then 36 at 90 BPM
