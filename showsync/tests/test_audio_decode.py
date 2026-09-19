from pathlib import Path
from types import SimpleNamespace
import time

import numpy as np
import pytest

from showsync.audio import AudioEngine, Decoder, RATE, RingBuffer
from showsync.setlist import Setlist, Song

FIXTURES = Path(__file__).parent / 'fixtures'


@pytest.mark.parametrize('ext, native', [('wav', 44100), ('aiff', 48000), ('flac', 32000), ('mp3', 44100), ('m4a', 44100)])
def test_decode_real_formats(ext, native):
    with Decoder.open(FIXTURES / f'tone.{ext}') as decoder:
        assert decoder.samplerate == RATE
        assert decoder.native_samplerate == native
        chunks = []
        while len(block := decoder.read(997)):
            chunks.append(block)
        result = np.concatenate(chunks)
        assert result.dtype == np.float32
        assert result.shape == (RATE, 2)
        assert decoder.duration == pytest.approx(1, abs=1 / native)
        assert np.max(np.abs(result)) > .09
        assert np.sqrt(np.mean(result**2)) == pytest.approx(.1 / np.sqrt(2), abs=.005)
        assert np.max(np.abs(result[:, 0] - result[:, 1])) < 1e-4
        assert not len(decoder.read(100))


def test_ring_wrap_and_capacity():
    ring = RingBuffer(5)
    data = np.arange(14, dtype='float32').reshape(7, 2)
    assert ring.write(data) == 5
    out = np.empty((3, 2), dtype='float32')
    assert ring.read_into(out) == 0
    np.testing.assert_array_equal(out, data[:3])
    assert ring.write(data[5:]) == 2
    out = np.empty((4, 2), dtype='float32')
    assert ring.read_into(out) == 0
    np.testing.assert_array_equal(out, data[3:])


def test_underrun_discards_late_frames_instead_of_delaying_audio():
    ring = RingBuffer(8)
    data = np.arange(16, dtype='float32').reshape(8, 2)
    ring.write(data[:2])
    out = np.ones((5, 2), dtype='float32')
    assert ring.read_into(out) == 3
    np.testing.assert_array_equal(out[2:], 0)
    assert ring.write(data[2:]) == 6
    out = np.empty((3, 2), dtype='float32')
    assert ring.read_into(out) == 0
    np.testing.assert_array_equal(out, data[5:])


def make_engine(now=time.monotonic, gap=0):
    songs = (Song('one', FIXTURES / 'tone.wav', 120, gap), Song('two', FIXTURES / 'tone.flac', 140))
    return AudioEngine(Setlist('test', songs), now=now)


def callback(engine, frames, latency=0):
    output = np.empty((frames, 2), dtype=np.float32)
    engine._callback(output, frames, SimpleNamespace(currentTime=10, outputBufferDacTime=10 + latency), False)
    return output


def test_gapless_boundary_different_rates_and_gap():
    for gap in (0, .001):
        engine = make_engine(gap=gap)
        try:
            engine.prepare()
            deadline = time.monotonic() + 5
            while (1 not in engine._slots or engine._slots[1].ring.available < RATE) and time.monotonic() < deadline:
                time.sleep(.005)
            assert engine._slots[1].ring.available == RATE
            engine._requested = (True, 0, 0)
            # Real decoders feed one callback crossing file + gap + next song.
            out = callback(engine, RATE + round(gap * RATE) + 100)
            with Decoder.open(FIXTURES / 'tone.wav') as source:
                np.testing.assert_allclose(out[:RATE], source.read(RATE))
            np.testing.assert_array_equal(out[RATE:RATE + round(gap * RATE)], 0)
            with Decoder.open(FIXTURES / 'tone.flac') as source:
                np.testing.assert_allclose(out[-100:], source.read(100))
            assert engine.underruns == 0
        finally:
            engine.close()


def test_latency_pause_skip_end_use_audible_frames():
    now = [0.0]
    engine = make_engine(now=lambda: now[0])
    try:
        engine.prepare()
        while 1 not in engine._slots:
            time.sleep(.001)
        engine._requested = (True, 0, 0)
        callback(engine, 480, latency=.02)
        assert not engine.position().playing
        now[0] = .025
        p = engine.position()
        assert p.playing and p.song_time == pytest.approx(.005)
        engine.toggle_pause()
        callback(engine, 480, latency=.02)
        assert engine.position().playing
        now[0] = .05
        assert not engine.position().playing
        assert engine.position().song_time == pytest.approx(.01)
        engine.skip()
        callback(engine, 480, latency=.02)
        assert engine.position().song_index == 0
        now[0] = .075
        assert engine.position().song_index == 1
        assert engine.position().song_time == pytest.approx(.005)
        assert engine.position().epoch == 1
        engine.skip()
        callback(engine, 480)
        assert engine.position().ended
    finally:
        engine.close()


def test_callback_underrun_keeps_frame_counter():
    engine = make_engine()
    engine._requested = (True, 0, 0)
    out = callback(engine, 256)
    assert engine.frames_played == 256
    assert engine.underruns == 1
    np.testing.assert_array_equal(out, 0)


def test_duration_validation_before_device_open():
    from showsync.tempomap import TempoEvent
    from showsync.setlist import SetlistError
    songs = (Song('bad', FIXTURES / 'tone.wav', 120, tempo=(TempoEvent(2, 140),)),)
    with pytest.raises(SetlistError, match='duration'):
        AudioEngine(Setlist('test', songs))


@pytest.mark.device
def test_real_single_stream():
    import sounddevice as sd
    try:
        sd.check_output_settings(samplerate=RATE, channels=2, dtype='float32')
    except sd.PortAudioError as exc:
        pytest.skip(f'no usable default output device: {exc}')
    engine = make_engine()
    try:
        engine.start()
        stream = engine.stream
        deadline = time.monotonic() + 5
        while not engine.position().ended and time.monotonic() < deadline:
            time.sleep(.02)
        assert engine.position().ended
        assert engine.stream is stream and stream.active
        assert engine.frames_played == 2 * RATE
        assert engine.error is None
    finally:
        engine.close()
