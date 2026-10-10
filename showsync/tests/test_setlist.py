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


def test_optional_midi_key_resolves_and_never_gates_loading(tmp_path):
    path = write(tmp_path, dict(name='Song', file='song.wav', bpm=120, midi='parts/song.mid'))
    result = load_setlist(path)  # the .mid does not exist; audio checks still pass
    assert result.songs[0].midi == tmp_path / 'parts' / 'song.mid'
    assert load_setlist(write(tmp_path, dict(name='Song', file='song.wav', bpm=120))).songs[0].midi is None


@pytest.mark.parametrize('midi, message', [
    ('song.wav', 'midi must be a .mid or .midi file'),
    (7, 'midi must be a nonempty string'),
    ('', 'midi must be a nonempty string'),
])
def test_invalid_midi_reference_rejected(tmp_path, midi, message):
    with pytest.raises(SetlistError, match=message):
        load_setlist(write(tmp_path, dict(name='Song', file='song.wav', bpm=120, midi=midi)))


def test_trim_field_loads_and_defaults(tmp_path):
    path = write(tmp_path, dict(name='Song', file='song.wav', bpm=120, trim=8.656))
    assert load_setlist(path, duration_probe=lambda _: 60).songs[0].trim == 8.656
    assert load_setlist(write(tmp_path, dict(name='Song', file='song.wav', bpm=120))).songs[0].trim == 0


@pytest.mark.parametrize('trim, probe, message', [
    (-1, None, 'trim must be finite and nonnegative'),
    ('x', None, 'trim must be a number'),
    (10, lambda _: 10, 'trim must be under the file duration'),
    (12, lambda _: 10, 'trim must be under the file duration'),
])
def test_bad_trims_rejected(tmp_path, trim, probe, message):
    path = write(tmp_path, dict(name='Song', file='song.wav', bpm=120, trim=trim))
    with pytest.raises(SetlistError, match=message):
        load_setlist(path, duration_probe=probe)


def test_tempo_event_before_trim_rejected(tmp_path):
    path = write(tmp_path, dict(name='Song', file='song.wav', bpm=120, trim=5,
                                tempo=[dict(at=3, bpm=140)]))
    with pytest.raises(SetlistError, match=r'tempo\[0\].at must not be before trim'):
        load_setlist(path, duration_probe=lambda _: 60)


def test_trim_is_beat_zero_of_the_tempo_map(tmp_path):
    # Trim past the beat anchor: playback starts on the one, so beat 0 is t=0.
    path = write(tmp_path, dict(name='Song', file='song.wav', bpm=120, offset=0.163, trim=8.656))
    song = load_setlist(path, duration_probe=lambda _: 60).songs[0]
    tempo = song.tempo_map(60 - song.trim)
    assert tempo.offset == 0
    assert tempo.T(0) == 0
    assert tempo.T(4) == pytest.approx(2.0)
    # Trim inside the lead-in: beat 0 keeps its remaining lead-in.
    path = write(tmp_path, dict(name='Song', file='song.wav', bpm=120, offset=2.5, trim=1))
    tempo = load_setlist(path, duration_probe=lambda _: 60).songs[0].tempo_map(59)
    assert tempo.offset == 1.5
    assert tempo.B(1.5) == 0


def test_trimmed_ambient_bed_interlude(tmp_path):
    # The live set's transition shape (T173): a 25s beatless bed trimmed to an
    # 8s heard length, carrying the outgoing->incoming ramp so the tempo has
    # settled on the target before the bar-quantized boundary Stop/Start.
    path = write(tmp_path, dict(name='Rise', file='song.wav', bpm=112.003456, trim=17,
                                tempo=[dict(at=18, bpm=120, ramp=6)]))
    song = load_setlist(path, duration_probe=lambda _: 25).songs[0]
    heard = 25 - song.trim
    assert heard == pytest.approx(8)
    tempo = song.tempo_map(heard)
    assert tempo.bpm_at(0) == pytest.approx(112.003456)
    assert tempo.bpm_at(4) == pytest.approx(116.001728)  # mid-ramp glide
    assert tempo.bpm_at(7) == 120  # ramp lands a second before the boundary
    assert tempo.bpm_at(heard) == 120


def test_trim_shifts_tempo_events_with_the_timeline(tmp_path):
    trimmed = write(tmp_path, dict(name='Song', file='song.wav', bpm=120, trim=2,
                                   tempo=[dict(at=10, bpm=140, ramp=20)]))
    plain = write(tmp_path, dict(name='Song', file='song.wav', bpm=120,
                                 tempo=[dict(at=8, bpm=140, ramp=20)]))
    ours = load_setlist(trimmed, duration_probe=lambda _: 60).songs[0].tempo_map(58)
    theirs = load_setlist(plain, duration_probe=lambda _: 58).songs[0].tempo_map(58)
    for t in (0, 5, 8, 15, 28, 40):
        assert ours.B(t) == pytest.approx(theirs.B(t), abs=1e-12)
        assert ours.bpm_at(t) == theirs.bpm_at(t)


@pytest.mark.parametrize('midi, loop, beats, port', [
    ('part.mid', False, None, None),
    ({'file': 'part.mid', 'loop': True, 'bars': 3, 'port': 'Synth'}, True, 12, 'Synth'),
    ({'file': 'part.mid', 'loop': True, 'beats': 7.5, 'port': 0}, True, 7.5, 0),
])
def test_midi_forms_preserve_order_roundtrip(tmp_path, midi, loop, beats, port):
    path = write(tmp_path, dict(name='Song', file='song.wav', bpm=120, midi=midi))
    save_song_order(path, [0])
    preserved = path.read_text()
    save_song_order(path, [0])
    assert path.read_text() == preserved
    song = load_setlist(path).songs[0]
    assert song.midi == tmp_path / 'part.mid'
    assert (song.midi_loop, song.midi_beats, song.midi_port) == (loop, beats, port)


@pytest.mark.parametrize('options, message', [
    ({'loop': 'yes'}, 'midi.loop'),
    ({'beats': 0}, 'midi.beats'),
    ({'bars': -1}, 'midi.bars'),
    ({'beats': float('inf')}, 'midi.beats'),
    ({'beats': True}, 'midi.beats'),
    ({'beats': 4, 'bars': 1}, 'choose beats or bars'),
    ({'port': -1}, 'midi.port'),
    ({'port': True}, 'midi.port'),
    ({'port': ''}, 'midi.port'),
    ({'unknown': 1}, 'unknown fields'),
])
def test_invalid_midi_options_have_context(tmp_path, options, message):
    path = write(tmp_path, dict(name='Song', file='song.wav', bpm=120,
                               midi=dict(file='part.mid', **options)))
    with pytest.raises(SetlistError, match=message) as exc:
        load_setlist(path)
    assert 'song 1 (Song)' in str(exc.value)


def write_set(tmp_path, data):
    (tmp_path / 'song.wav').touch()
    path = tmp_path / 'set.yaml'
    path.write_text(yaml.safe_dump(dict(songs=[dict(name='Song', file='song.wav', bpm=120)],
                                        **data)))
    return path


def test_midi_outputs_parse_names_substrings_and_indices(tmp_path):
    path = write_set(tmp_path, dict(midi_outputs=['Midi Out 1', 'Midi Out 2', 2]))
    result = load_setlist(path, duration_probe=lambda _: 60)
    assert result.midi_outputs == ('Midi Out 1', 'Midi Out 2', 2)


def test_midi_outputs_parse_per_port_filters(tmp_path):
    from showsync.setlist import EgressFilter
    path = write_set(tmp_path, dict(midi_outputs=[
        {'port': 'KeyStep', 'send': ['clock']},
        {'port': 'Midi Out 2', 'send': ['clock', 'cues', 'clock']},  # dupe folds
        {'port': 1},            # long-winded bare entry: full egress
        'Midi Out 1']))         # bare string back-compat
    result = load_setlist(path, duration_probe=lambda _: 60)
    assert result.midi_outputs == (EgressFilter('KeyStep', ('clock',)),
                                   EgressFilter('Midi Out 2', ('clock', 'cues')),
                                   1, 'Midi Out 1')


def test_midi_outputs_default_is_empty(tmp_path):
    path = write_set(tmp_path, {})
    assert load_setlist(path, duration_probe=lambda _: 60).midi_outputs == ()


@pytest.mark.parametrize('outputs, message', [
    ('Midi Out 1', 'midi_outputs must be a nonempty list'),
    ([], 'midi_outputs must be a nonempty list'),
    ([''], r'midi_outputs\[0\]'),
    ([-1], r'midi_outputs\[0\]'),
    ([True], r'midi_outputs\[0\]'),
    ([{'send': ['clock']}], r'midi_outputs\[0\] needs a port'),
    ([{'port': 'KeyStep', 'send': []}], r'midi_outputs\[0\].send must be a nonempty list'),
    ([{'port': 'KeyStep', 'send': 'clock'}], r'midi_outputs\[0\].send must be a nonempty list'),
    ([{'port': 'KeyStep', 'send': ['notes']}], r'unknown class'),
    ([{'port': 'KeyStep', 'send': [1]}], r'midi_outputs\[0\].send'),
    ([{'port': '', 'send': ['clock']}], r'midi_outputs\[0\].port'),
    ([{'port': 'KeyStep', 'send': ['clock'], 'extra': 1}], 'unknown fields'),
])
def test_invalid_midi_outputs_have_context(tmp_path, outputs, message):
    path = write_set(tmp_path, dict(midi_outputs=outputs))
    with pytest.raises(SetlistError, match=message):
        load_setlist(path, duration_probe=lambda _: 60)


def test_midi_outputs_survive_document_roundtrip(tmp_path):
    from showsync.document import Document
    path = write_set(tmp_path, dict(midi_outputs=['Midi Out 1', 'KeyStep']))
    document = Document.load(path, probe=lambda _: 60)
    assert document.setlist().midi_outputs == ('Midi Out 1', 'KeyStep')
    document.save()
    assert load_setlist(path, duration_probe=lambda _: 60).midi_outputs \
        == ('Midi Out 1', 'KeyStep')


def test_midi_port_accepts_substring(tmp_path):
    path = write(tmp_path, dict(name='Song', file='song.wav', bpm=120,
                                midi=dict(file='part.mid', port='midi out 2')))
    assert load_setlist(path, duration_probe=lambda _: 60).songs[0].midi_port == 'midi out 2'
