"""Strict, contextual validation around safely loaded, hand-edited YAML."""

from dataclasses import dataclass
import io
import math
import os
from pathlib import Path
import re

import yaml

from .tempomap import TempoEvent, TempoMap


class SetlistError(ValueError):
    pass


@dataclass(frozen=True)
class Song:
    name: str
    file: Path
    bpm: float
    gap: float = 0.0
    tempo: tuple[TempoEvent, ...] = ()

    def tempo_map(self, duration=None):
        return TempoMap(self.bpm, self.tempo, duration)


@dataclass(frozen=True)
class Setlist:
    title: str
    songs: tuple[Song, ...]


def number(value, field, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a number")
    value = float(value)
    if not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError(f"{field} must be finite and {'positive' if positive else 'nonnegative'}")
    return value


def position(value):
    if isinstance(value, str):
        if re.fullmatch(r"\d+:[0-5]\d(?:\.\d+)?", value):
            minutes, seconds = value.split(":")
            return 60 * int(minutes) + float(seconds)
        if re.fullmatch(r"\d+(?:\.\d+)?", value):
            return number(float(value), "at")
        raise ValueError("at must be seconds or m:ss.sss")
    return number(value, "at")


def mapping(value, allowed, field):
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a mapping")
    unknown = value.keys() - allowed
    if unknown:
        raise ValueError(f"{field}: unknown fields {', '.join(map(str, unknown))}")
    return value


def string(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")
    return value


def load_setlist(path, *, check_files=True, duration_probe=None):
    """Validate paths immediately; optionally validate durations with a decoder probe.

    AudioEngine always probes durations before opening the output device. The
    optional injection keeps the config/tempo suites independent of audio codecs.
    """
    path = Path(path).expanduser().resolve()
    context = str(path)
    try:
        data = mapping(yaml.safe_load(path.read_text(encoding="utf-8")),
                       {"title", "audio_root", "songs"}, "setlist")
        title = string(data.get("title", path.stem), "title")
        root = Path(string(data.get("audio_root", "."), "audio_root")).expanduser()
        root = (path.parent / root).resolve()
        rows = data.get("songs")
        if not isinstance(rows, list) or not rows:
            raise ValueError("songs must be a nonempty list")
        songs = []
        for i, row in enumerate(rows):
            context = f"{path}: song {i + 1}"
            row = mapping(row, {"name", "file", "bpm", "gap", "tempo"}, "song")
            name = string(row.get("name"), "name")
            context += f" ({name})"
            file = (root / string(row.get("file"), "file")).resolve()
            if file.suffix.lower() not in {".wav", ".aif", ".aiff", ".flac", ".mp3", ".m4a"}:
                raise ValueError("file must be WAV, AIFF, FLAC, MP3, or M4A")
            if check_files and not file.is_file():
                raise ValueError(f"file does not exist: {file}")
            bpm = number(row.get("bpm"), "bpm", positive=True)
            gap = number(row.get("gap", 0), "gap")
            raw_events = row.get("tempo", [])
            if not isinstance(raw_events, list):
                raise ValueError("tempo must be a list")
            events = []
            for j, raw in enumerate(raw_events):
                try:
                    raw = mapping(raw, {"at", "bpm", "ramp"}, "event")
                    events.append(TempoEvent(position(raw.get("at")),
                                             number(raw.get("bpm"), "bpm", positive=True),
                                             number(raw.get("ramp", 0), "ramp")))
                except ValueError as exc:
                    raise ValueError(f"tempo[{j}].{exc}") from exc
            song = Song(name, file, bpm, gap, tuple(events))
            song.tempo_map(duration_probe(file) if duration_probe else None)
            songs.append(song)
        return Setlist(title, tuple(songs))
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise SetlistError(f"{context}: {exc}") from exc


def save_song_order(path, order):
    """Rewrite the setlist file with its songs permuted into `order`.

    `order` maps new positions to the file's current song indices. The file is
    hand-edited between rehearsals, so a plain dump is unacceptable: ruamel's
    round-trip mode rewrites it with comments, quotes, and anchors intact
    (byte-stable for an unchanged order; per-song comments travel with their
    song). The replacement is written atomically so a crash mid-save cannot
    truncate the show's setlist.
    """
    from ruamel.yaml import YAML, YAMLError
    path = Path(path).expanduser().resolve()
    try:
        editor = YAML()
        editor.preserve_quotes = True
        editor.indent(mapping=2, sequence=4, offset=2)
        editor.width = 4096
        data = editor.load(path.read_text(encoding="utf-8"))
        songs = data["songs"] if isinstance(data, dict) else None
        if not isinstance(songs, list) or sorted(order) != list(range(len(songs))):
            raise ValueError(f"order must be a permutation of the {len(songs or [])} songs on disk")
        data["songs"] = [songs[i] for i in order]
        buffer = io.StringIO()
        editor.dump(data, buffer)
        replacement = path.with_name(path.name + ".tmp")
        replacement.write_text(buffer.getvalue(), encoding="utf-8")
        os.replace(replacement, path)
    except (OSError, ValueError, YAMLError) as exc:
        raise SetlistError(f"{path}: {exc}") from exc
