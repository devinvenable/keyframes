from pathlib import Path

from showsync.appstate import last_setlist, remember_setlist, state_file


def test_round_trip_and_missing_target(tmp_path):
    state = tmp_path / 'nested' / 'state.json'
    setlist = tmp_path / 'set.yaml'
    setlist.write_text('songs: []')
    assert last_setlist(state) is None          # nothing recorded yet
    remember_setlist(setlist, state)
    assert last_setlist(state) == setlist.resolve()
    setlist.unlink()                            # deleted set: pointer is dropped
    assert last_setlist(state) is None


def test_corrupt_state_is_ignored(tmp_path):
    state = tmp_path / 'state.json'
    for garbage in ('not json', '{"last_setlist": 4}', '[]'):
        state.write_text(garbage)
        assert last_setlist(state) is None


def test_state_file_is_per_user():
    path = state_file()
    assert path.name == 'state.json'
    assert 'showsync' in path.parts
    assert path.is_absolute()


def test_clock_offset_preserves_last_set_and_other_state(tmp_path):
    from showsync.appstate import clock_offset_ms, remember_clock_offset
    state = tmp_path / 'state.json'
    song = tmp_path / 'set.yaml'
    song.touch()
    remember_setlist(song, state)
    remember_clock_offset(32, state)
    assert clock_offset_ms(state) == 32
    assert last_setlist(state) == song
    remember_setlist(song, state)
    assert clock_offset_ms(state) == 32


def test_invalid_clock_offset_defaults_to_zero(tmp_path):
    import json
    from showsync.appstate import clock_offset_ms
    state = tmp_path / 'state.json'
    for value in [True, '32', None, 251, -251, float('nan'), float('inf')]:
        state.write_text(json.dumps({'clock_offset_ms': value}))
        assert clock_offset_ms(state) == 0
