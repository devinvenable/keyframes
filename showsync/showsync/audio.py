"""Bounded streaming playback; the DAC frame timeline is the only time master.

The SPSC buffers rely on CPython's GIL for publishing integer indices. NumPy
copies finish before an index is published. No decoding, MIDI, logging, or
blocking locks occur in the callback. Python slice/tuple headers still allocate;
this is a soft real-time Python engine, not a hard real-time guarantee.
"""
from bisect import bisect_right
from collections import deque
from dataclasses import dataclass
import logging
import math
from pathlib import Path
import threading
import time

import numpy as np

from .setlist import SetlistError

RATE = 48_000
LOG = logging.getLogger(__name__)


class Decoder:
    """Streaming float32 stereo at the engine rate; native rate is preserved."""
    samplerate = RATE

    @classmethod
    def open(cls, path):
        return AVDecoder(path) if Path(path).suffix.lower() == '.m4a' else SoundFileDecoder(path)

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
            if self._stream.duration is None:
                raise ValueError('audio stream has no duration')
            self.duration = float(self._stream.duration * self._stream.time_base)
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


@dataclass(frozen=True)
class Anchor:
    frame: int
    end_frame: int
    stamp: float
    playing: bool
    epoch: int


class _Slot:
    def __init__(self, path):
        self.ring = RingBuffer()
        self.decoder = Decoder.open(path)
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
        self.setlist = setlist
        self.device, self.blocksize, self.now = device, blocksize, now
        self._stream_factory = stream_factory
        self.durations, self.lengths, self.maps = [], [], []
        self.starts = []
        cursor = 0
        for song in setlist.songs:
            try:
                with Decoder.open(song.file) as decoder:
                    duration, length = decoder.duration, decoder.frames
                self.maps.append(song.tempo_map(duration))
            except Exception as exc:
                raise SetlistError(f'song {song.name}: file {song.file}: {exc}') from exc
            if length <= 0:
                raise SetlistError(f'song {song.name}: file contains no audio')
            self.starts.append(cursor)
            self.durations.append(duration)
            self.lengths.append(length)
            cursor += length + round(song.gap * RATE)
        self.total_frames = self.starts[-1] + self.lengths[-1]
        self.frames_played = 0
        self.underruns = 0
        self.error = None
        self._slots = {}
        self._anchors = deque([Anchor(0, 0, -math.inf, False, 0)], maxlen=2048)
        self._requested = (False, 0, 0)  # playing, skip serial, target song
        self._skip_applied = 0
        self._epoch = 0
        self._halt = threading.Event()
        self._worker = None
        self.stream = None

    def prepare(self, timeout=15):
        if self._worker is None:
            self._worker = threading.Thread(target=self._produce, name='showsync-decode', daemon=True)
            self._worker.start()
        deadline = self.now() + timeout
        while self.now() < deadline:
            if self.error:
                raise RuntimeError(self.error)
            slots = self._slots
            if 0 in slots and slots[0].ring.available >= min(RATE, self.lengths[0]):
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
        _, serial, _ = self._requested
        # Use queued position so rapid skips progress, even before the next callback.
        index = max(bisect_right(self.starts, self.frames_played) - 1,
                    self._requested[2] if serial != self._skip_applied else 0)
        target = min(index + 1, len(self.starts))
        self._requested = (True, serial + 1, target)

    def position(self):
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
        ended = frame >= self.total_frames
        index = min(len(self.starts) - 1, max(0, bisect_right(self.starts, frame) - 1))
        seconds = (frame - self.starts[index]) / RATE
        return Position(index, seconds, anchor.playing and not ended, anchor.epoch,
                        ended, seconds >= self.durations[index] and not ended, frame)

    def _produce(self):
        logged = 0
        try:
            while not self._halt.is_set():
                _, serial, target = self._requested
                current = max(0, bisect_right(self.starts, self.frames_played) - 1)
                if serial != self._skip_applied:
                    current = target
                if current >= len(self.starts):
                    self._halt.wait(.002)
                    continue
                wanted = {current}
                remaining = self.starts[current] + self.lengths[current] - self.frames_played
                if current + 1 < len(self.starts) and remaining <= 10 * RATE:
                    wanted.add(current + 1)
                slots = dict(self._slots)
                for index in wanted:
                    if index not in slots:
                        slot = _Slot(self.setlist.songs[index].file)
                        if index == current and serial == self._skip_applied:
                            slot.ring.consumed = max(0, self.frames_played - self.starts[index])
                        # Fill before publishing; callback never observes an opening decoder.
                        for _ in range(min(RATE, self.lengths[index]) // 4096 + 1):
                            slot.fill()
                        slots[index] = slot
                    slots[index].fill()
                for index in set(slots) - wanted:
                    slots.pop(index).close()
                self._slots = slots
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
        stamp = self.now() + (timing.outputBufferDacTime - timing.currentTime)
        output.fill(0)
        playing, serial, target = self._requested
        # A skip waits for the next prebuffer, with silence/Stop in the meantime.
        if serial != self._skip_applied:
            if target >= len(self.starts) or target in self._slots:
                self.frames_played = self.starts[target] if target < len(self.starts) else self.total_frames
                self._skip_applied = serial
                self._epoch += 1
            else:
                playing = False
        if self.error:
            playing = False
        begin = self.frames_played
        playing = playing and begin < self.total_frames
        offset = 0
        missed = bool(status)
        while playing and offset < frames and self.frames_played < self.total_frames:
            index = bisect_right(self.starts, self.frames_played) - 1
            local = self.frames_played - self.starts[index]
            audio_left = self.lengths[index] - local
            boundary = self.starts[index + 1] if index + 1 < len(self.starts) else self.total_frames
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
