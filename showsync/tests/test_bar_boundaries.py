"""Audio-master simulations count bytes just as a 16-step hardware slave does."""
from bisect import bisect_right
import math
from pathlib import Path
import random
from types import SimpleNamespace

import numpy as np
import pytest

from showsync.audio import Anchor, AudioEngine, Decoder, Layout, Position, RATE, RingBuffer
from showsync.clock import CLOCK, START, STOP, ClockEngine
from showsync.setlist import Setlist, Song
from showsync.tempomap import TempoEvent


def song(bpm, **kwargs):
    return Song('Test', Path('unused.wav'), bpm, **kwargs)


def layout(songs, durations):
    lengths = tuple(round(d * RATE) for d in durations)
    maps = tuple(s.tempo_map(d) for s, d in zip(songs, durations))
    starts, total = AudioEngine._positions(songs, lengths, maps)
    return Layout(Setlist('Test', tuple(songs)), tuple(range(len(songs))), starts,
                  lengths, tuple(durations), maps, total)


class SetClock:
    def __init__(self, timeline, offset=0, transport=True):
        self.layout = timeline
        self.transport = transport
        self.time = 0.0
        self.epoch = 0
        self.playing = True
        self.events, self.ticks = [], []
        self.slave_count = 0
        self.clock = ClockEngine(timeline.maps, self.position, self.send,
                                 clock_offset_ms=offset, send_transport=transport)

    def position(self):
        frame = self.time * RATE
        if abs(frame - round(frame)) < 1e-7:
            frame = round(frame)
        index = min(len(self.layout.starts) - 1, bisect_right(self.layout.starts, frame) - 1)
        local = (frame - self.layout.starts[index]) / RATE
        ended = frame >= self.layout.total_frames
        return Position(index, local, self.playing and not ended, self.epoch, ended,
                        local >= self.layout.durations[index], frame, self.layout)

    def send(self, byte):
        self.events.append((self.time, byte))
        if byte == START:
            self.slave_count = 0
        elif byte == CLOCK:
            self.ticks.append((self.time, self.position().song_index, self.clock._tick,
                               (self.slave_count // 6) % 16 + 1))
            self.slave_count += 1

    def run_until(self, end):
        for _ in range(2_000_000):
            delay = self.clock.step()
            if self.time >= end:
                return
            self.time = min(end, self.time + min(.01, max(delay, 1e-12)))
        pytest.fail('clock failed to make progress')


def assert_set(fake, expected_starts, expected_ticks):
    """Oracle inputs are independent of the production bar-layout calculation."""
    timeline = fake.layout
    assert timeline.starts == tuple(expected_starts)
    transport = [(t, b) for t, b in fake.events if b != CLOCK]
    expected_transport = [(0, START)]
    for start in expected_starts[1:]:
        expected_transport.extend([(start / RATE, STOP), (start / RATE, START)])
    expected_transport.append((timeline.total_frames / RATE, STOP))
    if fake.transport:
        assert [b for _, b in transport] == [b for _, b in expected_transport]
        assert [t for t, _ in transport] == pytest.approx([t for t, _ in expected_transport], abs=1e-8)
    else:
        assert transport == []
    for i, expected in enumerate(expected_ticks):
        emitted = [tick for tick in fake.ticks if tick[1] == i]
        assert [tick[2] for tick in emitted] == list(range(len(expected)))
        assert [tick[0] for tick in emitted] == pytest.approx(expected, abs=1e-8)
        if fake.transport:
            assert [tick[3] for tick in emitted] == [(k // 6) % 16 + 1 for k in range(len(expected))]
            assert emitted[0][3] == 1
        if i < len(expected_ticks) - 1:
            assert len(emitted) % 96 == 0
    assert fake.clock.dropped_ticks == 0


def constant_oracle(songs, lengths):
    starts, expected, cursor = [], [], 0
    for i, (s, length) in enumerate(zip(songs, lengths)):
        starts.append(cursor)
        # Enumerate bars rather than reproducing the layout's inverse/ceil logic.
        bars = 1
        minimum = length + round(s.gap * RATE)
        while round((s.offset + bars * 240 / s.bpm) * RATE) < minimum:
            bars += 1
        end = round((s.offset + bars * 240 / s.bpm) * RATE)
        if i < len(songs) - 1:
            count = bars * 96
        else:
            count = max(0, math.ceil((length / RATE - s.offset) * s.bpm * 24 / 60 - 1e-8))
        expected.append([cursor / RATE + s.offset + k * 60 / (24 * s.bpm) for k in range(count)])
        cursor += end
    return starts, expected


@pytest.mark.parametrize('bpm', [60, 90, 120, 137.123, 180, 300])
@pytest.mark.parametrize('edge', ['on_bar', 'one_tick', 'before', 'after', 'sub_bar'])
@pytest.mark.parametrize('transport', [False, True])
def test_boundary_edges_and_extreme_jumps(bpm, edge, transport):
    bar = round(240 / bpm * RATE)
    first = {'on_bar': bar, 'one_tick': bar + round(60 / bpm / 24 * RATE),
             'before': bar - 1, 'after': bar + 1, 'sub_bar': 1}[edge]
    songs = [song(bpm), song(180), song(60), song(180)]
    lengths = [first, 2 * RATE, 4 * RATE, RATE]
    fake = SetClock(layout(songs, [n / RATE for n in lengths]), transport=transport)
    starts, expected = constant_oracle(songs, lengths)
    fake.run_until(fake.layout.total_frames / RATE)
    assert_set(fake, starts, expected)
    if edge in ('on_bar', 'before'):
        assert starts[1] - first == (0 if edge == 'on_bar' else 1)
    elif edge == 'one_tick':
        assert (starts[1] - first) / RATE == pytest.approx(95 * 60 / bpm / 24, abs=1 / RATE)
    elif edge == 'after':
        assert starts[1] - first == round(480 / bpm * RATE) - bar - 1
    # Natural tick spacing remains unchanged through the entire injected wait.
    first_ticks = [t for t, i, _, _ in fake.ticks if i == 0]
    assert np.diff(first_ticks) == pytest.approx([60 / bpm / 24] * (len(first_ticks) - 1), abs=1e-8)


@pytest.mark.parametrize('seed', range(100))
def test_random_setlists_never_start_off_step_one_or_compress_ticks(seed):
    rng = random.Random(seed)
    songs, lengths = [], []
    for _ in range(rng.randint(4, 24)):
        bpm = rng.uniform(40, 240)
        offset = rng.choice([0, .013, .2])
        bar = round((offset + 240 / bpm) * RATE)
        length = rng.choice([bar, bar - 1, bar + 1,
                             round((offset + 60 / bpm / 24) * RATE),
                             round((offset + rng.uniform(.001, 12)) * RATE)])
        songs.append(song(bpm, offset=offset, gap=rng.choice([0, .001, .27, 2.3])))
        lengths.append(length)
    fake = SetClock(layout(songs, [n / RATE for n in lengths]))
    starts, expected = constant_oracle(songs, lengths)
    fake.run_until(fake.layout.total_frames / RATE)
    assert_set(fake, starts, expected)
    for i, s in enumerate(songs):
        ticks = [t for t, index, _, _ in fake.ticks if index == i]
        assert np.diff(ticks) == pytest.approx([60 / s.bpm / 24] * (len(ticks) - 1), abs=1e-8)
        if i + 1 < len(songs):
            minimum = lengths[i] + round(s.gap * RATE)
            wait = starts[i + 1] - starts[i] - minimum
            assert 0 <= wait < 240 / s.bpm * RATE + 1


def test_long_set_waits_and_phase_do_not_drift():
    songs = [song(137.123), song(60), song(180), song(91.9)] * 25
    lengths = [round(1.13 * RATE)] * len(songs)
    fake = SetClock(layout(songs, [n / RATE for n in lengths]))
    starts, expected = constant_oracle(songs, lengths)
    fake.run_until(fake.layout.total_frames / RATE)
    assert_set(fake, starts, expected)


@pytest.mark.parametrize('transport', [False, True])
def test_ramp_jump_gap_and_leadin_finish_at_final_outgoing_tempo(transport):
    # 60 -> 180 over two seconds integrates to four beats; after EOF at
    # 2.1s (plus .3s gap), the remaining bar finishes at 180 BPM, at 10/3s.
    songs = [song(60, tempo=(TempoEvent(0, 180, 2),), gap=.3),
             song(120, offset=.1, tempo=(TempoEvent(.6, 60),)), song(180), song(60)]
    fake = SetClock(layout(songs, [2.1, .9, .2, 2]), transport=transport)
    starts = [0, 160000, 332800, 396800]
    expected = []
    # Independent inverse of b=t+t^2/2, then the final 3 beats/second.
    expected.append([math.sqrt(1 + 2 * k / 24) - 1 if k < 96
                     else 2 + (k / 24 - 4) / 3 for k in range(192)])
    expected.append([starts[1] / RATE + (.1 + k / 48 if k < 24
                                      else .6 + (k / 24 - 1)) for k in range(96)])
    expected.append([starts[2] / RATE + k / 72 for k in range(96)])
    expected.append([starts[3] / RATE + k / 24 for k in range(48)])
    fake.run_until(fake.layout.total_frames / RATE)
    assert_set(fake, starts, expected)
    wait = [t for t, i, _, _ in fake.ticks if i == 0 and t > 2.1]
    assert np.diff(wait) == pytest.approx([1 / 72] * (len(wait) - 1))


@pytest.mark.parametrize('offset', [-250, -32, 32, 250])
def test_rig_compensation_does_not_change_layout_or_transport(offset):
    # Long lead-ins avoid startup clamping: compensation retains its existing
    # fixed phase shift. Negative offset can leave tail ticks beyond the cut.
    songs = [song(60, offset=.5), song(180, offset=.5), song(90, offset=.5), song(120, offset=.5)]
    lengths = [RATE] * 4
    timeline = layout(songs, [1] * 4)
    starts, unshifted = constant_oracle(songs, lengths)
    fake = SetClock(timeline, offset=offset)
    fake.run_until(timeline.total_frames / RATE)
    assert timeline.starts == tuple(starts)
    boundaries = [s / RATE for s in starts[1:]] + [timeline.total_frames / RATE]
    expected = [[t - offset / 1000 for t in ticks if t - offset / 1000 < boundaries[i] - 1e-9]
                for i, ticks in enumerate(unshifted)]
    # The final song is not bar-capped; positive compensation advances more
    # final-song ticks into the audible interval.
    count = math.ceil((1 - .5 + offset / 1000) * 48 - 1e-8)
    expected[-1] = [starts[-1] / RATE + .5 + k / 48 - offset / 1000 for k in range(count)]
    for i, stamps in enumerate(expected):
        emitted = [tick for tick in fake.ticks if tick[1] == i]
        assert [tick[2] for tick in emitted] == list(range(len(stamps)))
        assert [tick[0] for tick in emitted] == pytest.approx(stamps, abs=1e-8)
        assert emitted[0][3] == 1
    messages = [(t, b) for t, b in fake.events if b != CLOCK]
    assert [b for _, b in messages] == [START, STOP, START, STOP, START, STOP, START, STOP]
    assert [t for t, b in messages if b == START] == pytest.approx([s / RATE for s in starts])


def test_multi_second_stall_preserves_gapless_indices_and_recovers():
    fake = SetClock(layout([song(120)], [12]))
    fake.run_until(1)
    fake.time += 3
    fake.run_until(9)
    assert [k for _, _, k, _ in fake.ticks] == list(range(433))
    recovery = [t for t, _, _, _ in fake.ticks if 4 <= t <= 6]
    assert len(recovery) >= 190
    assert np.diff(recovery) == pytest.approx([1 / 96] * (len(recovery) - 1))
    assert [t for t, _, _, _ in fake.ticks][-48:] == pytest.approx([k / 48 for k in range(385, 433)])


def test_stall_across_multiple_boundaries_reanchors_current_song():
    fake = SetClock(layout([song(60), song(180), song(90), song(120)], [1] * 4))
    fake.run_until(.2)
    fake.time = fake.layout.starts[3] / RATE
    fake.clock.step()
    assert [b for _, b in fake.events][-3:] == [STOP, START, CLOCK]
    assert fake.ticks[-1][1:] == (3, 0, 1)


def test_reorder_snapshot_keeps_current_map_and_recalculates_waits():
    tone = Path(__file__).parent / 'fixtures' / 'tone.wav'
    engine = AudioEngine(Setlist('Reorder', tuple(Song(str(i), tone, bpm) for i, bpm in enumerate([60, 120, 90]))),
                         now=lambda: 0)
    engine._requested = (True, 0, 0)
    engine._anchors.append(Anchor(0, 0, 0, True, 0))
    position = engine.position()
    messages = []
    clock = ClockEngine(engine.maps, lambda: position, messages.append)
    clock.step()
    assert engine.move(2, -1) == 1
    assert position.layout.maps[1].bpm_at(0) == 120
    assert engine.position().layout.maps[1].bpm_at(0) == 90
    assert engine._layout.starts == (0, 4 * RATE, 320000)
    clock.step()
    position = engine.position()
    clock.step()
    assert messages == [START, CLOCK]
    assert engine._layout.reorder_margin == .5
    engine.frames_played = round(3.6 * RATE)
    assert engine.move(2, -1) is None
    engine._requested = (False, 0, 0)
    assert engine.move(2, -1) is None


class CallbackRig:
    """Real AudioEngine callback + decoded samples, deterministic DAC time."""
    def __init__(self, gap=0, transport=True):
        tone = Path(__file__).parent / 'fixtures' / 'tone.wav'
        self.now = 0.0
        songs = tuple(Song(str(i), tone, bpm, gap=gap) for i, bpm in enumerate([120, 180, 60, 90]))
        self.audio = AudioEngine(Setlist('Audio', songs), now=lambda: self.now)
        self.audio._requested = (True, 0, 0)
        with Decoder.open(tone) as source:
            self.samples = source.read(RATE)
        self.refill()
        self.events, self.ticks = [], []
        self.clock = ClockEngine(self.audio.maps, self.audio.position, self.send, send_transport=transport)

    def refill(self):
        for i in range(4):
            ring = RingBuffer()
            ring.write(self.samples)
            self.audio._slots[i] = SimpleNamespace(ring=ring)
        self.audio._skip_ready = self.audio._requested[1]

    def send(self, byte):
        self.events.append((self.now, byte))
        if byte == CLOCK:
            self.ticks.append((self.now, self.audio.position().song_index, self.clock._tick))

    def block(self, frames):
        output = np.empty((frames, 2), dtype=np.float32)
        self.audio._callback(output, frames, SimpleNamespace(currentTime=0, outputBufferDacTime=0), False)
        end = self.now + frames / RATE
        while self.now < end - 1e-12:
            delay = self.clock.step()
            self.now = min(end, self.now + min(.005, max(delay, 1e-12)))
        self.now = end
        self.clock.step()
        return output


@pytest.mark.parametrize('gap', [0, .25, 1, 1.01, 4.25])
@pytest.mark.parametrize('transport', [False, True])
def test_real_callback_outputs_original_audio_then_silence_and_synchronized_starts(gap, transport):
    rig = CallbackRig(gap, transport)
    timeline = rig.audio._layout
    expected_starts, _ = constant_oracle(timeline.setlist.songs, [RATE] * 4)
    assert timeline.starts == tuple(expected_starts)
    out = rig.block(timeline.total_frames)
    for i, start in enumerate(timeline.starts):
        np.testing.assert_array_equal(out[start:start + RATE], rig.samples)
        end = timeline.starts[i + 1] if i < 3 else timeline.total_frames
        np.testing.assert_array_equal(out[start + RATE:end], 0)
        ticks = [tick for tick in rig.ticks if tick[1] == i]
        assert ticks[0] == pytest.approx((start / RATE, i, 0), abs=1e-8)
        assert [k for _, _, k in ticks] == list(range(len(ticks)))
    assert rig.audio.underruns == 0
    assert rig.audio.position().epoch == 0
    assert rig.audio.position().ended
    transport_events = [(t, b) for t, b in rig.events if b != CLOCK]
    assert [b for _, b in transport_events] == ([START, STOP] * 4 if transport else [])
    if transport:
        assert [t for t, b in transport_events if b == START] == pytest.approx([s / RATE for s in timeline.starts])


@pytest.mark.parametrize('at', [.4, 1.2, 1.999])
@pytest.mark.parametrize('action', ['skip', 'restart', 'pause'])
@pytest.mark.parametrize('transport', [False, True])
def test_real_transport_mid_song_and_during_wait(at, action, transport):
    rig = CallbackRig(transport=transport)
    rig.block(round(at * RATE))
    rig.events.clear()
    before = rig.audio.position()
    previous_tick = rig.clock._tick
    if action == 'pause':
        rig.audio.toggle_pause()
        out = rig.block(RATE // 2)
        np.testing.assert_array_equal(out, 0)
        assert rig.audio.position().frame == before.frame
        assert rig.clock._tick == previous_tick
        rig.audio.toggle_pause()
        rig.block(RATE // 10)
        expected = [STOP, START]
        resumed = [k for t, _, k in rig.ticks if t >= at + .5 - 1e-8]
        # A natural boundary may follow the resume; it has its own reset.
        assert resumed[0] == (0 if previous_tick == 96 else previous_tick)
        if at + .1 >= 2:
            expected += [STOP, START]
    else:
        getattr(rig.audio, action)()
        rig.refill()
        out = rig.block(480)
        np.testing.assert_array_equal(out, rig.samples[:480])
        assert rig.audio.position().epoch == before.epoch + 1
        target = 1 if action == 'skip' else 0
        ticks = [tick for tick in rig.ticks if tick[0] >= at - 1e-8]
        # Ignore any tick emitted at the old endpoint before the request.
        assert any(i == target and k == 0 for _, i, k in ticks)
        expected = [STOP, START]
    assert [b for _, b in rig.events if b != CLOCK] == (expected if transport else [])


@pytest.mark.parametrize('action', ['skip', 'restart'])
@pytest.mark.parametrize('transport', [False, True])
def test_pending_seek_during_wait_stops_once_until_audio_is_ready(action, transport):
    rig = CallbackRig(transport=transport)
    rig.block(round(1.2 * RATE))
    rig.events.clear()
    before = rig.audio.position()
    getattr(rig.audio, action)()
    out = rig.block(480)
    np.testing.assert_array_equal(out, 0)
    assert rig.audio.position().frame == before.frame
    assert rig.audio.position().epoch == before.epoch
    assert [b for _, b in rig.events] == ([STOP] if transport else [])
    out = rig.block(480)
    np.testing.assert_array_equal(out, 0)
    assert [b for _, b in rig.events] == ([STOP] if transport else [])
    rig.refill()
    out = rig.block(480)
    np.testing.assert_array_equal(out, rig.samples[:480])
    assert rig.audio.position().epoch == before.epoch + 1
    assert [b for _, b in rig.events if b != CLOCK] == ([STOP, START] if transport else [])
    assert rig.ticks[-1][1:] == (1 if action == 'skip' else 0, 0)


@pytest.mark.parametrize('offset', [-250, -32, 32, 250])
@pytest.mark.parametrize('transport', [False, True])
def test_rig_offset_without_leadin_keeps_initial_tick_indices_at_every_song(offset, transport):
    songs = [song(60), song(180), song(90), song(120)]
    fake = SetClock(layout(songs, [1] * 4), offset=offset, transport=transport)
    fake.run_until(fake.layout.total_frames / RATE)
    for i, s in enumerate(songs):
        emitted = [tick for tick in fake.ticks if tick[1] == i]
        assert [tick[2] for tick in emitted] == list(range(len(emitted)))
        start = fake.layout.starts[i] / RATE
        assert [tick[0] for tick in emitted] == pytest.approx(
            [start + max(0, k * 60 / s.bpm / 24 - offset / 1000) for k in range(len(emitted))], abs=1e-8)
        if transport:
            assert emitted[0][3] == 1
    assert [b for _, b in fake.events if b != CLOCK] == ([START, STOP] * 4 if transport else [])


def test_skip_pressed_as_previous_skip_applies_still_advances(monkeypatch):
    """A press racing the callback's settle of the prior skip must not re-request
    the target the callback just applied (a silent no-op press)."""
    import showsync.audio as audio_module
    rig = CallbackRig()
    rig.block(round(.4 * RATE))
    rig.audio.skip()
    assert rig.audio._requested == (True, 1, 1)
    rig.refill()  # producer has prepared the pending target
    real = bisect_right
    armed = ['skip']

    def racing(a, x, *args):
        # The audio callback applies the pending skip between skip()'s read of
        # frames_played (already evaluated as x) and its settle-state check —
        # the thread interleaving that made a live press vanish, made exact.
        result = real(a, x, *args)
        if armed:
            armed.clear()
            rig.block(64)
        return result

    monkeypatch.setattr(audio_module, 'bisect_right', racing)
    rig.audio.skip()
    monkeypatch.setattr(audio_module, 'bisect_right', real)
    assert rig.audio._skip_applied == 1
    assert rig.audio._requested == (True, 2, 2)
    rig.refill()
    rig.block(480)
    assert rig.audio.position().song_index == 2
