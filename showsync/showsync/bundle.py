"""Portable show bundles: one zip holding a setlist and every audio file it plays.

Setlists reference audio by absolute or setlist-relative paths, so a naive zip
of the YAML cannot reproduce the show on another machine. Export rewrites the
YAML with `audio_root: .` and per-song archive-relative file names, then packs
each referenced audio file beside it. Machine state (device choices, clock
offset) lives in state.json and deliberately stays home. Import needs no code:
unzip anywhere, open the YAML, and the relative paths resolve.
"""
import io
import logging
import os
from pathlib import Path
import zipfile

from .setlist import mapping, string

LOG = logging.getLogger(__name__)
SIZE_WARNING_BYTES = 1024 ** 3


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
        size = sum(source.stat().st_size for source in archived)
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
            os.replace(replacement, zip_path)
        finally:
            replacement.unlink(missing_ok=True)
        return manifest
    except (OSError, ValueError, YAMLError) as exc:
        raise BundleError(f"{context}: {exc}") from exc


def _free_name(name, taken):
    """`name`, or stem-2.ext (-3, …) when a different source already claimed it."""
    stem, suffix = Path(name).stem, Path(name).suffix
    candidate, n = name, 1
    while candidate.casefold() in taken:
        n += 1
        candidate = f"{stem}-{n}{suffix}"
    return candidate
