"""Show bundles must reproduce a set on another machine from the zip alone."""
from pathlib import Path
import zipfile

import pytest

from showsync.bundle import BundleError, export_bundle, import_bundle
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


def test_referenced_midi_files_travel_in_the_bundle(tmp_path):
    audio = make_audio(tmp_path / 'audio', 'opener.wav', b'audio-bytes')
    midi = tmp_path / 'audio' / 'opener.mid'
    midi.write_bytes(b'MThd-fake')
    setlist = write_setlist(tmp_path / 'show.yaml', f"""\
songs:
  - name: Opener
    file: {audio}
    bpm: 112
    midi: {midi}
""")
    bundle = tmp_path / 'show.zip'
    export_bundle(setlist, bundle)
    home = extract(bundle, tmp_path / 'other-machine')
    reloaded = load_setlist(home / 'show.yaml', duration_probe=lambda _: 60)
    assert reloaded.songs[0].midi == (home / 'opener.mid').resolve()
    assert reloaded.songs[0].midi.read_bytes() == b'MThd-fake'


def test_missing_midi_file_warns_but_never_gates_export(tmp_path, caplog):
    audio = make_audio(tmp_path / 'audio', 'opener.wav', b'audio-bytes')
    setlist = write_setlist(tmp_path / 'show.yaml', f"""\
songs:
  - name: Opener
    file: {audio}
    bpm: 112
    midi: {tmp_path / 'audio' / 'gone.mid'}
""")
    bundle = tmp_path / 'show.zip'
    with caplog.at_level('WARNING'):
        manifest = export_bundle(setlist, bundle)
    assert manifest == ['opener.wav']
    assert 'gone.mid' in caplog.text
    with zipfile.ZipFile(bundle) as archive:
        assert sorted(archive.namelist()) == ['opener.wav', 'show.yaml']

def make_bundle(tmp_path, name='show'):
    """Export a two-song set and return its zip path."""
    first = make_audio(tmp_path / 'src', 'opener.wav', b'opener-bytes')
    second = make_audio(tmp_path / 'src', 'closer.mp3', b'closer-bytes')
    setlist = write_setlist(tmp_path / f'{name}.yaml', f"""\
title: "Fall tour"
songs:
  - name: Opener
    file: {first}
    bpm: 112
  - name: Closer
    file: {second}
    bpm: 90
""")
    zip_path = tmp_path / f'{name}.zip'
    export_bundle(setlist, zip_path)
    return zip_path


def test_import_round_trips_an_exported_bundle(tmp_path):
    """export -> import -> load reproduces the set; default dest is zip stem."""
    zip_path = make_bundle(tmp_path)
    setlist = import_bundle(zip_path)
    assert setlist == tmp_path / 'show' / 'show.yaml'
    result = load_setlist(setlist, duration_probe=lambda _: 300)
    assert result.title == 'Fall tour'
    assert [song.file.read_bytes() for song in result.songs] == [b'opener-bytes', b'closer-bytes']
    assert [song.bpm for song in result.songs] == [112, 90]


def test_import_into_explicit_destination(tmp_path):
    zip_path = make_bundle(tmp_path)
    setlist = import_bundle(zip_path, tmp_path / 'landing' / 'here')
    assert setlist == tmp_path / 'landing' / 'here' / 'show.yaml'
    assert setlist.is_file()


def test_import_rejects_zip_slip_members(tmp_path):
    """Absolute, drive-lettered, backslashed and ..-escaping members all refuse."""
    for evil in ('/etc/evil.wav', 'C:\\evil.wav', 'a\\..\\evil.wav', '../evil.wav', 'ok/../../evil.wav'):
        bad = tmp_path / 'bad.zip'
        with zipfile.ZipFile(bad, 'w') as archive:
            archive.writestr('set.yaml', 'songs: []\n')
            archive.writestr(evil, b'payload')
        dest = tmp_path / 'dest'
        with pytest.raises(BundleError, match='unsafe path'):
            import_bundle(bad, dest)
        assert not dest.exists()
    assert not (tmp_path / 'evil.wav').exists()


def test_import_never_clobbers_occupied_destination(tmp_path):
    zip_path = make_bundle(tmp_path)
    first = import_bundle(zip_path, tmp_path / 'dest')
    (first.parent / 'precious.txt').write_text('mine')
    second = import_bundle(zip_path, tmp_path / 'dest')
    assert second == tmp_path / 'dest-2' / 'show.yaml'
    assert (first.parent / 'precious.txt').read_text() == 'mine'
    third = import_bundle(zip_path, tmp_path / 'dest')
    assert third == tmp_path / 'dest-3' / 'show.yaml'


def test_import_uses_existing_empty_destination(tmp_path):
    zip_path = make_bundle(tmp_path)
    (tmp_path / 'empty').mkdir()
    setlist = import_bundle(zip_path, tmp_path / 'empty')
    assert setlist == tmp_path / 'empty' / 'show.yaml'


def test_import_rejects_non_bundle_zips(tmp_path):
    no_setlist = tmp_path / 'plain.zip'
    with zipfile.ZipFile(no_setlist, 'w') as archive:
        archive.writestr('song.wav', b'data')
    with pytest.raises(BundleError, match='not a show bundle.*found 0'):
        import_bundle(no_setlist, tmp_path / 'a')
    two = tmp_path / 'two.zip'
    with zipfile.ZipFile(two, 'w') as archive:
        archive.writestr('one.yaml', 'songs: []\n')
        archive.writestr('two.yml', 'songs: []\n')
    with pytest.raises(BundleError, match='not a show bundle.*found 2'):
        import_bundle(two, tmp_path / 'b')
    assert not (tmp_path / 'a').exists() and not (tmp_path / 'b').exists()
    with pytest.raises(BundleError, match='File is not a zip file|BadZipFile'):
        import_bundle(write_setlist(tmp_path / 'not.zip', 'nope'), tmp_path / 'c')


def test_cli_import(tmp_path, capsys):
    from showsync.cli import main
    zip_path = make_bundle(tmp_path)
    assert main(['--import-bundle', str(zip_path)]) == 0
    assert str(tmp_path / 'show' / 'show.yaml') in capsys.readouterr().out
    assert (tmp_path / 'show' / 'show.yaml').is_file()
    dest = tmp_path / 'elsewhere'
    assert main(['--import-bundle', str(zip_path), str(dest)]) == 0
    assert (dest / 'show.yaml').is_file()
    assert main(['--import-bundle', str(tmp_path / 'missing.zip')]) == 1
    with pytest.raises(SystemExit):
        main(['--import-bundle', str(zip_path), str(dest), 'extra'])
    with pytest.raises(SystemExit):
        main([str(tmp_path / 'show.yaml'), '--import-bundle', str(zip_path)])


def make_keyframes(tmp_path, name='rig', mapping=None, files=()):
    """Build a Keyframes app folder: images/ pool + mapping.json manifest."""
    import json
    folder = tmp_path / name
    (folder / 'images').mkdir(parents=True)
    for filename in files:
        (folder / 'images' / filename).write_bytes(b'media:' + filename.encode())
    if mapping is not None:
        (folder / 'mapping.json').write_text(json.dumps(mapping), encoding='utf-8')
    return folder


def test_keyframes_export_packs_only_mapped_media(tmp_path):
    """Mapped files travel under keyframes/; the unmapped pool stays home."""
    import json
    rig = make_keyframes(tmp_path, mapping={'60': 'kick.png', '62': 'clip.mp4'},
                         files=('kick.png', 'clip.mp4', 'dormant.png'))
    first = make_audio(tmp_path / 'src', 'song.wav')
    setlist = write_setlist(tmp_path / 'set.yaml',
                            f'songs:\n  - name: Song\n    file: {first}\n    bpm: 120\n')
    export_bundle(setlist, tmp_path / 'set.zip', keyframes_dir=rig)
    with zipfile.ZipFile(tmp_path / 'set.zip') as archive:
        assert sorted(archive.namelist()) == [
            'keyframes/images/clip.mp4', 'keyframes/images/kick.png',
            'keyframes/mapping.json', 'set.yaml', 'song.wav']
        packed = json.loads(archive.read('keyframes/mapping.json'))
    assert packed == {'60': 'kick.png', '62': 'clip.mp4'}


def test_keyframes_export_drops_missing_mapped_files_with_warning(tmp_path, caplog):
    """A mapped-but-absent file warns and is left out, like launch reconcile."""
    import json
    rig = make_keyframes(tmp_path, mapping={'60': 'kick.png', '61': 'gone.png'},
                         files=('kick.png',))
    first = make_audio(tmp_path / 'src', 'song.wav')
    setlist = write_setlist(tmp_path / 'set.yaml',
                            f'songs:\n  - name: Song\n    file: {first}\n    bpm: 120\n')
    with caplog.at_level('WARNING'):
        export_bundle(setlist, tmp_path / 'set.zip', keyframes_dir=rig)
    assert 'gone.png' in caplog.text
    with zipfile.ZipFile(tmp_path / 'set.zip') as archive:
        assert json.loads(archive.read('keyframes/mapping.json')) == {'60': 'kick.png'}


def test_keyframes_export_refuses_bad_folders(tmp_path):
    first = make_audio(tmp_path / 'src', 'song.wav')
    setlist = write_setlist(tmp_path / 'set.yaml',
                            f'songs:\n  - name: Song\n    file: {first}\n    bpm: 120\n')
    no_manifest = make_keyframes(tmp_path, name='bare', files=('kick.png',))
    with pytest.raises(BundleError, match='no mapping.json'):
        export_bundle(setlist, tmp_path / 'set.zip', keyframes_dir=no_manifest)
    empty = make_keyframes(tmp_path, name='empty', mapping={'60': 'gone.png'})
    with pytest.raises(BundleError, match='nothing to pack'):
        export_bundle(setlist, tmp_path / 'set.zip', keyframes_dir=empty)
    evil = make_keyframes(tmp_path, name='evil', mapping={'60': '../escape.png'})
    with pytest.raises(BundleError, match='unsafe media name'):
        export_bundle(setlist, tmp_path / 'set.zip', keyframes_dir=evil)
    assert not (tmp_path / 'set.zip').exists()


def test_keyframes_export_accepts_mapping_json_path(tmp_path):
    rig = make_keyframes(tmp_path, mapping={'60': 'kick.png'}, files=('kick.png',))
    first = make_audio(tmp_path / 'src', 'song.wav')
    setlist = write_setlist(tmp_path / 'set.yaml',
                            f'songs:\n  - name: Song\n    file: {first}\n    bpm: 120\n')
    export_bundle(setlist, tmp_path / 'set.zip', keyframes_dir=rig / 'mapping.json')
    with zipfile.ZipFile(tmp_path / 'set.zip') as archive:
        assert 'keyframes/images/kick.png' in archive.namelist()


def test_keyframes_round_trip_installs_the_set(tmp_path):
    """Import with a target dir restores media + manifest, mapping written last."""
    import json
    rig = make_keyframes(tmp_path, mapping={'60': 'kick.png', '62': 'clip.mp4'},
                         files=('kick.png', 'clip.mp4', 'dormant.png'))
    zip_path = make_bundle(tmp_path)
    bundle = tmp_path / 'full.zip'
    export_bundle(tmp_path / 'show.yaml', bundle, keyframes_dir=rig)
    target = make_keyframes(tmp_path, name='other-rig', mapping={'40': 'old.png'},
                            files=('old.png',))
    setlist = import_bundle(bundle, tmp_path / 'landed', keyframes_dir=target)
    assert setlist.is_file()
    # The show folder keeps its own copy of the set, like any bundle content.
    assert (setlist.parent / 'keyframes' / 'images' / 'kick.png').is_file()
    installed = json.loads((target / 'mapping.json').read_text())
    assert installed == {'60': 'kick.png', '62': 'clip.mp4'}
    assert (target / 'images' / 'kick.png').read_bytes() == b'media:kick.png'
    assert (target / 'images' / 'clip.mp4').read_bytes() == b'media:clip.mp4'
    # The old manifest survives one undo deep; old media is never deleted.
    assert json.loads((target / 'mapping.json.bak').read_text()) == {'40': 'old.png'}
    assert (target / 'images' / 'old.png').is_file()
    # Manifest newer than every installed file, so Keyframes' launch reconcile
    # keeps these note assignments instead of reseeding "new" media.
    manifest_mtime = (target / 'mapping.json').stat().st_mtime
    for media in (target / 'images').iterdir():
        assert media.stat().st_mtime <= manifest_mtime
    assert zip_path.exists()  # unrelated v1 bundle untouched


def test_keyframes_install_into_fresh_folder(tmp_path):
    import json
    rig = make_keyframes(tmp_path, mapping={'60': 'kick.png'}, files=('kick.png',))
    make_audio(tmp_path / 'src', 'song.wav')
    setlist = write_setlist(tmp_path / 'set.yaml',
                            f"songs:\n  - name: Song\n    file: {tmp_path / 'src' / 'song.wav'}\n    bpm: 120\n")
    bundle = tmp_path / 'set.zip'
    export_bundle(setlist, bundle, keyframes_dir=rig)
    target = tmp_path / 'brand-new'
    import_bundle(bundle, tmp_path / 'landed', keyframes_dir=target)
    assert json.loads((target / 'mapping.json').read_text()) == {'60': 'kick.png'}
    assert not (target / 'mapping.json.bak').exists()


def test_import_refuses_keyframes_request_on_v1_bundle(tmp_path):
    """Asking to install keyframes from a bundle that has none fails up front."""
    zip_path = make_bundle(tmp_path)
    target = tmp_path / 'rig'
    with pytest.raises(BundleError, match='no Keyframes set'):
        import_bundle(zip_path, tmp_path / 'landed', keyframes_dir=target)
    assert not (tmp_path / 'landed').exists()
    assert not target.exists()


def test_v2_bundle_imports_without_keyframes_flag(tmp_path):
    """A keyframes-carrying bundle still imports as a plain show (set travels inert)."""
    rig = make_keyframes(tmp_path, mapping={'60': 'kick.png'}, files=('kick.png',))
    make_audio(tmp_path / 'src', 'song.wav')
    setlist = write_setlist(tmp_path / 'set.yaml',
                            f"songs:\n  - name: Song\n    file: {tmp_path / 'src' / 'song.wav'}\n    bpm: 120\n")
    bundle = tmp_path / 'set.zip'
    export_bundle(setlist, bundle, keyframes_dir=rig)
    extracted = import_bundle(bundle, tmp_path / 'landed')
    assert extracted.is_file()
    assert (extracted.parent / 'keyframes' / 'mapping.json').is_file()


def test_cli_keyframes_flag(tmp_path, capsys):
    from showsync.cli import main
    rig = make_keyframes(tmp_path, mapping={'60': 'kick.png'}, files=('kick.png',))
    file = make_audio(tmp_path / 'audio', 'song.wav')
    setlist = write_setlist(tmp_path / 'set.yaml',
                            f'songs:\n  - name: Song\n    file: {file}\n    bpm: 120\n')
    out = tmp_path / 'set.zip'
    assert main([str(setlist), '--export-bundle', str(out), '--keyframes', str(rig)]) == 0
    assert 'keyframes set' in capsys.readouterr().out
    assert 'keyframes/images/kick.png' in zipfile.ZipFile(out).namelist()
    target = tmp_path / 'new-rig'
    assert main(['--import-bundle', str(out), str(tmp_path / 'landed'),
                 '--keyframes', str(target)]) == 0
    assert str(target) in capsys.readouterr().out
    assert (target / 'mapping.json').is_file()
    with pytest.raises(SystemExit):
        main([str(setlist), '--keyframes', str(rig)])


def test_extended_midi_bundle_keeps_options_and_rewrites_file(tmp_path):
    audio = make_audio(tmp_path / 'media', 'song.wav', b'audio')
    midi = tmp_path / 'media' / 'song.mid'
    midi.write_bytes(b'MIDI')
    path = write_setlist(tmp_path / 'show.yaml', f'''songs:
  - name: Song
    file: {audio}
    bpm: 120
    midi: {{file: {midi}, loop: true, bars: 2, port: 'Synth'}} # loop notes
''')
    bundle = tmp_path / 'show.zip'
    export_bundle(path, bundle)
    home = extract(bundle, tmp_path / 'imported')
    song = load_setlist(home / 'show.yaml').songs[0]
    assert song.midi == home / 'song.mid'
    assert song.midi.read_bytes() == b'MIDI'
    assert (song.midi_loop, song.midi_beats, song.midi_port) == (True, 8, 'Synth')
    assert '# loop notes' in (home / 'show.yaml').read_text()
