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
    assert 'offset' not in path.read_text(encoding='utf-8')


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
