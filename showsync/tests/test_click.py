"""Click track: onsets from the layout's tempo maps, mixed in the callback."""
from bisect import bisect_right
from pathlib import Path

import numpy as np
import pytest

from showsync.audio import AudioEngine, Layout, RATE
from showsync.click import ClickTrack
from showsync.setlist import Setlist, Song
from showsync.tempomap import TempoEvent

FIXTURES = Path(__file__).parent / 'fixtures'
TONE = FIXTURES / 'tone.wav'


def layout(songs, durations):
    lengths = tuple(round(d * RATE) for d in durations)
    maps = tuple(s.tempo_map(d) for s, d in zip(songs, durations))
    starts, total = AudioEngine._positions(songs, lengths, maps)
    return Layout(Setlist('Test', tuple(songs)), tuple(range(len(songs))), starts,
                  lengths, tuple(durations), maps, total)


def render(timeline, frames, blocksize=256):
    """Zero blocks through one ClickTrack, split at song boundaries like the callback."""
    click = ClickTrack(RATE)
    click.enabled = True
    out = np.zeros((frames, 2), dtype=np.float32)
    begin = 0
    while begin < frames:
        index = max(0, bisect_right(timeline.starts, begin) - 1)
        boundary = (timeline.starts[index + 1] if index + 1 < len(timeline.starts)
                    else timeline.total_frames)
        count = min(blocksize, frames - begin, boundary - begin)
        click.mix(out[begin:begin + count], begin, index, timeline)
        begin += count
    return out


def onsets(out):
    """Frames where the mix becomes nonzero after silence."""
    audible = np.abs(out[:, 0]) > 0
    rises = np.flatnonzero(audible[1:] & ~audible[:-1]) + 1
    return ([0] if audible[0] else []) + rises.tolist()


def expected_onsets(timeline, index, end_frame):
    tempo, start = timeline.maps[index], timeline.starts[index]
    result, beat = [], 0
    while (onset := start + round(tempo.T(beat) * RATE)) < end_frame:
        result.append(onset)
        beat += 1
    return result


def test_clicks_land_on_every_beat_of_a_constant_tempo_song():
    timeline = layout([Song('A', TONE, 120)], [4.0])
    frames = 2 * RATE
    out = render(timeline, frames)
    expected = expected_onsets(timeline, 0, frames)
    assert expected == [round(i * RATE / 2) for i in range(4)]
    assert onsets(out) == expected


def test_bar_downbeats_are_accented():
    timeline = layout([Song('A', TONE, 240)], [8.0])
    out = render(timeline, 3 * RATE)
    peaks = [np.max(np.abs(out[onset:onset + RATE // 100]))
             for onset in expected_onsets(timeline, 0, 3 * RATE - RATE // 100)]
    assert len(peaks) >= 9
    for beat, peak in enumerate(peaks):
        if beat % 4 == 0:
            assert peak > 0.38
        else:
            assert 0.15 < peak < 0.35


def test_first_beat_offset_delays_the_first_click():
    timeline = layout([Song('A', TONE, 120, offset=0.5)], [4.0])
    out = render(timeline, RATE)
    first = onsets(out)[0]
    assert first == round(0.5 * RATE)
    assert not np.any(out[:first])


def test_ramped_tempo_clicks_at_the_local_tempo():
    song = Song('A', TONE, 120, tempo=(TempoEvent(0.0, 180, 4.0),))
    timeline = layout([song], [6.0])
    frames = 5 * RATE
    expected = expected_onsets(timeline, 0, frames)
    assert onsets(render(timeline, frames)) == expected
    spacing = np.diff(expected)
    assert spacing[0] > spacing[-1]  # accelerating ramp: intervals shrink
    assert spacing[-1] == pytest.approx(RATE / 3, abs=2)


def test_both_channels_carry_the_click():
    timeline = layout([Song('A', TONE, 120)], [2.0])
    out = render(timeline, RATE // 2)
    assert np.array_equal(out[:, 0], out[:, 1])
    assert np.max(np.abs(out)) > 0.3


def test_click_tail_continues_across_a_block_boundary():
    timeline = layout([Song('A', TONE, 120)], [2.0])
    click = ClickTrack(RATE)
    click.enabled = True
    first = np.zeros((100, 2), dtype=np.float32)
    second = np.zeros((2048, 2), dtype=np.float32)
    click.mix(first, 0, 0, timeline)
    click.mix(second, 100, 0, timeline)
    assert np.any(first) and np.any(second[:50])
    tone = np.concatenate([first[:, 0], second[:, 0]])
    assert not np.any(tone[round(0.04 * RATE):])


def test_frame_discontinuity_drops_the_ringing_tail():
    timeline = layout([Song('A', TONE, 120)], [4.0])
    click = ClickTrack(RATE)
    click.enabled = True
    block = np.zeros((64, 2), dtype=np.float32)
    click.mix(block, 0, 0, timeline)  # beat 0 starts ringing
    assert np.any(block)
    jump = np.zeros((64, 2), dtype=np.float32)
    # A skip lands mid-beat far from any onset: the old tail must not replay.
    click.mix(jump, RATE // 4, 0, timeline)
    assert not np.any(jump)


def test_second_song_clicks_follow_its_own_map():
    timeline = layout([Song('A', TONE, 120), Song('B', TONE, 60)], [2.0, 4.0])
    start = timeline.starts[1]
    frames = start + 3 * RATE
    out = render(timeline, frames)
    second = [o for o in onsets(out) if o >= start]
    assert second == expected_onsets(timeline, 1, frames)
    assert np.diff(second)[-1] == pytest.approx(RATE, abs=2)


def callback_mix(enabled, frames=RATE):
    engine = AudioEngine(Setlist('Set', (Song('A', TONE, 120),)))
    try:
        engine.prepare()
        engine.click.enabled = enabled
        engine._requested = (True, 0, 0)
        timing = type('T', (), {'outputBufferDacTime': 0.0, 'currentTime': 0.0})()
        out = np.zeros((frames, 2), dtype=np.float32)
        for begin in range(0, frames, 256):
            engine._callback(out[begin:begin + 256], 256, timing, None)
        return out, engine._layout
    finally:
        engine.close()


def test_callback_mixes_click_only_when_enabled():
    silent, _ = callback_mix(False)
    clicked, timeline = callback_mix(True)
    diff = clicked - silent
    expected = expected_onsets(timeline, 0, min(len(diff), timeline.total_frames))
    assert expected  # the fixture spans at least one beat
    # Float32 mixing quantizes the diff, so assert click windows rather than
    # exact rise samples: audible at each beat onset, silent everywhere else.
    span = round(0.03 * RATE)
    mask = np.zeros(len(diff), dtype=bool)
    for onset in expected:
        mask[onset:onset + span] = True
        assert np.abs(diff[onset]).max() > 0.004  # the onset frame itself sounds
        assert np.max(np.abs(diff[onset:onset + RATE // 100])) > 0.2
    assert not np.any(np.abs(diff[~mask]) > 1e-5)


def test_click_defaults_off():
    engine = AudioEngine(Setlist('Set', (Song('A', TONE, 120),)))
    try:
        assert engine.click.enabled is False
    finally:
        engine.close()
