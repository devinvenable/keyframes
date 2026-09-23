"""GM MIDI files as beat-indexed event lists for the clock thread.

The file's ticks become beats through its own PPQN division; its embedded
tempo metas are deliberately ignored. Beats are beats: the song's tempo map
(the one already driving MIDI clock) decides when each beat sounds, so file
playback follows ramps and stays locked to the audio frame counter for free.
"""
from dataclasses import dataclass
import logging

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class MidiEvent:
    beat: float
    data: tuple  # complete wire message, ready for send_message


def load_midi_events(path):
    """All non-meta events of the file, beat-ordered, as MidiEvent tuples.

    mido's merge keeps the within-tick order tracks wrote (bank select before
    program change survives). Meta events are file structure, not wire traffic;
    everything else — channel voice messages and sysex (GM Reset lives there) —
    is passed through verbatim.
    """
    import mido
    source = mido.MidiFile(path)
    if source.ticks_per_beat <= 0:
        raise ValueError("SMPTE-division MIDI files are not supported")
    events, ticks = [], 0
    for message in mido.merge_tracks(source.tracks):
        ticks += message.time
        if not message.is_meta:
            events.append(MidiEvent(ticks / source.ticks_per_beat, tuple(message.bytes())))
    return tuple(events)


def load_setlist_events(setlist):
    """Per-path event lists for every song that references a MIDI file.

    A missing or unreadable file is a warning, never a gate: the show plays
    without it, exactly as if the key were absent.
    """
    by_path = {}
    for song in setlist.songs:
        if song.midi is None or song.midi in by_path:
            continue
        try:
            by_path[song.midi] = load_midi_events(song.midi)
        except Exception as exc:
            LOG.warning('%s: MIDI file %s unavailable (%s) — playing without it',
                        song.name, song.midi, exc)
            by_path[song.midi] = ()
    return by_path


class MidiEventsView:
    """Per-song events that follow reorders, like audio.MapsView for maps.

    Indexes the audio engine's current layout so a reorder repoints event
    lists exactly when it repoints tempo maps.
    """
    def __init__(self, engine, by_path):
        self._engine, self._by_path = engine, by_path

    def __getitem__(self, index):
        midi = self._engine._layout.setlist.songs[index].midi
        return self._by_path.get(midi, ()) if midi is not None else ()
