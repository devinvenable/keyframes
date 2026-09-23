"""Portable show bundles: one zip holding a setlist and every audio file it plays.

Setlists reference audio by absolute or setlist-relative paths, so a naive zip
of the YAML cannot reproduce the show on another machine. Export rewrites the
YAML with `audio_root: .` and per-song archive-relative file names, then packs
each referenced audio file beside it. Machine state (device choices, clock
offset) lives in state.json and deliberately stays home. Import unzips into a
fresh folder (never clobbering an existing show) and hands back the setlist
path; the relative paths inside resolve as written.
"""
import io
import logging
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import zipfile

from .setlist import mapping, string

LOG = logging.getLogger(__name__)


class BundleError(ValueError):
    pass


def export_bundle(setlist_path, zip_path):
    """Write the bundle zip; returns the archived audio names in song order.

    The YAML travels through ruamel round-trip mode, so hand-written comments
    and styles arrive on the other machine intact. Rows are otherwise kept as
    loose as the editor keeps them (no BPM yet is fine) — only the audio files
    must exist, because they are the bundle's payload.
    """
    from ruamel.yaml import YAML, YAMLError
    setlist_path = Path(setlist_path).expanduser().resolve()
    zip_path = Path(zip_path).expanduser().resolve()
    context = str(setlist_path)
    try:
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
            # A song's MIDI file is show content like its audio (decision
            # update to I22), but it never gates playback, so it never gates
            # export either: pack it when present, warn and travel the
            # reference untouched when not.
            if row.get("midi") is not None:
                midi = (root / string(row.get("midi"), "midi")).resolve()
                if midi.is_file():
                    name = archived.get(midi)
                    if name is None:
                        name = _free_name(midi.name, taken)
                        taken.add(name.casefold())
                        archived[midi] = name
                    row["midi"] = name
                else:
                    LOG.warning('%s: midi file does not exist: %s — bundled without it',
                                context, midi)
        context = str(setlist_path)
        data["audio_root"] = "."
        buffer = io.StringIO()
        editor.dump(data, buffer)
        replacement = zip_path.with_name(zip_path.name + ".tmp")
        try:
            with zipfile.ZipFile(replacement, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(setlist_path.name, buffer.getvalue())
                for source, name in archived.items():
                    archive.write(source, name)
            os.replace(replacement, zip_path)
        finally:
            replacement.unlink(missing_ok=True)
        return manifest
    except (OSError, ValueError, YAMLError) as exc:
        raise BundleError(f"{context}: {exc}") from exc


def import_bundle(zip_path, dest_dir=None):
    """Unpack a show bundle zip; returns the extracted setlist path.

    A show bundle holds exactly one top-level setlist YAML (the shape
    export_bundle writes); anything else is rejected before a byte lands on
    disk. Member paths are validated against zip-slip — absolute paths,
    drive letters, backslashes and `..` segments all refuse the import.
    Existing show folders are never overwritten: when dest_dir already holds
    files, extraction lands in a fresh sibling (name-2, name-3, …).
    dest_dir defaults to a folder named after the zip, beside it.
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
            dest = _free_dir(dest_dir)
            dest.mkdir(parents=True, exist_ok=True)
            for name in names:
                target = dest / PurePosixPath(name)
                if not target.resolve().is_relative_to(dest):
                    raise ValueError(f'unsafe path in zip: {name!r}')
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as member, open(target, 'wb') as out:
                    shutil.copyfileobj(member, out)
            return dest / setlists[0]
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        raise BundleError(f'{zip_path}: {exc}') from exc


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
