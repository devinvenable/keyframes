"""Bounded PyAV video decoding, driven exclusively by audio song position.

The GUI publishes one target and reads one result. No queues grow when either
side is slow, and neither side ever waits for the other. Containers and codec
state belong exclusively to the worker; the audio callback never calls here.
"""
from dataclasses import dataclass
import logging
import math
import threading

from .media import stream_duration, stream_start

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class Picture:
    pts: float
    until: float
    rgb: object


class VideoReader:
    def __init__(self, path, audio_origin=False):
        import av
        self.container = av.open(str(path))
        try:
            if not self.container.streams.video:
                raise ValueError('container has no video stream')
            self.stream = self.container.streams.video[0]
            # Match AVDecoder's first audio sample for embedded video. Separate
            # visuals and silent sources instead start at their first video PTS.
            origin = (self.container.streams.audio[0]
                      if audio_origin and self.container.streams.audio else self.stream)
            self.origin = stream_start(origin)
            self.end = (stream_start(self.stream) - self.origin +
                        stream_duration(self.container, self.stream))
            self.frames = iter(self.container.decode(self.stream))
            self.pending = self.current = self.picture = None
            self.previous = None
            self.target = None
            self.buffer = ()
        except Exception:
            self.close()
            raise

    def seek(self, seconds):
        # PyAV stream seeks use stream time-base units, not microseconds.
        # MPEG program streams carry sparse PES timestamps. Preroll gives the
        # parser sequence headers/timestamps before selecting the exact frame.
        preroll = 2 if self.container.format.name == 'mpeg' else 0
        stamp = math.floor((max(0, seconds - preroll) + self.origin) / self.stream.time_base)
        self.container.seek(stamp, stream=self.stream, backward=True, any_frame=False)
        self.frames = iter(self.container.decode(self.stream))
        self.pending = self.current = self.picture = None

    def frame_at(self, seconds, *, cancelled=lambda: False):
        """Latest frame due at seconds, decoding forward from a keyframe.

        Only the chosen frame is converted to RGB; all intervening late frames
        are dropped. One future frame is retained to delimit the current PTS.
        """
        if self.previous is None or seconds < self.previous or seconds - self.previous > .5:
            self.seek(seconds)
        self.previous = seconds
        if seconds >= self.end:
            return None
        while not cancelled():
            if self.pending is None:
                self.pending = next(self.frames, None)
                if self.pending is None:
                    break
            frame = self.pending
            if frame.pts is None:
                self.pending = None
                continue
            stamp = float(frame.pts * frame.time_base) - self.origin
            if stamp > seconds + 1e-9:
                break
            self.current, self.pending = frame, None
        if cancelled() or self.current is None:
            return None
        pts = float(self.current.pts * self.current.time_base) - self.origin
        until = (float(self.pending.pts * self.pending.time_base) - self.origin
                 if self.pending is not None else self.end)
        if self.picture is None or self.picture.pts != pts:
            self.picture = Picture(pts, until, self.current.to_ndarray(format='rgb24'))
        return self.picture

    def close(self):
        self.container.close()

    def pictures_at(self, seconds, *, cancelled=lambda: False):
        """A bounded 100 ms lookahead lets Qt present frames on their PTS.

        Conversion happens before the frame is due, even for 60 fps sources.
        When behind, frame_at discards late frames before converting RGB.
        """
        if self.target is not None and (seconds < self.target or seconds - self.target > .5):
            self.buffer = ()
            self.previous = None
        self.target = seconds
        pictures = [p for p in self.buffer if p.until > seconds]
        if not pictures:
            picture = self.frame_at(seconds, cancelled=cancelled)
            if picture is not None:
                pictures.append(picture)
        while len(pictures) < 8 and not cancelled():
            next_time = (pictures[-1].until if pictures else
                         float(self.pending.pts * self.pending.time_base) - self.origin
                         if self.pending is not None else self.end)
            if next_time >= min(self.end, seconds + .1):
                break
            picture = self.frame_at(next_time, cancelled=cancelled)
            if picture is None or (pictures and picture.pts <= pictures[-1].pts):
                break
            pictures.append(picture)
        self.buffer = tuple(pictures)
        return self.buffer


class VideoWorker:
    def __init__(self, reader_factory=VideoReader):
        self.reader_factory = reader_factory
        self.request = None  # ((path, audio_origin, epoch, song_index), seconds)
        self.result = None   # (key, tuple[Picture, ...] of at most eight frames, stream end)
        self.error = None
        self.halt = threading.Event()
        self.wake = threading.Event()
        self.thread = threading.Thread(target=self._run, name='showsync-video', daemon=True)
        self.thread.start()

    def submit(self, key, seconds=0):
        request = (key, seconds) if key is not None else None
        if request != self.request:
            self.request = request
            self.wake.set()

    def _run(self):
        reader = key = failed = None
        try:
            while not self.halt.is_set():
                self.wake.wait(.05)
                self.wake.clear()
                request = self.request
                wanted = request[0] if request else None
                if wanted != key:
                    if reader:
                        reader.close()
                    reader = None
                    key, failed = wanted, None
                    self.result = self.error = None
                if request is None or key == failed:
                    continue
                try:
                    if reader is None:
                        reader = self.reader_factory(key[0], audio_origin=key[1])
                    def cancelled():
                        latest = self.request
                        return self.halt.is_set() or latest is None or latest[0] != key
                    pictures = reader.pictures_at(request[1], cancelled=cancelled)
                    latest = self.request
                    if latest is not None and latest[0] == key:
                        # The stream end lets the GUI tell "video over" from
                        # "decoder running behind" when no frame is due.
                        self.result = (key, pictures, reader.end)
                except Exception as exc:
                    failed = key
                    self.error = (key, str(exc))
                    self.result = (key, (), 0.0)
                    LOG.warning('Video %s: %s; audio continues', key[0], exc)
        finally:
            if reader:
                reader.close()

    def close(self):
        self.halt.set()
        self.wake.set()
        # Do not stall transport teardown on a codec or slow storage read.
        self.thread.join(timeout=.25)
