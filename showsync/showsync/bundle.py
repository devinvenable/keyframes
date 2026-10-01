"""Portable show bundles: one zip holding a setlist and every audio file it plays.

Setlists reference audio by absolute or setlist-relative paths, so a naive zip
of the YAML cannot reproduce the show on another machine. Export rewrites the
YAML with `audio_root: .` and per-song archive-relative file names, then packs
each referenced audio file beside it. Machine state (device choices, clock
offset) lives in state.json and deliberately stays home. Import unzips into a
fresh folder (never clobbering an existing show) and hands back the setlist
path; the relative paths inside resolve as written.

A bundle can optionally carry a Keyframes set — the sibling app's mapping.json
plus only the media files that manifest actually maps (the images/ pool may
hold dormant unmapped files; those stay home). It travels under a keyframes/
subtree in the zip, and import can install it into a Keyframes app folder.
"""
import io
import json
import logging
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import zipfile

from .setlist import mapping, string

LOG = logging.getLogger(__name__)
SIZE_WARNING_BYTES = 1024 ** 3
KEYFRAMES_DIR = 'keyframes'
KEYFRAMES_MAPPING = f'{KEYFRAMES_DIR}/mapping.json'
KEYFRAMES_IMAGES = f'{KEYFRAMES_DIR}/images'


class BundleError(ValueError):
    pass


class _Keyframes:
    """A Keyframes set ready to pack: manifest JSON text + (name, source) media."""
    def __init__(self, manifest, media):
        self.manifest = manifest
        self.media = media


def _read_keyframes_mapping(path):
    """Read a Keyframes mapping.json: {int note: str filename}, leniently.

    Mirrors Keyframes' own load_mapping(): malformed entries are skipped, not
    fatal — but a missing or non-dict file is an error here, because packing
    was explicitly requested.
    """
    raw = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(raw, dict):
        raise ValueError(f'{path}: mapping.json must hold a JSON object')
    mapping = {}
    for note, filename in raw.items():
        try:
            note_int = int(note)
        except (TypeError, ValueError):
            continue
        if isinstance(filename, str):
            mapping[note_int] = filename
    return mapping


def _collect_keyframes(keyframes_dir):
    """Gather a Keyframes app folder's mapped media for packing.

    Only files mapping.json actually references travel — the images/ pool may
    hold dormant unmapped media, and the mapping contract (sparse, 1:1) makes
    the manifest, not the folder, the set's definition. Entries whose file is
    missing are dropped with a warning, matching Keyframes' own reconcile
    behavior on launch. The packed manifest is rewritten to hold only the
    entries that travel.
    """
    keyframes_dir = Path(keyframes_dir).expanduser().resolve()
    if keyframes_dir.name == 'mapping.json' and keyframes_dir.is_file():
        keyframes_dir = keyframes_dir.parent
    mapping_path = keyframes_dir / 'mapping.json'
    if not mapping_path.is_file():
        raise ValueError(f'not a Keyframes folder (no mapping.json): {keyframes_dir}')
    images_dir = keyframes_dir / 'images'
    mapping = _read_keyframes_mapping(mapping_path)
    packed, media, seen = {}, [], set()
    for note in sorted(mapping):
        name = mapping[note]
        # Mapping names are plain filenames inside images/; anything that
        # could escape the keyframes/images/ subtree on extraction refuses
        # the export rather than travel.
        if ('/' in name or '\\' in name or name in ('.', '..') or not name):
            raise ValueError(f'{mapping_path}: unsafe media name: {name!r}')
        source = images_dir / name
        if not source.is_file():
            LOG.warning('%s: note %d maps missing file %s — left out of the bundle',
                        mapping_path, note, name)
            continue
        packed[str(note)] = name
        if name not in seen:
            seen.add(name)
            media.append((name, source))
    if not packed:
        raise ValueError(f'{mapping_path}: no mapped media files exist — nothing to pack')
    manifest = json.dumps(packed, indent=2) + '\n'
    return _Keyframes(manifest, media)


def export_bundle(setlist_path, zip_path, keyframes_dir=None):
    """Write the bundle zip; returns the archived audio names in song order.

    The YAML travels through ruamel round-trip mode, so hand-written comments
    and styles arrive on the other machine intact. Rows are otherwise kept as
    loose as the editor keeps them (no BPM yet is fine) — only the audio files
    must exist, because they are the bundle's payload.

    keyframes_dir, when given, names a Keyframes app folder (holding
    mapping.json and images/); its mapped media and manifest are packed under
    keyframes/ in the zip.
    """
    from ruamel.yaml import YAML, YAMLError
    setlist_path = Path(setlist_path).expanduser().resolve()
    zip_path = Path(zip_path).expanduser().resolve()
    context = str(setlist_path)
    try:
        keyframes = (_collect_keyframes(keyframes_dir)
                     if keyframes_dir is not None else None)
        editor = YAML()
        editor.preserve_quotes = True
        editor.indent(mapping=2, sequence=4, offset=2)
        editor.width = 4096
        data = editor.load(setlist_path.read_text(encoding="utf-8"))
        data = mapping(data if data is not None else {},
                       {"title", "audio_root", "songs"}, "setlist")
        root = Path(string(data.get("audio_root", "."), "audio_root")).expanduser()
        root = (setlist_path.parent / root).resolve()
        songs = data.get("songs")
        if not isinstance(songs, list) or not songs:
            raise ValueError("songs must be a nonempty list")
        # Casefolded archive names, so the zip extracts on case-insensitive
        # (Windows) filesystems; seeded with the YAML's own slot.
        taken = {setlist_path.name.casefold()}
        archived = {}  # resolved source path -> archive name
        manifest = []
        for i, row in enumerate(songs):
            context = f"{setlist_path}: song {i + 1}"
            if not isinstance(row, dict):
                raise ValueError("song must be a mapping")
            if isinstance(row.get("name"), str) and row["name"].strip():
                context += f" ({row['name']})"
            source = (root / string(row.get("file"), "file")).resolve()
            if not source.is_file():
                raise ValueError(f"file does not exist: {source}")
            name = archived.get(source)
            if name is None:
                name = _free_name(source.name, taken)
                taken.add(name.casefold())
                archived[source] = name
            row["file"] = name
            manifest.append(name)
            if row.get('video') is not None:
                video = (root / string(row['video'], 'video')).resolve()
                if not video.is_file():
                    raise ValueError(f'video file does not exist: {video}')
                name = archived.get(video)
                if name is None:
                    name = _free_name(video.name, taken)
                    taken.add(name.casefold())
                    archived[video] = name
                row['video'] = name
            # A song's MIDI file is show content like its audio (decision
            # update to I22), but it never gates playback, so it never gates
            # export either: pack it when present, warn and travel the
            # reference untouched when not.
            if row.get("midi") is not None:
                midi_options = row['midi']
                reference = midi_options.get('file') if isinstance(midi_options, dict) else midi_options
                midi = (root / string(reference, "midi")).resolve()
                if midi.is_file():
                    name = archived.get(midi)
                    if name is None:
                        name = _free_name(midi.name, taken)
                        taken.add(name.casefold())
                        archived[midi] = name
                    if isinstance(midi_options, dict):
                        midi_options['file'] = name
                    else:
                        row["midi"] = name
                else:
                    LOG.warning('%s: midi file does not exist: %s — bundled without it',
                                context, midi)
        context = str(setlist_path)
        size = sum(source.stat().st_size for source in archived)
        if keyframes is not None:
            size += sum(source.stat().st_size for _, source in keyframes.media)
        if size >= SIZE_WARNING_BYTES:
            LOG.warning('%s: bundle media exceeds 1 GB (%.2f GiB); export will continue',
                        context, size / 1024 ** 3)
        data["audio_root"] = "."
        buffer = io.StringIO()
        editor.dump(data, buffer)
        replacement = zip_path.with_name(zip_path.name + ".tmp")
        try:
            with zipfile.ZipFile(replacement, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(setlist_path.name, buffer.getvalue())
                for source, name in archived.items():
                    archive.write(source, name)
                if keyframes is not None:
                    archive.writestr(KEYFRAMES_MAPPING, keyframes.manifest)
                    for name, source in keyframes.media:
                        archive.write(source, f'{KEYFRAMES_IMAGES}/{name}')
            os.replace(replacement, zip_path)
        finally:
            replacement.unlink(missing_ok=True)
        return manifest
    except (OSError, ValueError, YAMLError) as exc:
        raise BundleError(f"{context}: {exc}") from exc


def import_bundle(zip_path, dest_dir=None, keyframes_dir=None):
    """Unpack a show bundle zip; returns the extracted setlist path.

    A show bundle holds exactly one top-level setlist YAML (the shape
    export_bundle writes); anything else is rejected before a byte lands on
    disk. Member paths are validated against zip-slip — absolute paths,
    drive letters, backslashes and `..` segments all refuse the import.
    Existing show folders are never overwritten: when dest_dir already holds
    files, extraction lands in a fresh sibling (name-2, name-3, …).
    dest_dir defaults to a folder named after the zip, beside it.

    keyframes_dir, when given, additionally installs the bundle's Keyframes
    set (keyframes/ subtree) into that app folder — run while Keyframes is
    closed. Bundles without a Keyframes set refuse the request up front.
    """
    zip_path = Path(zip_path).expanduser().resolve()
    if dest_dir is None:
        dest_dir = zip_path.parent / zip_path.stem
    dest_dir = Path(dest_dir).expanduser().resolve()
    try:
        with zipfile.ZipFile(zip_path) as archive:
            names = [info.filename for info in archive.infolist() if not info.is_dir()]
            for name in names:
                if (not name or name.startswith('/') or '\\' in name or
                        PureWindowsPath(name).drive or
                        '..' in PurePosixPath(name).parts):
                    raise ValueError(f'unsafe path in zip: {name!r}')
            setlists = [name for name in names
                        if '/' not in name and name.lower().endswith(('.yaml', '.yml'))]
            if len(setlists) != 1:
                raise ValueError('not a show bundle: expected exactly one '
                                 f'top-level setlist YAML, found {len(setlists)}')
            if keyframes_dir is not None and KEYFRAMES_MAPPING not in names:
                raise ValueError('bundle holds no Keyframes set '
                                 f'(no {KEYFRAMES_MAPPING})')
            dest = _free_dir(dest_dir)
            dest.mkdir(parents=True, exist_ok=True)
            for name in names:
                target = dest / PurePosixPath(name)
                if not target.resolve().is_relative_to(dest):
                    raise ValueError(f'unsafe path in zip: {name!r}')
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as member, open(target, 'wb') as out:
                    shutil.copyfileobj(member, out)
            if keyframes_dir is not None:
                _install_keyframes(dest / KEYFRAMES_DIR, keyframes_dir)
            return dest / setlists[0]
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        raise BundleError(f'{zip_path}: {exc}') from exc


def _install_keyframes(source_dir, keyframes_dir):
    """Copy an extracted keyframes/ subtree into a Keyframes app folder.

    Media lands first and mapping.json is written last (atomically), so the
    manifest's mtime is newer than every installed file — Keyframes' launch
    reconcile then keeps the installed note assignments instead of treating
    the media as new arrivals to reseed. An existing manifest is kept as
    mapping.json.bak: installing replaces the rig's current set by design,
    but never beyond one undo.
    """
    keyframes_dir = Path(keyframes_dir).expanduser().resolve()
    images_dir = keyframes_dir / 'images'
    images_dir.mkdir(parents=True, exist_ok=True)
    source_images = source_dir / 'images'
    if source_images.is_dir():
        for source in sorted(source_images.iterdir()):
            if source.is_file():
                shutil.copy2(source, images_dir / source.name)
    mapping_path = keyframes_dir / 'mapping.json'
    if mapping_path.is_file():
        shutil.copy2(mapping_path, keyframes_dir / 'mapping.json.bak')
    tmp = keyframes_dir / 'mapping.json.tmp'
    shutil.copy(source_dir / 'mapping.json', tmp)
    os.replace(tmp, mapping_path)


def _free_dir(path):
    """`path` when absent or an empty directory, else sibling path-2 (-3, …)."""
    candidate, n = path, 1
    while candidate.exists() and (not candidate.is_dir() or any(candidate.iterdir())):
        n += 1
        candidate = path.with_name(f'{path.name}-{n}')
    return candidate


def _free_name(name, taken):
    """`name`, or stem-2.ext (-3, …) when a different source already claimed it."""
    stem, suffix = Path(name).stem, Path(name).suffix
    candidate, n = name, 1
    while candidate.casefold() in taken:
        n += 1
        candidate = f"{stem}-{n}{suffix}"
    return candidate
