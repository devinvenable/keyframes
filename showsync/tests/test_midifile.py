"""GM MIDI file playback: beats from ticks, clock-thread scheduling, note safety."""
from dataclasses import replace
from pathlib import Path

import mido
import pytest

from showsync.audio import Position
from showsync.clock import CLOCK, START, STOP, ClockEngine
from showsync.midifile import (MidiEvent, MidiEventsView, load_midi_events,
                               load_setlist_events)
from showsync.setlist import Setlist, Song
from showsync.tempomap import TempoEvent as E, TempoMap

FIXTURES = Path(__file__).parent / 'fixtures'


def write_mid(path, tracks, ticks_per_beat=480):
    file = mido.MidiFile(ticks_per_beat=ticks_per_beat)
    for messages in tracks:
        track = mido.MidiTrack()
        track.extend(messages)
        file.tracks.append(track)
    file.save(path)
    return path


def test_ticks_become_beats_and_embedded_tempo_is_ignored(tmp_path):
    path = write_mid(tmp_path / 'song.mid', [[
        mido.MetaMessage('set_tempo', tempo=250_000, time=0),  # 240 BPM: ignored
        mido.Message('program_change', program=5, time=0),
        mido.Message('note_on', note=60, velocity=100, time=480),
        mido.MetaMessage('set_tempo', tempo=1_000_000, time=240),
        mido.Message('note_off', note=60, velocity=0, time=240),
    ]])
    events = load_midi_events(path)
    assert events == (MidiEvent(0.0, (0xC0, 5)),
                      MidiEvent(1.0, (0x90, 60, 100)),
                      MidiEvent(2.0, (0x80, 60, 0)))


def test_multitrack_merge_keeps_same_tick_order(tmp_path):
    path = write_mid(tmp_path / 'song.mid', [
        [mido.Message('control_change', control=0, value=1, time=0),
         mido.Message('program_change', program=9, time=0)],
        [mido.Message('note_on', channel=9, note=36, velocity=90, time=960)],
    ], ticks_per_beat=960)
    events = load_midi_events(path)
    assert events == (MidiEvent(0.0, (0xB0, 0, 1)),
                      MidiEvent(0.0, (0xC0, 9)),
                      MidiEvent(1.0, (0x99, 36, 90)))


def test_missing_or_unreadable_file_warns_and_plays_without(tmp_path, caplog):
    missing = Song('A', FIXTURES / 'tone.wav', 120, midi=tmp_path / 'nope.mid')
    garbage = tmp_path / 'bad.mid'
    garbage.write_bytes(b'not a midi file')
    unreadable = Song('B', FIXTURES / 'tone.wav', 120, midi=garbage)
    with caplog.at_level('WARNING'):
        by_path = load_setlist_events(Setlist('t', (missing, unreadable)))
    assert by_path == {missing.midi: (), garbage: ()}
    assert 'nope.mid' in caplog.text and 'bad.mid' in caplog.text


def test_songs_without_midi_load_nothing(tmp_path):
    assert load_setlist_events(Setlist('t', (Song('A', FIXTURES / 'tone.wav', 120),))) == {}


class Fake:
    def __init__(self, maps, events=None):
        self.time = 0.0
        self.p = Position(0, 0, True)
        self.messages = []
        self.engine = ClockEngine(maps, lambda: self.p,
                                  lambda m: self.messages.append((self.time, m)),
                                  now=lambda: self.time, sleep=self.advance,
                                  events=events)

    def advance(self, dt):
        self.time += dt
        self.p = replace(self.p, song_time=self.p.song_time + dt)

    def run_until(self, t):
        while self.p.song_time < t:
            self.advance(max(self.engine.step(), 1e-6))

    def sent(self):
        return [(t, m) for t, m in self.messages if isinstance(m, tuple)]


EVENTS = (MidiEvent(0.0, (0x90, 60, 100)), MidiEvent(1.0, (0x80, 60, 0)),
          MidiEvent(2.5, (0x91, 64, 90)), MidiEvent(4.0, (0x81, 64, 0)))


@pytest.mark.parametrize('events', [[], [E(.3, 180, .7)], [E(.1, 60, .8), E(1, 140)]])
def test_events_fire_exactly_on_the_tempo_map(events):
    tempo = TempoMap(120, events)
    fake = Fake([tempo], events=[EVENTS])
    fake.run_until(tempo.T(4.5))
    sent = fake.sent()
    assert [m for _, m in sent] == [e.data for e in EVENTS]
    assert [t for t, _ in sent] == pytest.approx([tempo.T(e.beat) for e in EVENTS], abs=1e-9)
    # The clock itself is untouched: tick timestamps stay on the map's grid.
    ticks = [t for t, m in fake.messages if m == CLOCK]
    assert ticks == pytest.approx([tempo.T(k / 24) for k in range(len(ticks))], abs=1e-9)


def test_lead_in_offset_delays_events_to_the_downbeat():
    tempo = TempoMap(120, offset=2.0)
    fake = Fake([tempo], events=[EVENTS[:2]])
    fake.run_until(3.0)
    sent = fake.sent()
    assert [t for t, _ in sent] == pytest.approx([2.0, 2.5], abs=1e-9)


@pytest.mark.parametrize('offset', [-32, 32])
def test_clock_offset_shifts_events_with_the_ticks(offset):
    tempo = TempoMap(120)
    fake = Fake([tempo], events=[EVENTS[:2]])
    fake.engine.clock_offset_ms = offset
    fake.run_until(1.5)
    assert [t for t, _ in fake.sent()] == pytest.approx(
        [max(0, tempo.T(e.beat) - offset / 1000) for e in EVENTS[:2]], abs=1e-9)


def test_pause_sends_sustain_off_then_all_notes_off_then_stop_and_resume_replays_nothing():
    fake = Fake([TempoMap(120)], events=[EVENTS])
    fake.run_until(.6)  # note 60 on, its off at beat 1 (t=0.5) already sent
    fake.p = replace(fake.p, playing=False)
    fake.engine.step()
    assert fake.messages[-3:] == [(fake.time, (0xB0, 64, 0)),
                                  (fake.time, (0xB0, 123, 0)),
                                  (fake.time, STOP)]
    before = len(fake.sent())
    fake.p = replace(fake.p, playing=True)
    fake.run_until(1.0)
    # Only events beyond the pause point are new; nothing replays.
    assert [m for _, m in fake.sent()[before:]] == []
    fake.run_until(1.3)
    assert fake.sent()[-1][1] == EVENTS[2].data


def test_sustain_pedal_channel_gets_flushed_even_without_new_notes():
    events = (MidiEvent(0.0, (0xB3, 64, 127)),)
    fake = Fake([TempoMap(120)], events=[events])
    fake.run_until(.1)
    fake.p = replace(fake.p, playing=False)
    fake.engine.step()
    assert (fake.time, (0xB3, 64, 0)) in fake.messages
    assert (fake.time, (0xB3, 123, 0)) in fake.messages


def test_skip_flushes_and_restarts_the_next_songs_events_from_zero():
    per_song = [EVENTS, (MidiEvent(0.0, (0x92, 40, 80)),)]
    fake = Fake([TempoMap(120), TempoMap(90)], events=per_song)
    fake.run_until(.2)
    base = fake.time
    fake.p = Position(1, 0, True, epoch=1)
    fake.engine.step()
    tail = [m for t, m in fake.messages if t >= base]
    assert tail[:3] == [(0xB0, 64, 0), (0xB0, 123, 0), STOP]
    assert (0x92, 40, 80) in tail
    assert tail.index(START) < tail.index((0x92, 40, 80))


def test_restart_replays_song_one_from_the_top():
    fake = Fake([TempoMap(120)], events=[EVENTS[:2]])
    fake.run_until(.6)
    assert len(fake.sent()) == 2
    fake.p = Position(0, 0, True, epoch=1)
    base = fake.time
    fake.run_until(.6)
    # The reset first flushes the hanging note, then replays from beat 0.
    assert [m for t, m in fake.sent() if t >= base] == \
        [(0xB0, 64, 0), (0xB0, 123, 0)] + [e.data for e in EVENTS[:2]]


def test_close_while_active_flushes_before_stop():
    fake = Fake([TempoMap(120)], events=[EVENTS])
    fake.run_until(.1)
    fake.engine.close()
    tail = [m for _, m in fake.messages[-3:]]
    assert tail == [(0xB0, 64, 0), (0xB0, 123, 0), STOP]


def test_no_events_means_no_flush_traffic():
    fake = Fake([TempoMap(120)], events=[()])
    fake.run_until(.3)
    fake.p = replace(fake.p, playing=False)
    fake.engine.step()
    assert all(m in (START, CLOCK, STOP) for _, m in fake.messages)


def test_events_view_follows_reorders():
    class Engine:
        pass
    class Layout:
        pass
    a = Song('A', FIXTURES / 'tone.wav', 120, midi=Path('/a.mid'))
    b = Song('B', FIXTURES / 'tone.wav', 90)
    engine, layout = Engine(), Layout()
    layout.setlist = Setlist('t', (a, b))
    engine._layout = layout
    view = MidiEventsView(engine, {Path('/a.mid'): EVENTS})
    assert view[0] == EVENTS and view[1] == ()
    layout.setlist = Setlist('t', (b, a))
    assert view[0] == () and view[1] == EVENTS
