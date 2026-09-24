"""Editable setlist: lenient load, per-row problems, comment-preserving save.

The Document is what the GUI edits; the frozen Setlist the engines consume is
built from it only once every row is playable. Unlike `load_setlist`, a
Document tolerates rows with no BPM yet and missing audio files — those rows
carry a `problem()` that gates playback instead of refusing to open the set.
"""
from dataclasses import dataclass
import io
import os
from pathlib import Path

from .setlist import (SUFFIXES, VIDEO_SUFFIXES, Setlist, SetlistError, Song, mapping, number,
                      parse_song, position, song_context, string, timing_metadata)
from .tempomap import TempoEvent


def probe_duration(path):
    from .audio import Decoder
    with Decoder.open(path) as decoder:
        return decoder.duration


def _editor():
    from ruamel.yaml import YAML
    editor = YAML()
    editor.preserve_quotes = True
    editor.indent(mapping=2, sequence=4, offset=2)
    editor.width = 4096
    return editor


@dataclass
class Row:
    name: str
    file: Path
    bpm: float | None
    gap: float = 0.0
    tempo: tuple = ()
    offset: float = 0.0
    midi: Path | None = None
    duration: float | None = None
    file_error: str | None = None
    source_index: int | None = None  # position in the songs list on disk; None = unsaved

    offset_explicit: bool = False  # editor intent, including an explicitly entered zero
    bpm_estimated: bool = False
    timing_review: str = ''
    video: Path | None = None
    mute: bool = False
    trim: float = 0.0

    def problem(self):
        if self.file_error:
            return self.file_error
        if self.timing_review:
            return 'Replacement audio needs timing review'
        if self.bpm is None:
            return "BPM not set"
        if self.trim and self.duration is not None and self.trim >= self.duration:
            return f'Trim must be under the file length ({self.duration:g}s)'
        try:
            duration = None if self.duration is None else self.duration - self.trim
            self.song().tempo_map(duration)
        except ValueError as exc:
            return str(exc)
        return None

    def song(self):
        return Song(self.name, self.file, self.bpm, self.gap, self.tempo, self.offset,
                    self.midi, self.video, self.mute, self.trim)

    @property
    def custom_tempo(self):
        """Hand-authored map the simple controls can't express (jumps, 2+ events)."""
        return bool(self.tempo) and (len(self.tempo) > 1 or not self.tempo[0].ramp)

    @property
    def ramp(self):
        """The single editable ramp event, or None."""
        return self.tempo[0] if self.tempo and not self.custom_tempo else None


class Document:
    def __init__(self, path=None, title=None, rows=(), source=None):
        self.path = Path(path).expanduser().resolve() if path else None
        self.title = title
        self.rows = list(rows)
        self._source = source  # ruamel data of the file on disk; None until first save

    @property
    def display_title(self):
        return self.title or (self.path.stem if self.path else "New set")

    @classmethod
    def load(cls, path, *, probe=probe_duration):
        from ruamel.yaml import YAMLError
        path = Path(path).expanduser().resolve()
        context = str(path)
        try:
            data = _editor().load(path.read_text(encoding="utf-8"))
            data = mapping(data if data is not None else {},
                           {"title", "audio_root", "songs"}, "setlist")
            title = string(data.get("title", path.stem), "title")
            root = Path(string(data.get("audio_root", "."), "audio_root")).expanduser()
            root = (path.parent / root).resolve()
            raw = data.get("songs")
            if raw is not None and not isinstance(raw, list):
                raise ValueError("songs must be a list")
            rows = []
            for i, item in enumerate(raw or []):
                context = song_context(path, i, item)
                fields = parse_song(item, root, require_bpm=False)
                metadata = timing_metadata(item)
                row = Row(**fields, source_index=i,
                          offset_explicit="offset" in item and not metadata.get('offset_estimated'),
                          bpm_estimated=metadata.get('bpm_estimated', False),
                          timing_review=metadata.get('timing_review', ''))
                if not row.file.is_file():
                    row.file_error = "audio file not found"
                else:
                    try:
                        if row.mute and probe is probe_duration:
                            # Full-file duration: the editor's file-time fields
                            # (offset, tempo, trim itself) validate against it.
                            from .audio import Decoder
                            with Decoder.open(row.file, mute=True) as decoder:
                                row.duration = decoder.duration
                        else:
                            row.duration = probe(row.file)
                    except Exception as exc:
                        row.file_error = f"cannot decode: {exc}"
                if row.video and not row.video.is_file():
                    row.file_error = f"video file not found: {row.video}"
                rows.append(row)
            return cls(path, title, rows, source=data)
        except (OSError, ValueError, YAMLError) as exc:
            raise SetlistError(f"{context}: {exc}") from exc

    def add_files(self, paths, *, probe=probe_duration):
        """Append rows for the decodable audio files; report the rejects."""
        added, rejected = [], []
        for item in paths:
            item = Path(item).expanduser()
            if item.suffix.lower() not in SUFFIXES:
                rejected.append((item, "unsupported file type"))
                continue
            if not item.is_file():
                rejected.append((item, "not a file"))
                continue
            item = item.resolve()
            try:
                duration = probe(item)
            except Exception as exc:
                rejected.append((item, f"cannot decode: {exc}"))
                continue
            row = Row(name=item.stem, file=item, bpm=None, duration=duration)
            self.rows.append(row)
            added.append(row)
        return added, rejected

    def replace_file(self, row, path, *, probe=probe_duration):
        """Validate before changing the existing row or its source mapping."""
        candidate = Document()
        added, rejected = candidate.add_files([path], probe=probe)
        if rejected:
            raise ValueError(rejected[0][1])
        replacement = added[0]
        if row.mute and replacement.file.suffix.lower() in VIDEO_SUFFIXES and probe is probe_duration:
            from .audio import Decoder
            with Decoder.open(replacement.file, mute=True) as decoder:
                replacement.duration = decoder.duration
        if row.name == row.file.stem:
            row.name = replacement.name
        row.file, row.duration, row.file_error = replacement.file, replacement.duration, None
        if row.file.suffix.lower() not in VIDEO_SUFFIXES:
            row.mute = False
        # Keep old values (and their YAML comments) while the persisted gate
        # blocks playback. The new fit replaces only unconfirmed values.
        row.timing_review = 'pending'

    def first_problem(self):
        """(row, message) blocking playback, or None when the set can start."""
        if not self.rows:
            return None, "the set has no songs"
        for row in self.rows:
            message = row.problem()
            if message:
                return row, message
        return None

    def setlist(self):
        blocked = self.first_problem()
        if blocked:
            row, message = blocked
            raise SetlistError(f"{row.name}: {message}" if row else message)
        return Setlist(self.display_title, tuple(row.song() for row in self.rows))

    def default_save_directory(self):
        return self.rows[0].file.parent if self.rows else Path.home()

    def save(self):
        """Write through ruamel so hand-written comments and styles survive.

        Rows keep their `source_index` into the songs list on disk: existing
        entries travel whole (gap/tempo/comments untouched, fields assigned
        only when changed so an unchanged set is byte-stable), removed entries
        are dropped, new rows become fresh mappings. Atomic replace, as in
        save_song_order.
        """
        from ruamel.yaml import YAMLError
        from ruamel.yaml.comments import CommentedMap
        if self.path is None:
            raise SetlistError("no file chosen for this set")
        try:
            editor = _editor()
            data = self._source if isinstance(self._source, dict) else CommentedMap()
            if "title" not in data:
                data["title"] = self.display_title
            root = Path(str(data.get("audio_root", "."))).expanduser()
            root = (self.path.parent / root).resolve()
            original = list(data.get("songs") or [])
            entries = []
            for row in self.rows:
                if row.source_index is None:
                    entry = CommentedMap()
                    entry["name"] = row.name
                    entry["file"] = self._portable(row.file, root)
                else:
                    entry = original[row.source_index]
                    if str(entry.get("name")) != row.name:
                        entry["name"] = row.name
                    current_file = (root / str(entry['file'])).resolve()
                    if current_file != row.file:
                        entry['file'] = self._portable(row.file, root)
                self._set_number(entry, "bpm", row.bpm)
                if row.video is None:
                    entry.pop('video', None)
                elif ('video' not in entry or
                      (root / str(entry['video'])).resolve() != row.video):
                    entry['video'] = self._portable(row.video, root)
                if row.mute or 'mute' in entry:
                    entry['mute'] = row.mute
                self._set_number(entry, "offset", row.offset if row.offset_explicit else row.offset or None)
                self._set_number(entry, "trim", row.trim or None)
                self._sync_tempo(entry, row.tempo)
                metadata = dict(bpm_estimated=row.bpm_estimated,
                                offset_estimated=bool(row.offset and not row.offset_explicit),
                                timing_review=row.timing_review)
                if any(metadata.values()) or 'editor' in entry:
                    saved_metadata = entry.setdefault('editor', CommentedMap())
                    for key, value in metadata.items():
                        if value or key in saved_metadata:
                            saved_metadata[key] = value
                entries.append(entry)
            data["songs"] = entries
            buffer = io.StringIO()
            editor.dump(data, buffer)
            replacement = self.path.with_name(self.path.name + ".tmp")
            replacement.write_text(buffer.getvalue(), encoding="utf-8")
            os.replace(replacement, self.path)
        except (OSError, ValueError, YAMLError) as exc:
            raise SetlistError(f"{self.path}: {exc}") from exc
        self._source = data
        for i, row in enumerate(self.rows):
            row.source_index = i

    @staticmethod
    def _portable(file, root):
        try:
            return file.relative_to(root).as_posix()
        except ValueError:
            return str(file)

    @classmethod
    def _sync_tempo(cls, entry, events):
        """Rewrite the entry's tempo list only when the editor changed it.

        Hand-authored maps (m:ss positions, comments, extra events) reparse
        equal to the row's untouched events, so they pass through verbatim.
        """
        from ruamel.yaml.comments import CommentedMap, CommentedSeq
        raw = entry.get("tempo")
        try:
            current = tuple(TempoEvent(position(item.get("at")),
                                       number(item.get("bpm"), "bpm", positive=True),
                                       number(item.get("ramp", 0), "ramp"))
                            for item in (raw if isinstance(raw, list) else ()))
        except (AttributeError, ValueError):
            current = None
        if current == tuple(events):
            return
        if not events:
            del entry["tempo"]
            return
        replacement = CommentedSeq()
        for event in events:
            item = CommentedMap()
            for key, value in (("at", event.at), ("bpm", event.bpm), ("ramp", event.ramp)):
                item[key] = int(value) if float(value).is_integer() else float(value)
            replacement.append(item)
        entry["tempo"] = replacement

    @staticmethod
    def _set_number(entry, key, value):
        if value is None:
            if key in entry:
                del entry[key]
            return
        current = entry.get(key)
        unchanged = (isinstance(current, (int, float)) and not isinstance(current, bool)
                     and float(current) == value)
        if not unchanged:
            entry[key] = int(value) if float(value).is_integer() else float(value)
