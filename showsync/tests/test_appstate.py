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
