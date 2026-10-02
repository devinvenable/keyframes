"""Sidecar take markers: timestamped song/tempo events for beat-synced editing.

perform.sh activates this by exporting SHOWSYNC_MARKERS=<path> (the take's
sidecar file) and SHOWSYNC_MARKERS_EPOCH=<unix seconds, float> (the wall
clock of the recording's first video frame, i.e. the recorded take's t=0).
Every record then carries t_rec — seconds since that t=0 — so an editor can
snap cuts to beats directly: beat positions are t_rec of a song_start plus
the song's tempo map (bpm + trim-adjusted ramp events, both included).

Format: one JSON object per line (JSON Lines), appended as events happen so
a crashed take still keeps everything up to the crash. Events:
  set_start   engines started (Play): set file, title, full song list
  song_start  a song became audible: index, name, file, bpm, tempo ramps;
              t_start is the song's exact audible t=0 (t_rec minus how far
              into the song the poll caught it — exact regardless of the
              poll interval)
  pause / resume
  set_end     the set played to its end
  set_stop    engines closed (Stop pressed or shutdown)

The writer polls AudioEngine.position() — the same cross-thread snapshot the
clock engine spins on — from its own daemon thread; it never touches the
audio callback path.
"""
import json
import logging
import os
import threading
import time

LOG = logging.getLogger(__name__)

POLL_SECONDS = 0.02


def song_fields(song, duration=None):
    """JSON-ready tempo identity of a song, on the playable timeline.

    Tempo event times are shifted by the song's trim (matching
    Song.tempo_map) so `at` is seconds after the audible start — the same
    timeline song_start's t_start anchors.
    """
    fields = {'name': song.name, 'file': str(song.file), 'bpm': song.bpm}
    if song.trim:
        fields['trim'] = song.trim
    if song.tempo:
        fields['tempo'] = [{'at': event.at - song.trim, 'bpm': event.bpm,
                            'ramp': event.ramp} for event in song.tempo]
    if duration is not None:
        fields['duration'] = round(duration, 3)
    return fields


class MarkerWriter:
    def __init__(self, path, rec_epoch=None, setlist_path=None):
        self.rec_epoch = rec_epoch
        self.setlist_path = setlist_path
        self._file = open(path, 'a', encoding='utf-8')
        self._lock = threading.Lock()
        self._halt = threading.Event()
        self._thread = None

    @classmethod
    def from_env(cls, setlist_path=None, environ=os.environ):
        """The writer the environment asks for, or None (markers are optional:
        a bad path/epoch only warns — it must never stop a take)."""
        path = environ.get('SHOWSYNC_MARKERS')
        if not path:
            return None
        rec_epoch = None
        raw = environ.get('SHOWSYNC_MARKERS_EPOCH', '')
        if raw:
            try:
                rec_epoch = float(raw)
            except ValueError:
                LOG.warning('SHOWSYNC_MARKERS_EPOCH %r is not a unix time — '
                            'markers will carry wall-clock epochs only', raw)
        try:
            return cls(path, rec_epoch=rec_epoch, setlist_path=setlist_path)
        except OSError as exc:
            LOG.warning('could not open markers file %s: %s — no take markers',
                        path, exc)
            return None

    def emit(self, event, at=None, **fields):
        """Append one marker. `at` overrides the event's wall time (used for
        song boundaries, which are detected a poll interval late)."""
        now = time.time() if at is None else at
        record = {'event': event, 'epoch': round(now, 3)}
        if self.rec_epoch is not None:
            record['t_rec'] = round(now - self.rec_epoch, 3)
        record.update(fields)
        with self._lock:
            if self._file.closed:
                return
            try:
                self._file.write(json.dumps(record) + '\n')
                self._file.flush()
            except OSError as exc:
                LOG.warning('markers write failed: %s', exc)

    def watch(self, audio):
        """Record set_start now and song/pause/end events as they play."""
        layout = audio.position().layout
        setlist = layout.setlist
        self.emit('set_start',
                  set_file=str(self.setlist_path) if self.setlist_path else None,
                  title=setlist.title,
                  songs=[song_fields(song, duration)
                         for song, duration in zip(setlist.songs, layout.durations)])
        self._thread = threading.Thread(target=self._poll, args=(audio,),
                                        name='showsync-markers', daemon=True)
        self._thread.start()

    def _poll(self, audio):
        last_index = last_epoch = None
        last_playing = None
        while not self._halt.is_set():
            try:
                pos = audio.position()
            except Exception as exc:  # engines torn down under us
                LOG.debug('markers poll stopped: %s', exc)
                return
            now = time.time()
            if pos.ended:
                self.emit('set_end')
                return
            if pos.playing and (pos.song_index, pos.epoch) != (last_index, last_epoch):
                song = pos.layout.setlist.songs[pos.song_index]
                # The boundary happened song_time seconds before this poll.
                self.emit('song_start', at=now - pos.song_time,
                          song_index=pos.song_index,
                          **song_fields(song, pos.layout.durations[pos.song_index]))
                last_index, last_epoch = pos.song_index, pos.epoch
            elif last_playing is not None and pos.playing != last_playing:
                self.emit('resume' if pos.playing else 'pause',
                          song_index=pos.song_index,
                          song_time=round(pos.song_time, 3))
            last_playing = pos.playing
            self._halt.wait(POLL_SECONDS)

    def close(self):
        """Stop polling, record set_stop, release the file. Idempotent."""
        self._halt.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        if not self._file.closed:
            self.emit('set_stop')
            with self._lock:
                self._file.close()
