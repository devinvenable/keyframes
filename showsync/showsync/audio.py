"""Bounded streaming playback; the DAC frame timeline is the only time master.

The SPSC buffers rely on CPython's GIL for publishing integer indices. NumPy
copies finish before an index is published. No decoding, MIDI, logging, or
blocking locks occur in the callback. Python slice/tuple headers still allocate;
this is a soft real-time Python engine, not a hard real-time guarantee.
"""
from bisect import bisect_right
from collections import deque
from dataclasses import dataclass, field, replace
import logging
import math
from pathlib import Path
import threading
import time

import numpy as np

from .setlist import SetlistError, VIDEO_SUFFIXES
from .media import stream_duration

RATE = 48_000
LOG = logging.getLogger(__name__)


class Decoder:
    """Streaming float32 stereo at the engine rate; native rate is preserved."""
    samplerate = RATE

    @classmethod
    def open(cls, path, *, mute=False):
        suffix = Path(path).suffix.lower()
        if suffix in VIDEO_SUFFIXES:
            import av
            with av.open(str(path)) as source:
                if not source.streams.video:
                    raise ValueError('container has no video stream')
                if mute or not source.streams.audio:
                    return SilenceDecoder(stream_duration(source, source.streams.video[0]))
        return AVDecoder(path) if suffix in VIDEO_SUFFIXES | {'.m4a'} else SoundFileDecoder(path)

    @classmethod
    def for_song(cls, song):
        decoder = cls.open(song.file, mute=True) if song.mute else cls.open(song.file)
        return TrimmedDecoder(decoder, song.trim) if song.trim else decoder

    def _setup(self):
        import av
        self._resampler = av.AudioResampler(format='fltp', layout='stereo', rate=RATE)
        self._chunks = self._converted()
        self._pending = np.empty((0, 2), dtype=np.float32)
        self.frames = round(self.duration * RATE)
        self._read = 0

    def _converted(self):
        for frame in self._native_frames():
            for output in self._resampler.resample(frame):
                yield np.ascontiguousarray(output.to_ndarray().T)
        for output in self._resampler.resample(None):
            yield np.ascontiguousarray(output.to_ndarray().T)

    def read(self, n):
        n = min(n, self.frames - self._read)
        result = np.empty((n, 2), dtype=np.float32)
        used = 0
        while used < n:
            if not len(self._pending):
                self._pending = next(self._chunks, np.empty((0, 2), dtype=np.float32))
                if not len(self._pending):
                    break
            size = min(n - used, len(self._pending))
            result[used:used + size] = self._pending[:size]
            self._pending = self._pending[size:]
            used += size
        self._read += used
        return result[:used]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class TrimmedDecoder(Decoder):
    """A song's non-destructive trim: playback starts `trim` seconds in.

    Metadata shrinks immediately, so duration probes stay free; the skipped
    frames are decoded and discarded on the first read (no seeking, so the
    sequential MP3 path stays intact).
    """
    def __init__(self, decoder, trim):
        self._decoder = decoder
        self.native_samplerate = decoder.native_samplerate
        self._skip = min(decoder.frames, round(trim * RATE))
        self.frames = decoder.frames - self._skip
        self.duration = self.frames / RATE

    def read(self, n):
        while self._skip:
            block = self._decoder.read(min(4096, self._skip))
            if not len(block):
                self._skip = 0
                break
            self._skip -= len(block)
        return self._decoder.read(n)

    def close(self):
        self._decoder.close()


class SilenceDecoder(Decoder):
    """Bounded silence fed through the same ring/callback as decoded audio."""
    native_samplerate = RATE

    def __init__(self, duration):
        self.duration = duration
        self.frames = round(duration * RATE)
        self._read = 0

    def read(self, n):
        n = min(n, self.frames - self._read)
        self._read += n
        return np.zeros((n, 2), dtype=np.float32)

    def close(self):
        pass


class SoundFileDecoder(Decoder):
    def __init__(self, path):
        import soundfile as sf
        class SequentialMP3(sf.SoundFile):
            def seekable(self):
                # SoundFile seeks after every read on seekable inputs. Bundled
                # libsndfile 1.2.2 corrupts incremental MP3 output after those
                # seeks. Streaming sequentially preserves the MP3 bit reservoir.
                return False
        source_type = SequentialMP3 if Path(path).suffix.lower() == '.mp3' else sf.SoundFile
        self._source = source_type(path)
        self.native_samplerate = self._source.samplerate
        self.duration = len(self._source) / self.native_samplerate
        if self._source.channels not in (1, 2):
            self.close()
            raise ValueError(f'{path}: only mono/stereo files are supported')
        self._setup()

    def _native_frames(self):
        import av
        while len(block := self._source.read(4096, dtype='float32', always_2d=True)):
            if block.shape[1] == 1:
                block = np.repeat(block, 2, axis=1)
            frame = av.AudioFrame.from_ndarray(np.ascontiguousarray(block.T), format='fltp', layout='stereo')
            frame.sample_rate = self.native_samplerate
            yield frame

    def close(self):
        self._source.close()


class AVDecoder(Decoder):
    def __init__(self, path):
        import av
        self._source = av.open(str(path))
        try:
            self._stream = self._source.streams.audio[0]
            self.native_samplerate = self._stream.codec_context.sample_rate
            if len(self._stream.codec_context.layout.channels) not in (1, 2):
                raise ValueError('only mono/stereo files are supported')
            self.duration = stream_duration(self._source, self._stream)
            self._setup()
        except Exception:
            self.close()
            raise

    def _native_frames(self):
        import av
        for frame in self._source.decode(self._stream):
            # Duplicate mono without FFmpeg's default -3dB upmix attenuation.
            if len(frame.layout.channels) == 1:
                mono = av.AudioResampler(format='fltp', layout='mono', rate=frame.sample_rate)
                converted = mono.resample(frame)[0]
                data = np.repeat(converted.to_ndarray(), 2, axis=0)
                frame = av.AudioFrame.from_ndarray(data, format='fltp', layout='stereo')
                frame.sample_rate = self.native_samplerate
            frame.pts = None
            yield frame

    def close(self):
        self._source.close()


class RingBuffer:
    """One producer, one consumer. Underruns consume time, dropping late audio."""
    def __init__(self, capacity=4 * RATE):
        self.data = np.empty((capacity, 2), dtype=np.float32)
        self.capacity = capacity
        self.written = 0
        self.consumed = 0

    @property
    def available(self):
        return max(0, self.written - self.consumed)

    @property
    def free(self):
        return self.capacity - self.available

    def write(self, data):
        # When the consumer emitted silence, discard those late decoded frames.
        dropped = min(len(data), max(0, self.consumed - self.written))
        start = self.written + dropped
        count = min(len(data) - dropped, self.free)
        index = start % self.capacity
        first = min(count, self.capacity - index)
        self.data[index:index + first] = data[dropped:dropped + first]
        self.data[:count - first] = data[dropped + first:dropped + count]
        self.written = start + count
        return dropped + count

    def read_into(self, output):
        count = min(len(output), self.available)
        index = self.consumed % self.capacity
        first = min(count, self.capacity - index)
        output[:first] = self.data[index:index + first]
        output[first:count] = self.data[:count - first]
        output[count:] = 0
        self.consumed += len(output)
        return len(output) - count


@dataclass(frozen=True)
class Position:
    song_index: int
    song_time: float
    playing: bool
    epoch: int = 0
    ended: bool = False
    gap: bool = False
    frame: float = 0.0
    layout: object = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class Anchor:
    frame: int
    end_frame: int
    stamp: float
    playing: bool
    epoch: int


@dataclass(frozen=True)
class Layout:
    """One immutable snapshot of the set's timeline; swapped whole on reorder.

    The callback, producer, and readers each take a single reference per pass,
    so they can never see starts from one ordering and lengths from another.
    A reorder only permutes entries after the currently sounding song, so every
    frame the callback has already played means the same thing in both layouts.
    """
    setlist: object
    order: tuple          # order[i] = index of songs[i] in the file on disk
    starts: tuple
    lengths: tuple
    durations: tuple
    maps: tuple
    total_frames: int

    @property
    def reorder_margin(self):
        # Leave room for queued audio callbacks; there is no early handover.
        return .5


class MapsView:
    """Stable per-song tempo map accessor that follows reorders.

    The ClockEngine captures this once at wiring time; indexing always reads
    the engine's current layout.
    """
    def __init__(self, engine):
        self._engine = engine

    def __getitem__(self, index):
        return self._engine._layout.maps[index]

    def __len__(self):
        return len(self._engine._layout.maps)


class _Slot:
    def __init__(self, song):
        self.ring = RingBuffer()
        self.decoder = Decoder.for_song(song)
        self.path = song.file
        self.mute = song.mute
        self.eof = False

    def fill(self):
        if self.eof or not self.ring.free:
            return
        block = self.decoder.read(min(4096, self.ring.free))
        if not len(block):
            self.eof = True
            self.decoder.close()
        else:
            self.ring.write(block)

    def close(self):
        self.decoder.close()


class AudioEngine:
    def __init__(self, setlist, *, device=None, blocksize=256, now=time.monotonic,
                 stream_factory=None):
        self.device, self.blocksize, self.now = device, blocksize, now
        self._stream_factory = stream_factory
        durations, lengths, maps = [], [], []
        for song in setlist.songs:
            try:
                with Decoder.for_song(song) as decoder:
                    duration, length = decoder.duration, decoder.frames
                maps.append(song.tempo_map(duration))
            except Exception as exc:
                raise SetlistError(f'song {song.name}: file {song.file}: {exc}') from exc
            if length <= 0:
                raise SetlistError(f'song {song.name}: file contains no audio')
            durations.append(duration)
            lengths.append(length)
        starts, total = self._positions(setlist.songs, lengths, maps)
        self._layout = Layout(setlist, tuple(range(len(lengths))), starts,
                              tuple(lengths), tuple(durations), tuple(maps), total)
        self.maps = MapsView(self)
        self.frames_played = 0
        self.underruns = 0
        self.error = None
        self._slots = {}
        self._anchors = deque([Anchor(0, 0, -math.inf, False, 0)], maxlen=2048)
        self._requested = (False, 0, 0)  # playing, skip serial, target song
        self._skip_applied = 0
        self._skip_ready = 0  # producer publishes only after preparing this request
        self._epoch = 0
        self._halt = threading.Event()
        self._worker = None
        self.stream = None

    @staticmethod
    def _positions(songs, lengths, maps):
        """Pad each inter-song gap to the outgoing map's next four-beat bar.

        Gaps are minimum silences. Maps extend at their final BPM after EOF.
        Compare rounded frame positions so a bar already on the requested
        audio frame adds no wait, even for non-integral samples per beat.
        """
        starts, cursor = [], 0
        for song, length, tempo in zip(songs, lengths, maps):
            starts.append(cursor)
            end = length + round(song.gap * RATE)
            bar = math.floor(tempo.B(end / RATE) / 4)
            boundary = round(tempo.T(bar * 4) * RATE)
            if boundary < end:
                boundary = round(tempo.T((bar + 1) * 4) * RATE)
            cursor += boundary
        # There is no incoming song at set end; ignore the final gap as before.
        return tuple(starts), starts[-1] + lengths[-1]

    @property
    def setlist(self):
        return self._layout.setlist

    @property
    def durations(self):
        return self._layout.durations

    @property
    def total_frames(self):
        return self._layout.total_frames

    @property
    def order(self):
        return self._layout.order

    def prepare(self, timeout=15):
        if self._worker is None:
            self._worker = threading.Thread(target=self._produce, name='showsync-decode', daemon=True)
            self._worker.start()
        deadline = self.now() + timeout
        while self.now() < deadline:
            if self.error:
                raise RuntimeError(self.error)
            slots = self._slots
            if 0 in slots and slots[0].ring.available >= min(RATE, self._layout.lengths[0]):
                return
            time.sleep(.005)
        raise TimeoutError('audio prebuffer timed out')

    def start(self):
        self.prepare()
        if self._stream_factory is None:
            import sounddevice as sd
            self._stream_factory = sd.OutputStream
        self.stream = self._stream_factory(samplerate=RATE, channels=2, dtype='float32',
                                          blocksize=self.blocksize, latency='low',
                                          device=self.device, callback=self._callback)
        self._requested = (True, 0, 0)
        self.stream.start()

    def toggle_pause(self):
        playing, serial, target = self._requested
        self._requested = (not playing, serial, target)

    def skip(self):
        layout = self._layout
        _, serial, _ = self._requested
        # Use queued position so rapid skips progress, even before the next callback.
        index = max(bisect_right(layout.starts, self.frames_played) - 1,
                    self._requested[2] if serial != self._skip_applied else 0)
        target = min(index + 1, len(layout.starts))
        self._requested = (True, serial + 1, target)

    def restart(self):
        """Take the whole set from the top: the skip path targeting song 1.

        The epoch bump in the callback gives the clock its Stop (already sent
        if the set had ended) then Start, so gear re-syncs at song 1's tempo.
        """
        _, serial, _ = self._requested
        self._requested = (True, serial + 1, 0)

    def move(self, index, delta):
        """Move a not-yet-played song within the set; new index, or None if refused.

        Movable songs are those after the one currently sounding (every song
        once the set has ended). Refused while a skip/restart is settling and
        inside the half-second callback margin before a boundary.
        The guard also applies when paused: queued audio cannot be retracted.
        It keeps a callback boundary from landing inside the check-then-swap.
        """
        layout = self._layout
        _, serial, _ = self._requested
        if serial != self._skip_applied:
            return None
        count = len(layout.starts)
        frame = self.frames_played
        if frame >= layout.total_frames:
            first = 0
        else:
            current = max(0, bisect_right(layout.starts, frame) - 1)
            boundary = layout.starts[current + 1] if current + 1 < count else layout.total_frames
            if boundary - frame < layout.reorder_margin * RATE:
                return None
            first = current + 1
        target = index + delta
        if index == target or not (first <= index < count and first <= target < count):
            return None
        ids = list(range(count))
        ids.insert(target, ids.pop(index))
        songs = tuple(layout.setlist.songs[i] for i in ids)
        lengths = tuple(layout.lengths[i] for i in ids)
        maps = tuple(layout.maps[i] for i in ids)
        starts, total = self._positions(songs, lengths, maps)
        self._layout = Layout(replace(layout.setlist, songs=songs),
                              tuple(layout.order[i] for i in ids), starts, lengths,
                              tuple(layout.durations[i] for i in ids),
                              maps, total)
        if frame >= layout.total_frames:
            # Permuting gaps moves the last audible frame; stay at the end so
            # the ended state survives the reorder.
            self.frames_played = total
            self._anchors.append(Anchor(total, total, self.now(), False, self._epoch))
        return target

    def position(self):
        layout = self._layout
        now = self.now()
        # Index the bounded history without copying thousands of queued anchors
        # on every clock spin. Appends may advance the window, never invalidate a
        # fetched immutable anchor; the most recent audible anchor is sufficient.
        anchor = self._anchors[0]
        for offset in range(1, len(self._anchors) + 1):
            candidate = self._anchors[-offset]
            if candidate.stamp <= now:
                anchor = candidate
                break
        frame = float(anchor.frame)
        if anchor.playing:
            frame = min(anchor.end_frame, frame + max(0, now - anchor.stamp) * RATE)
        ended = frame >= layout.total_frames
        index = min(len(layout.starts) - 1, max(0, bisect_right(layout.starts, frame) - 1))
        seconds = (frame - layout.starts[index]) / RATE
        return Position(index, seconds, anchor.playing and not ended, anchor.epoch,
                        ended, seconds >= layout.durations[index] and not ended, frame, layout)

    def _produce(self):
        logged = 0
        try:
            while not self._halt.is_set():
                layout = self._layout
                _, serial, target = self._requested
                current = max(0, bisect_right(layout.starts, self.frames_played) - 1)
                rewind = (serial != self._skip_applied and serial != self._skip_ready
                          and target <= current)
                if serial != self._skip_applied:
                    current = target
                slots = dict(self._slots)
                # A reorder leaves slot indices pointing at different songs:
                # drop any slot whose decoder no longer matches its index.
                stale = [index for index, slot in slots.items()
                         if index >= len(layout.starts) or slot.path != layout.setlist.songs[index].file
                         or slot.mute != layout.setlist.songs[index].mute
                         or (rewind and index >= target)]
                for index in stale:
                    slots.pop(index).close()
                if stale:
                    self._slots = slots
                if current >= len(layout.starts):
                    self._halt.wait(.002)
                    continue
                wanted = {current}
                remaining = layout.starts[current] + layout.lengths[current] - self.frames_played
                if current + 1 < len(layout.starts) and remaining <= 10 * RATE:
                    wanted.add(current + 1)
                for index in wanted:
                    if index not in slots:
                        slot = _Slot(layout.setlist.songs[index])
                        if index == current and serial == self._skip_applied:
                            slot.ring.consumed = max(0, self.frames_played - layout.starts[index])
                        # Fill before publishing; callback never observes an opening decoder.
                        for _ in range(min(RATE, layout.lengths[index]) // 4096 + 1):
                            slot.fill()
                        slots[index] = slot
                    slots[index].fill()
                for index in set(slots) - wanted:
                    slots.pop(index).close()
                self._slots = slots
                # Publish buffers before readiness. The callback cannot accept an
                # old ring while we reopen a backward target (or a newer request
                # while this pass is still decoding an earlier serial).
                self._skip_ready = serial
                if self.underruns != logged:
                    LOG.warning('audio underrun: %d callback(s); output silence, timeline continues', self.underruns)
                    logged = self.underruns
                self._halt.wait(.001)
        except Exception as exc:
            self.error = f'decode failed: {exc}'
            LOG.exception(self.error)
        finally:
            for slot in self._slots.values():
                slot.close()

    def _callback(self, output, frames, timing, status):
        layout = self._layout
        stamp = self.now() + (timing.outputBufferDacTime - timing.currentTime)
        output.fill(0)
        playing, serial, target = self._requested
        # A skip waits for the next prebuffer, with silence/Stop in the meantime.
        if serial != self._skip_applied:
            if target >= len(layout.starts) or (serial == self._skip_ready and target in self._slots):
                self.frames_played = layout.starts[target] if target < len(layout.starts) else layout.total_frames
                self._skip_applied = serial
                self._epoch += 1
            else:
                playing = False
        if self.error:
            playing = False
        begin = self.frames_played
        playing = playing and begin < layout.total_frames
        offset = 0
        missed = bool(status)
        while playing and offset < frames and self.frames_played < layout.total_frames:
            index = bisect_right(layout.starts, self.frames_played) - 1
            local = self.frames_played - layout.starts[index]
            audio_left = layout.lengths[index] - local
            boundary = layout.starts[index + 1] if index + 1 < len(layout.starts) else layout.total_frames
            count = min(frames - offset, boundary - self.frames_played)
            if audio_left > 0:
                count = min(count, audio_left)
                slot = self._slots.get(index)
                if slot is not None:
                    missed |= bool(slot.ring.read_into(output[offset:offset + count]))
                else:
                    missed = True
            self.frames_played += count
            offset += count
        if missed:
            self.underruns += 1
        # PortAudio's times use its own epoch: translate the DAC delay to monotonic.
        self._anchors.append(Anchor(begin, self.frames_played, stamp, playing, self._epoch))

    def close(self):
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        self._halt.set()
        if self._worker is not None:
            self._worker.join(timeout=10)
            if self._worker.is_alive():
                LOG.error('decoder did not stop within 10 seconds')


def main():
    import argparse
    from .setlist import load_setlist
    parser = argparse.ArgumentParser(description='Play a ShowSync setlist without a GUI or MIDI')
    parser.add_argument('setlist')
    parser.add_argument('--audio-device', type=lambda s: int(s) if s.isdecimal() else s)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    engine = AudioEngine(load_setlist(args.setlist), device=args.audio_device)
    try:
        engine.start()
        while not engine.position().ended:
            if engine.error:
                raise RuntimeError(engine.error)
            time.sleep(.03)
    except KeyboardInterrupt:
        pass
    finally:
        engine.close()


if __name__ == '__main__':
    main()
