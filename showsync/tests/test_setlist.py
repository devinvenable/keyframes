from pathlib import Path

import pytest
import yaml

from showsync.setlist import load_setlist, position, SetlistError

FIXTURES = Path(__file__).parent / 'fixtures'


def test_full_design_fixture():
    result = load_setlist(FIXTURES / 'fall2026.yaml', check_files=False,
                          duration_probe=lambda _: 360)
    assert result.title == 'Fall 2026 set'
    assert len(result.songs) == 5
    assert result.songs[1].tempo[1].at == 210.5
    assert result.songs[2].tempo[0].ramp == 45
    assert result.songs[2].gap == 1.5
    assert result.songs[0].file == Path('~/shows/fall2026/audio/01-cold-open.wav').expanduser()


@pytest.mark.parametrize('raw, seconds', [('1:35.5', 95.5), ('95.5', 95.5), (95.5, 95.5), ('0:00', 0)])
def test_time_formats(raw, seconds):
    assert position(raw) == seconds


@pytest.mark.parametrize('raw', ['1:60', '1:2', '-1', 'NaN', '1:20:30', True, None])
def test_invalid_time(raw):
    with pytest.raises(ValueError):
        position(raw)


def write(tmp_path, row):
    (tmp_path / 'song.wav').touch()
    path = tmp_path / 'set.yaml'
    path.write_text(yaml.safe_dump({'songs': [row]}))
    return path


def test_relative_paths_and_defaults(tmp_path):
    result = load_setlist(write(tmp_path, dict(name='Song', file='song.wav', bpm=120)))
    assert result.songs[0].file == tmp_path / 'song.wav'
    assert result.songs[0].gap == 0
    assert result.title == 'set'


@pytest.mark.parametrize('change, field', [({'bpm': False}, 'bpm'), ({'bpm': 0}, 'bpm'),
    ({'bpm': float('nan')}, 'bpm'), ({'gap': -1}, 'gap'), ({'name': ''}, 'name'),
    ({'file': 'missing.wav'}, 'file'), ({'file': 'song.ogg'}, 'file'), ({'oops': 4}, 'unknown'),
    ({'tempo': [{'at': 2, 'bpm': 120}, {'at': 1, 'bpm': 130}]}, 'ascending'),
    ({'tempo': [{'at': 0, 'bpm': 140, 'ramp': 4}, {'at': 2, 'bpm': 120}]}, 'overlaps'),
    ({'tempo': [{'at': '1:90', 'bpm': 140}]}, 'tempo[0]'), ({'tempo': None}, 'tempo')])
def test_contextual_errors(tmp_path, change, field):
    row = dict(name='Song', file='song.wav', bpm=120)
    row.update(change)
    with pytest.raises(SetlistError) as exc:
        load_setlist(write(tmp_path, row))
    assert 'set.yaml: song 1' in str(exc.value)
    assert field in str(exc.value)


def test_duration_checked_at_load(tmp_path):
    path = write(tmp_path, dict(name='Song', file='song.wav', bpm=120,
                                tempo=[dict(at=9, bpm=140, ramp=2)]))
    with pytest.raises(SetlistError, match='duration'):
        load_setlist(path, duration_probe=lambda _: 10)


def test_unsafe_yaml_rejected(tmp_path):
    path = tmp_path / 'bad.yaml'
    path.write_text('!!python/object/apply:os.system [echo unsafe]')
    with pytest.raises(SetlistError, match='constructor'):
        load_setlist(path)
