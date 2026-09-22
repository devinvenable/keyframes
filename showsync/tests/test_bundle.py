"""Show bundles must reproduce a set on another machine from the zip alone."""
from pathlib import Path
import zipfile

import pytest

from showsync.bundle import BundleError, export_bundle
from showsync.setlist import load_setlist


def write_setlist(path, text):
    path.write_text(text, encoding='utf-8')
    return path


def make_audio(directory, name, content=b'RIFFfake'):
    directory.mkdir(parents=True, exist_ok=True)
    file = directory / name
    file.write_bytes(content)
    return file


def extract(zip_path, destination):
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(destination)
    return destination


def test_round_trip_absolute_paths(tmp_path):
    """A set with absolute Linux paths plays from the extracted bundle."""
    first = make_audio(tmp_path / 'elsewhere', 'opener.wav', b'opener-bytes')
    second = make_audio(tmp_path / 'assets' / 'sounds', 'closer.mp3', b'closer-bytes')
    setlist = write_setlist(tmp_path / 'show.yaml', f"""\
title: "Fall tour"
songs:
  - name: Opener
    file: {first}
    bpm: 112
    gap: 1.5
    tempo:
      - at: 30
        bpm: 140
        ramp: 4
  - name: Closer
    file: {second}
    bpm: 90
    offset: 0.25
""")
    bundle = tmp_path / 'show-bundle.zip'
    manifest = export_bundle(setlist, bundle)
    assert manifest == ['opener.wav', 'closer.mp3']

    stage = extract(bundle, tmp_path / 'other-machine')
    result = load_setlist(stage / 'show.yaml', duration_probe=lambda _: 300)
    assert result.title == 'Fall tour'
    assert [song.file for song in result.songs] == [stage / 'opener.wav', stage / 'closer.mp3']
    assert (stage / 'opener.wav').read_bytes() == b'opener-bytes'
    assert result.songs[0].bpm == 112
    assert result.songs[0].gap == 1.5
    assert result.songs[0].tempo[0].bpm == 140
    assert result.songs[1].offset == 0.25


def test_bundle_holds_only_setlist_and_audio(tmp_path):
    """No machine state (state.json device/offset choices) travels in a bundle."""
    file = make_audio(tmp_path / 'audio', 'song.wav')
    setlist = write_setlist(tmp_path / 'set.yaml',
                            f'songs:\n  - name: Song\n    file: {file}\n    bpm: 120\n')
    export_bundle(setlist, tmp_path / 'set.zip')
    with zipfile.ZipFile(tmp_path / 'set.zip') as archive:
        assert sorted(archive.namelist()) == ['set.yaml', 'song.wav']


def test_relative_paths_and_audio_root(tmp_path):
    file = make_audio(tmp_path / 'tracks', 'song.flac')
    setlist = write_setlist(tmp_path / 'set.yaml',
                            'audio_root: tracks\nsongs:\n  - name: Song\n    file: song.flac\n    bpm: 100\n')
    export_bundle(setlist, tmp_path / 'set.zip')
    stage = extract(tmp_path / 'set.zip', tmp_path / 'stage')
    result = load_setlist(stage / 'set.yaml', duration_probe=lambda _: 60)
    assert result.songs[0].file == stage / 'song.flac'
    assert file.read_bytes() == (stage / 'song.flac').read_bytes()


def test_basename_collisions_disambiguated(tmp_path):
    first = make_audio(tmp_path / 'a', 'click.wav', b'first')
    second = make_audio(tmp_path / 'b', 'click.wav', b'second')
    third = make_audio(tmp_path / 'c', 'Click.wav', b'third')  # collides on Windows
    setlist = write_setlist(tmp_path / 'set.yaml', f"""\
songs:
  - name: One
    file: {first}
    bpm: 100
  - name: Two
    file: {second}
    bpm: 100
  - name: Three
    file: {third}
    bpm: 100
""")
    manifest = export_bundle(setlist, tmp_path / 'set.zip')
    assert manifest == ['click.wav', 'click-2.wav', 'Click-3.wav']
    stage = extract(tmp_path / 'set.zip', tmp_path / 'stage')
    result = load_setlist(stage / 'set.yaml', duration_probe=lambda _: 60)
    assert [song.file.read_bytes() for song in result.songs] == [b'first', b'second', b'third']


def test_same_file_referenced_twice_archived_once(tmp_path):
    file = make_audio(tmp_path / 'audio', 'loop.wav', b'loop')
    setlist = write_setlist(tmp_path / 'set.yaml', f"""\
songs:
  - name: Intro
    file: {file}
    bpm: 100
  - name: Reprise
    file: {file}
    bpm: 100
""")
    manifest = export_bundle(setlist, tmp_path / 'set.zip')
    assert manifest == ['loop.wav', 'loop.wav']
    with zipfile.ZipFile(tmp_path / 'set.zip') as archive:
        assert archive.namelist().count('loop.wav') == 1


def test_missing_audio_file_names_the_song(tmp_path):
    setlist = write_setlist(tmp_path / 'set.yaml',
                            'songs:\n  - name: Ghost\n    file: gone.wav\n    bpm: 100\n')
    with pytest.raises(BundleError, match=r'song 1 \(Ghost\).*does not exist'):
        export_bundle(setlist, tmp_path / 'set.zip')
    assert not (tmp_path / 'set.zip').exists()
    assert not (tmp_path / 'set.zip.tmp').exists()


def test_empty_or_invalid_setlists_rejected(tmp_path):
    empty = write_setlist(tmp_path / 'empty.yaml', 'title: none\n')
    with pytest.raises(BundleError, match='songs must be a nonempty list'):
        export_bundle(empty, tmp_path / 'out.zip')
    strange = write_setlist(tmp_path / 'strange.yaml', 'title: x\nbogus: 1\nsongs: []\n')
    with pytest.raises(BundleError, match='unknown fields'):
        export_bundle(strange, tmp_path / 'out.zip')


def test_comments_and_mid_edit_rows_survive(tmp_path):
    """Hand-written comments travel; a row without BPM bundles instead of erroring."""
    file = make_audio(tmp_path / 'audio', 'song.wav')
    setlist = write_setlist(tmp_path / 'set.yaml', f"""\
title: "WIP show"
# rehearsal notes live here
songs:
  - name: Song  # count-in of 4
    file: {file}
""")
    export_bundle(setlist, tmp_path / 'set.zip')
    stage = extract(tmp_path / 'set.zip', tmp_path / 'stage')
    text = (stage / 'set.yaml').read_text(encoding='utf-8')
    assert '# rehearsal notes live here' in text
    assert '# count-in of 4' in text
    assert 'audio_root: .' in text
    from showsync.document import Document
    document = Document.load(stage / 'set.yaml', probe=lambda _: 60)
    assert document.rows[0].file == stage / 'song.wav'
    assert document.rows[0].problem() == 'BPM not set'


def test_cli_export(tmp_path, capsys):
    from showsync.cli import main
    file = make_audio(tmp_path / 'audio', 'song.wav')
    setlist = write_setlist(tmp_path / 'set.yaml',
                            f'songs:\n  - name: Song\n    file: {file}\n    bpm: 120\n')
    out = tmp_path / 'set.zip'
    assert main([str(setlist), '--export-bundle', str(out)]) == 0
    assert '1 songs' in capsys.readouterr().out
    assert zipfile.ZipFile(out).namelist() == ['set.yaml', 'song.wav']
    assert main([str(tmp_path / 'missing.yaml'), '--export-bundle', str(out)]) == 1
