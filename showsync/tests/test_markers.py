"""Take-marker sidecar: song/tempo events on the recording's timeline."""
import json
import time
from types import SimpleNamespace

from showsync.audio import Position
from showsync.markers import MarkerWriter, song_fields
from showsync.setlist import Setlist, Song
from showsync.tempomap import TempoEvent


def make_layout():
    songs = (Song('one', 'one.wav', 112.5),
             Song('ramp', 'bed.wav', 112.5, trim=17,
                  tempo=(TempoEvent(18, 130, 6),)))
    return SimpleNamespace(setlist=Setlist('Test set', songs),
                           durations=(4.0, 8.0))


class ScriptedAudio:
    """position() returns each scripted Position once, then holds the last."""

    def __init__(self, *positions):
        self.positions = list(positions)

    def position(self):
        if len(self.positions) > 1:
            return self.positions.pop(0)
        return self.positions[0]


def read_markers(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def wait_for(path, event, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        records = read_markers(path)
        if any(r['event'] == event for r in records):
            return records
        time.sleep(0.01)
    raise AssertionError(f'no {event} marker in {read_markers(path)}')


def test_song_fields_trim_adjusts_tempo_events():
    layout = make_layout()
    fields = song_fields(layout.setlist.songs[1], duration=8.0)
    assert fields['name'] == 'ramp'
    assert fields['bpm'] == 112.5
    assert fields['trim'] == 17
    assert fields['tempo'] == [{'at': 1, 'bpm': 130, 'ramp': 6}]
    assert fields['duration'] == 8.0
    assert 'tempo' not in song_fields(layout.setlist.songs[0])


def test_from_env_requires_path(tmp_path):
    assert MarkerWriter.from_env(environ={}) is None
    writer = MarkerWriter.from_env(environ={
        'SHOWSYNC_MARKERS': str(tmp_path / 'take.markers'),
        'SHOWSYNC_MARKERS_EPOCH': 'not-a-number'})
    assert writer is not None and writer.rec_epoch is None
    writer.close()
    bad = MarkerWriter.from_env(environ={
        'SHOWSYNC_MARKERS': str(tmp_path / 'no' / 'dir' / 'take.markers')})
    assert bad is None


def test_watch_records_set_and_song_starts(tmp_path):
    path = tmp_path / 'take.markers'
    layout = make_layout()
    rec_epoch = time.time() - 10  # recording started 10s ago
    audio = ScriptedAudio(
        Position(0, 0.0, False, layout=layout),            # engines up, pre-play
        Position(0, 0.01, True, layout=layout),            # song one audible
        Position(0, 2.0, True, layout=layout),
        Position(1, 0.05, True, layout=layout),            # boundary crossed
        Position(1, 1.0, True, layout=layout))
    writer = MarkerWriter(path, rec_epoch=rec_epoch, setlist_path='set.yaml')
    writer.watch(audio)
    records = wait_for(path, 'song_start')
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        records = read_markers(path)
        if sum(r['event'] == 'song_start' for r in records) == 2:
            break
        time.sleep(0.01)
    writer.close()
    records = read_markers(path)

    start = records[0]
    assert start['event'] == 'set_start'
    assert start['set_file'] == 'set.yaml'
    assert start['title'] == 'Test set'
    assert [s['name'] for s in start['songs']] == ['one', 'ramp']
    assert start['songs'][1]['tempo'] == [{'at': 1, 'bpm': 130, 'ramp': 6}]
    assert abs(start['t_rec'] - 10) < 2

    starts = [r for r in records if r['event'] == 'song_start']
    assert [s['song_index'] for s in starts] == [0, 1]
    assert starts[1]['name'] == 'ramp'
    assert starts[1]['tempo'] == [{'at': 1, 'bpm': 130, 'ramp': 6}]
    # The boundary stamp backs out how far into the song the poll caught it.
    assert starts[1]['t_rec'] <= (time.time() - rec_epoch) - 0.05 + 0.001
    assert records[-1]['event'] == 'set_stop'
    # Every record carries the recording-relative clock.
    assert all('t_rec' in r and 'epoch' in r for r in records)


def test_pause_resume_and_set_end(tmp_path):
    path = tmp_path / 'take.markers'
    layout = make_layout()
    audio = ScriptedAudio(
        Position(0, 0.0, False, layout=layout),            # consumed by watch()
        Position(0, 0.5, True, layout=layout),
        Position(0, 1.0, False, layout=layout),            # paused
        Position(0, 1.0, True, epoch=0, layout=layout),    # resumed
        Position(1, 8.0, True, ended=True, layout=layout))  # played out
    writer = MarkerWriter(path, rec_epoch=time.time())
    writer.watch(audio)
    records = wait_for(path, 'set_end')
    writer.close()
    events = [r['event'] for r in read_markers(path)]
    assert events == ['set_start', 'song_start', 'pause', 'resume',
                      'set_end', 'set_stop']
    paused = [r for r in records if r['event'] == 'pause'][0]
    assert paused['song_index'] == 0 and paused['song_time'] == 1.0


def test_restart_same_song_new_epoch_marks_again(tmp_path):
    path = tmp_path / 'take.markers'
    layout = make_layout()
    audio = ScriptedAudio(
        Position(0, 0.0, False, layout=layout),            # consumed by watch()
        Position(0, 0.5, True, epoch=0, layout=layout),
        Position(0, 0.1, True, epoch=1, layout=layout))    # restart (skip)
    writer = MarkerWriter(path, rec_epoch=time.time())
    writer.watch(audio)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if sum(r['event'] == 'song_start' for r in read_markers(path)) == 2:
            break
        time.sleep(0.01)
    writer.close()
    starts = [r for r in read_markers(path) if r['event'] == 'song_start']
    assert [s['song_index'] for s in starts] == [0, 0]


def test_close_is_idempotent_and_appends(tmp_path):
    path = tmp_path / 'take.markers'
    path.write_text('{"event":"recording_start","t_rec":0.0}\n')
    writer = MarkerWriter(path, rec_epoch=time.time())
    writer.emit('song_start', song_index=0)
    writer.close()
    writer.close()
    writer.emit('late', song_index=1)  # after close: silently dropped
    events = [r['event'] for r in read_markers(path)]
    assert events == ['recording_start', 'song_start', 'set_stop']
