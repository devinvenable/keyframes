from pathlib import Path

import pytest

from showsync.document import Document, Row
from showsync.setlist import SetlistError, load_setlist

FIXTURES = Path(__file__).parent / 'fixtures'
TONE = FIXTURES / 'tone.wav'

COMMENTED = """\
title: "Rehearsal set"   # working title
songs:
  - name: "Opener"
    file: tone.wav
    bpm: 120
    tempo:
      - at: 0.4            # bridge jump
        bpm: 126
  - name: "Closer"       # crowd favourite
    file: tone.wav
    bpm: 90
"""


def probe(_):
    return 60.0


def commented_set(tmp_path):
    path = tmp_path / 'set.yaml'
    (tmp_path / 'tone.wav').write_bytes(TONE.read_bytes())
    path.write_text(COMMENTED, encoding='utf-8')
    return path


def test_lenient_load_marks_problems_instead_of_refusing(tmp_path):
    path = tmp_path / 'set.yaml'
    path.write_text(f'songs:\n'
                    f'  - name: NoBpm\n    file: {TONE}\n'
                    f'  - name: Gone\n    file: {tmp_path}/gone.wav\n'
                    f'  - name: Fine\n    file: {TONE}\n    bpm: 120\n')
    document = Document.load(path, probe=probe)
    assert [row.problem() for row in document.rows] == \
        ['BPM not set', 'audio file not found', None]
    assert document.rows[0].duration == 60
    row, message = document.first_problem()
    assert (row.name, message) == ('NoBpm', 'BPM not set')
    with pytest.raises(SetlistError, match='NoBpm'):
        document.setlist()


def test_empty_and_new_documents():
    document = Document()
    assert document.first_problem() == (None, 'the set has no songs')
    assert document.display_title == 'New set'
    assert document.default_save_directory() == Path.home()
    with pytest.raises(SetlistError, match='no file chosen'):
        Document(rows=[Row('X', TONE, 120)]).save()


def test_add_files_probes_and_rejects(tmp_path):
    document = Document()
    bad = tmp_path / 'broken.wav'
    bad.write_bytes(b'not audio')
    added, rejected = document.add_files(
        [TONE, tmp_path / 'notes.txt', tmp_path / 'gone.wav', bad])
    assert [row.name for row in added] == ['tone']
    assert added[0].bpm is None and added[0].offset == 0
    assert added[0].duration == pytest.approx(1.0)  # real decode probe
    assert [(p.name, r.split(':')[0]) for p, r in rejected] == \
        [('notes.txt', 'unsupported file type'), ('gone.wav', 'not a file'),
         ('broken.wav', 'cannot decode')]
    assert document.default_save_directory() == TONE.parent


def test_unchanged_save_is_byte_stable(tmp_path):
    path = commented_set(tmp_path)
    document = Document.load(path, probe=probe)
    document.save()
    assert path.read_text(encoding='utf-8') == COMMENTED


def test_edit_save_round_trip_preserves_comments(tmp_path):
    path = commented_set(tmp_path)
    document = Document.load(path, probe=probe)
    document.rows[0].bpm = 124.5
    document.rows[0].offset = 0.25
    document.rows[1].name = 'Encore'
    document.save()
    text = path.read_text(encoding='utf-8')
    assert '# bridge jump' in text and '# working title' in text
    assert '# crowd favourite' in text  # comment survives the rename
    reloaded = load_setlist(path, duration_probe=probe)
    assert reloaded.songs[0].bpm == 124.5
    assert reloaded.songs[0].offset == 0.25
    assert reloaded.songs[0].tempo[0].at == 0.4  # untouched fields intact
    assert reloaded.songs[1].name == 'Encore'


def test_add_remove_reorder_and_offset_removal(tmp_path):
    path = commented_set(tmp_path)
    document = Document.load(path, probe=probe)
    added, _ = document.add_files([TONE], probe=probe)
    added[0].bpm = 100
    document.rows = [document.rows[2], document.rows[0]]  # drop Closer, new song first
    document.save()
    text = path.read_text(encoding='utf-8')
    assert 'Closer' not in text and '# bridge jump' in text
    reloaded = Document.load(path, probe=probe)
    assert [row.name for row in reloaded.rows] == ['tone', 'Opener']
    # A second identity save right after is byte-stable again.
    before = path.read_text(encoding='utf-8')
    document.save()
    assert path.read_text(encoding='utf-8') == before
    # Clearing the offset removes the key from the file entirely.
    document.rows[1].offset = 2.0
    document.save()
    assert 'offset: 2' in path.read_text(encoding='utf-8')
    document.rows[1].offset = 0.0
    document.save()
    assert 'offset:' not in path.read_text(encoding='utf-8')


def test_save_new_set_writes_portable_paths(tmp_path):
    local = tmp_path / 'tone.wav'
    local.write_bytes(TONE.read_bytes())
    document = Document()
    document.add_files([local, TONE], probe=probe)
    for row in document.rows:
        row.bpm = 120
    document.path = tmp_path / 'new.yaml'
    document.save()
    text = (tmp_path / 'new.yaml').read_text(encoding='utf-8')
    assert 'file: tone.wav' in text          # sibling file saved relative
    assert str(TONE) in text                 # foreign file stays absolute
    playable = load_setlist(tmp_path / 'new.yaml', duration_probe=probe)
    assert [song.bpm for song in playable.songs] == [120, 120]
    assert document.rows[0].source_index == 0  # future saves round-trip


def test_load_rejects_structural_garbage(tmp_path):
    path = tmp_path / 'set.yaml'
    for text in ('songs: 4', '- 1\n- 2', 'songs:\n  - name: X\n    file: x.wav\n    bpm: [1]',
                 'songs:\n  - nope: 1'):
        path.write_text(text)
        with pytest.raises(SetlistError):
            Document.load(path, probe=probe)


MULTI_EVENT = """\
title: "Hand set"
songs:
  - name: "Weird"
    file: tone.wav
    bpm: 120
    tempo:
      - at: "1:35.5"     # bridge jump
        bpm: 126
      - at: 110.0        # outro glide
        bpm: 96
        ramp: 30.0
  - name: "Plain"
    file: tone.wav
    bpm: 100
"""


def test_row_simple_ramp_classification():
    from showsync.tempomap import TempoEvent
    row = Row('X', TONE, 120)
    assert row.ramp is None and not row.custom_tempo
    row.tempo = (TempoEvent(10, 140, 20),)
    assert row.ramp == TempoEvent(10, 140, 20) and not row.custom_tempo
    row.tempo = (TempoEvent(10, 140),)  # hard jump: not expressible as a ramp
    assert row.custom_tempo and row.ramp is None
    row.tempo = (TempoEvent(10, 140, 5), TempoEvent(30, 120, 5))
    assert row.custom_tempo and row.ramp is None


def test_multi_event_maps_survive_unrelated_editor_saves(tmp_path):
    from showsync.tempomap import TempoEvent
    path = tmp_path / 'set.yaml'
    (tmp_path / 'tone.wav').write_bytes(TONE.read_bytes())
    path.write_text(MULTI_EVENT, encoding='utf-8')
    document = Document.load(path, probe=lambda _: 200.0)
    assert document.rows[0].custom_tempo
    document.rows[0].name = 'Weirder'          # unrelated edits only
    document.rows[1].bpm = 101
    document.save()
    text = path.read_text(encoding='utf-8')
    assert 'at: "1:35.5"     # bridge jump' in text   # node untouched, verbatim
    assert '# outro glide' in text
    reloaded = Document.load(path, probe=lambda _: 200.0)
    assert reloaded.rows[0].tempo == (TempoEvent(95.5, 126, 0),
                                      TempoEvent(110.0, 96.0, 30.0))
    assert reloaded.rows[0].name == 'Weirder'
    assert reloaded.rows[1].bpm == 101


def test_simple_ramp_saves_as_tempo_event_and_clears(tmp_path):
    from showsync.tempomap import TempoEvent
    path = commented_set(tmp_path)
    document = Document.load(path, probe=probe)
    document.rows[1].tempo = (TempoEvent(10, 140, 20),)   # Closer gains a ramp
    document.save()
    reloaded = Document.load(path, probe=probe)
    assert reloaded.rows[1].ramp == TempoEvent(10, 140, 20)
    assert '# crowd favourite' in path.read_text(encoding='utf-8')
    playable = load_setlist(path, duration_probe=probe)
    assert playable.songs[1].tempo == (TempoEvent(10, 140, 20),)
    reloaded.rows[1].tempo = ()                           # and loses it again
    reloaded.save()
    text = path.read_text(encoding='utf-8')
    assert text.count('tempo:') == 1                      # only Opener's map left
    assert '# bridge jump' in text


MIDI_SET = """\
title: "Midi set"
songs:
  - name: "Opener"
    file: tone.wav
    bpm: 120
    midi: parts/opener.mid   # GM backing for the synth rack
"""


def test_midi_key_survives_editor_round_trip_byte_stable(tmp_path):
    path = tmp_path / 'set.yaml'
    (tmp_path / 'tone.wav').write_bytes(TONE.read_bytes())
    path.write_text(MIDI_SET, encoding='utf-8')
    document = Document.load(path, probe=probe)
    assert document.rows[0].midi == tmp_path / 'parts' / 'opener.mid'
    document.save()
    assert path.read_text(encoding='utf-8') == MIDI_SET
    document.rows[0].bpm = 121
    document.save()
    reloaded = load_setlist(path, duration_probe=probe)
    assert reloaded.songs[0].midi == tmp_path / 'parts' / 'opener.mid'
    assert '# GM backing' in path.read_text(encoding='utf-8')
