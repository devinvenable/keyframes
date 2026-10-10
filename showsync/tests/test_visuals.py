"""Per-song Keyframes cues: setlist parsing, message building, clock emission."""
from dataclasses import replace

import pytest
import yaml

from showsync.audio import Position
from showsync.clock import CLOCK, START, ClockEngine
from showsync.setlist import SetlistError, Setlist, load_setlist
from showsync.tempomap import TempoMap
from showsync.visuals import (CC_ALLOW_ADD, CC_ENABLED, CC_PROBABILITY, CC_RESET,
                              KEYFRAMES_SCENES, KeyframesCue, song_controls)


def write(tmp_path, songs, top=None):
    (tmp_path / 'song.wav').touch()
    data = {'songs': songs}
    if top is not None:
        data['keyframes'] = top
    path = tmp_path / 'set.yaml'
    path.write_text(yaml.safe_dump(data))
    return path


def song(**keyframes):
    row = dict(name='Song', file='song.wav', bpm=120)
    if keyframes:
        row['keyframes'] = keyframes.get('keyframes', keyframes)
    return row


def test_full_cue_parses(tmp_path):
    path = write(tmp_path, [song(bank='robot-society-symbols',
                                 scenes=dict(enabled=True, probability=0.15,
                                             allow=['four-bar-sweep-tinted']))],
                 top=dict(banks=['insect-war-aged', 'robot-society-symbols']))
    result = load_setlist(path)
    assert result.keyframes_banks == ('insect-war-aged', 'robot-society-symbols')
    assert result.keyframes_channel == 16
    cue = result.songs[0].keyframes
    assert cue == KeyframesCue(bank='robot-society-symbols', enabled=True,
                               probability=0.15, allow=('four-bar-sweep-tinted',))


def test_absent_block_is_none_and_empty_block_is_bare_cue(tmp_path):
    rows = [dict(name='A', file='song.wav', bpm=120),
            dict(name='B', file='song.wav', bpm=120, keyframes={})]
    result = load_setlist(write(tmp_path, rows))
    assert result.songs[0].keyframes is None
    assert result.songs[1].keyframes == KeyframesCue()


@pytest.mark.parametrize('block, match', [
    (dict(bank='missing'), 'not in the top-level'),
    (dict(scenes=dict(enabled='yes')), 'enabled must be a boolean'),
    (dict(scenes=dict(probability=1.5)), 'between 0 and 1'),
    (dict(scenes=dict(probability=-0.1)), 'probability'),
    (dict(scenes=dict(allow=[])), 'enabled: false'),
    (dict(scenes=dict(allow=['nope'])), 'unknown scene'),
    (dict(scenes=dict(allow='four-bar-sweep')), 'nonempty list'),
    (dict(scenes=dict(surprise=1)), 'unknown fields'),
    (dict(surprise=1), 'unknown fields'),
])
def test_invalid_song_blocks(tmp_path, block, match):
    with pytest.raises(SetlistError, match=match):
        load_setlist(write(tmp_path, [song(keyframes=block)],
                           top=dict(banks=['other'])))


@pytest.mark.parametrize('top, match', [
    (dict(banks=['b', 'a']), 'sorted'),
    (dict(banks=['a', 'a']), 'repeat'),
    (dict(banks=['a', 'default']), "'default'"),
    (dict(banks='a'), 'must be a list'),
    (dict(channel=0), 'integer 1-16'),
    (dict(channel=17), 'integer 1-16'),
    (dict(channel=True), 'integer 1-16'),
    (dict(surprise=1), 'unknown fields'),
])
def test_invalid_top_level_blocks(tmp_path, top, match):
    with pytest.raises(SetlistError, match=match):
        load_setlist(write(tmp_path, [song()], top=top))


def make_setlist(cues, banks=('aaa', 'bbb'), channel=16):
    songs = tuple(SongStub(cue) for cue in cues)
    return Setlist('t', songs, tuple(banks), channel)


class SongStub:
    def __init__(self, keyframes):
        self.keyframes = keyframes


def test_song_controls_messages_and_order():
    setlist = make_setlist([
        None,
        KeyframesCue(bank='bbb', enabled=False, probability=0.15,
                     allow=('concentric-rings', 'four-bar-sweep')),
        KeyframesCue(bank='default'),
        KeyframesCue(enabled=True),
    ])
    controls = song_controls(setlist)
    assert controls[0] == ()  # no block: nothing emitted, state persists
    # Bank program FIRST (reset must land on the new bank's defaults), then
    # reset, then only the values the block sets.
    assert controls[1] == (
        (0xCF, 2),                     # program 2 = banks[1], channel 16
        (0xBF, CC_RESET, 0),
        (0xBF, CC_ENABLED, 0),
        (0xBF, CC_PROBABILITY, 19),    # round(0.15 * 127)
        (0xBF, CC_ALLOW_ADD, KEYFRAMES_SCENES['concentric-rings']),
        (0xBF, CC_ALLOW_ADD, KEYFRAMES_SCENES['four-bar-sweep']),
    )
    assert controls[2] == ((0xCF, 0), (0xBF, CC_RESET, 0))  # default = program 0
    assert controls[3] == ((0xBF, CC_RESET, 0), (0xBF, CC_ENABLED, 127))


def test_song_controls_channel_and_quantization():
    setlist = make_setlist([KeyframesCue(bank='aaa', probability=0.05)],
                           channel=1)
    (pc, reset, prob), = song_controls(setlist)
    assert pc == (0xC0, 1)
    assert reset == (0xB0, CC_RESET, 0)
    assert prob == (0xB0, CC_PROBABILITY, 6)  # 6/127 = 0.047 — ~0.8% steps


class FakeClock:
    def __init__(self, maps, controls):
        self.time = 0.0
        self.p = Position(0, 0, True)
        self.messages = []
        self.engine = ClockEngine(maps, lambda: self.p,
                                  lambda b: self.messages.append(b),
                                  now=lambda: self.time, sleep=self.advance,
                                  controls=controls)

    def advance(self, dt):
        self.time += dt
        self.p = replace(self.p, song_time=self.p.song_time + dt)


def test_clock_emits_controls_once_per_song_start_before_transport():
    cue = ((0xCF, 1), (0xBF, CC_RESET, 0))
    fake = FakeClock([TempoMap(120), TempoMap(120)], controls=(cue, ()))
    for _ in range(40):
        fake.advance(fake.engine.step())
    # Song 1's cue messages precede START and are never repeated per tick.
    assert fake.messages[:4] == [(0xCF, 1), (0xBF, CC_RESET, 0), START, CLOCK]
    assert fake.messages.count((0xCF, 1)) == 1
    fake.p = Position(1, 0, True, epoch=1)  # skip to song 2: empty cue, no spam
    fake.engine.step()
    assert not any(isinstance(b, tuple) for b in fake.messages[4:])


def test_clock_emits_second_songs_controls_at_the_boundary():
    cues = ((), ((0xCF, 2), (0xBF, CC_ENABLED, 0)))
    fake = FakeClock([TempoMap(120), TempoMap(120)], controls=cues)
    fake.engine.step()
    assert not any(isinstance(b, tuple) for b in fake.messages)
    fake.p = Position(1, 0, True, epoch=1)
    fake.engine.step()
    tuples = [b for b in fake.messages if isinstance(b, tuple)]
    assert tuples == [(0xCF, 2), (0xBF, CC_ENABLED, 0)]


def test_clock_without_controls_is_unchanged():
    fake = FakeClock([TempoMap(120)], controls=None)
    for _ in range(10):
        fake.advance(fake.engine.step())
    assert all(b in (START, CLOCK) for b in fake.messages)
