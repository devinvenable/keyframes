from pathlib import Path

import pytest
import yaml

from showsync.setlist import load_setlist, position, save_song_order, SetlistError

FIXTURES = Path(__file__).parent / 'fixtures'
DEMO = Path(__file__).parent.parent / 'demo' / 'demo-setlist.yaml'


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
    assert not hasattr(result.songs[0], 'restart')
    assert result.title == 'set'


@pytest.mark.parametrize('restart', [True, False])
def test_legacy_restart_boolean_is_inert(tmp_path, restart):
    path = write(tmp_path, dict(name='Song', file='song.wav', bpm=120, restart=restart))
    assert not hasattr(load_setlist(path).songs[0], 'restart')


@pytest.mark.parametrize('restart', ['true', 1, None])
def test_restart_rejects_non_boolean(tmp_path, restart):
    path = write(tmp_path, dict(name='Song', file='song.wav', bpm=120, restart=restart))
    with pytest.raises(SetlistError, match='restart must be a boolean'):
        load_setlist(path)


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


@pytest.mark.parametrize('source', [FIXTURES / 'fall2026.yaml', FIXTURES / 'smoke.yaml', DEMO])
def test_save_order_unchanged_is_byte_stable(tmp_path, source):
    target = tmp_path / source.name
    text = source.read_text(encoding='utf-8')
    target.write_text(text, encoding='utf-8')
    count = len(load_setlist(target, check_files=False, duration_probe=lambda _: 360).songs)
    save_song_order(target, list(range(count)))
    assert target.read_text(encoding='utf-8') == text


def test_save_order_reorders_and_keeps_comments(tmp_path):
    target = tmp_path / 'set.yaml'
    target.write_text((FIXTURES / 'fall2026.yaml').read_text(encoding='utf-8'), encoding='utf-8')
    save_song_order(target, [4, 0, 1, 2, 3])
    text = target.read_text(encoding='utf-8')
    for comment in ('# hard jump into the bridge', '# back to verse tempo',
                    '# ambient section: linear ramp 120 -> 140 over 45 s starting at 0:20',
                    '# slow outro ramp-down'):
        assert comment in text
    # The outro comment travels with "Closer" to the top of the file.
    assert text.index('# slow outro ramp-down') < text.index('Cold Open')
    result = load_setlist(target, check_files=False, duration_probe=lambda _: 360)
    assert [song.name for song in result.songs] == \
        ['Closer', 'Cold Open', 'Signal Path', 'Interlude (beatless)', 'Fourteen Hundred']


def test_save_order_rejects_bad_permutation(tmp_path):
    target = tmp_path / 'set.yaml'
    original = (FIXTURES / 'smoke.yaml').read_text(encoding='utf-8')
    target.write_text(original, encoding='utf-8')
    for order in ([0, 0, 1, 2, 3], [0, 1, 2], [0, 1, 2, 3, 5]):
        with pytest.raises(SetlistError, match='permutation'):
            save_song_order(target, order)
    assert target.read_text(encoding='utf-8') == original


def test_unsafe_yaml_rejected(tmp_path):
    path = tmp_path / 'bad.yaml'
    path.write_text('!!python/object/apply:os.system [echo unsafe]')
    with pytest.raises(SetlistError, match='constructor'):
        load_setlist(path)


def test_offset_field_loads_and_validates(tmp_path):
    path = write(tmp_path, dict(name='Song', file='song.wav', bpm=120, offset=1.5,
                                tempo=[dict(at=5, bpm=140)]))
    result = load_setlist(path, duration_probe=lambda _: 10)
    assert result.songs[0].offset == 1.5
    assert result.songs[0].tempo_map(10).T(0) == 1.5


@pytest.mark.parametrize('offset, probe', [(-1, None), ('x', None), (12, lambda _: 10),
                                           (6, lambda _: 10)])
def test_bad_offsets_rejected(tmp_path, offset, probe):
    path = write(tmp_path, dict(name='Song', file='song.wav', bpm=120, offset=offset,
                                tempo=[dict(at=5, bpm=140)]))
    with pytest.raises(SetlistError, match='offset'):
        load_setlist(path, duration_probe=probe)
