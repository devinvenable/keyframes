from pathlib import Path
from types import SimpleNamespace
import time
import threading

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


def test_bar_padding_different_rates_and_gap():
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
            out = callback(engine, 2 * RATE + 100)
            with Decoder.open(FIXTURES / 'tone.wav') as source:
                np.testing.assert_allclose(out[:RATE], source.read(RATE))
            np.testing.assert_array_equal(out[RATE:2 * RATE], 0)
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
        wait_for_skip(engine)
        callback(engine, 480, latency=.02)
        assert engine.position().song_index == 0
        now[0] = .075
        assert engine.position().song_index == 1
        assert engine.position().song_time == pytest.approx(.005)
        assert engine.position().epoch == 1
        engine.skip()
        wait_for_skip(engine)
        callback(engine, 480)
        assert engine.position().ended
    finally:
        engine.close()


def wait_for_slot(engine, index, path=None, deadline=5):
    limit = time.monotonic() + deadline
    while time.monotonic() < limit:
        slot = engine._slots.get(index)
        if slot is not None and (path is None or slot.path == path) and slot.ring.available >= min(RATE, engine._layout.lengths[index]):
            return slot
        time.sleep(.005)
    raise AssertionError(f'slot {index} for {path} never prebuffered')


def wait_for_skip(engine):
    limit = time.monotonic() + 5
    while time.monotonic() < limit:
        if (engine._requested[2] >= len(engine.maps)
                or engine._skip_ready == engine._requested[1]):
            return
        assert engine.error is None
        time.sleep(.001)
    raise AssertionError('skip never prepared')


def test_reorder_updates_layout_and_redoes_prefetch():
    songs = (Song('one', FIXTURES / 'tone.wav', 120), Song('two', FIXTURES / 'tone.flac', 140),
             Song('three', FIXTURES / 'tone.aiff', 100, gap=.5))
    engine = AudioEngine(Setlist('test', songs))
    try:
        engine.prepare()
        wait_for_slot(engine, 1, FIXTURES / 'tone.flac')  # 1 s songs prefetch immediately
        assert engine.move(0, 1) is None      # current song is locked
        assert engine.move(1, -1) is None     # nothing may land on the current song
        assert engine.move(2, -1) == 1        # 'three' now plays second
        assert engine.order == (0, 2, 1)
        assert [s.name for s in engine.setlist.songs] == ['one', 'three', 'two']
        assert engine._layout.starts == (0, 2 * RATE, round(4.4 * RATE))
        assert engine.total_frames == engine._layout.starts[2] + RATE
        # The stale 'two' prefetch is discarded and 'three' decoded in its place.
        wait_for_slot(engine, 1, FIXTURES / 'tone.aiff')
        engine._requested = (True, 0, 0)
        out = callback(engine, 2 * RATE + 100)
        with Decoder.open(FIXTURES / 'tone.aiff') as source:
            np.testing.assert_allclose(out[-100:], source.read(100))
        assert engine.underruns == 0
    finally:
        engine.close()


def test_reorder_refused_near_boundary_and_while_skip_pending():
    songs = (Song('one', FIXTURES / 'tone.wav', 120), Song('two', FIXTURES / 'tone.flac', 140),
             Song('three', FIXTURES / 'tone.aiff', 100))
    engine = AudioEngine(Setlist('test', songs))
    engine._requested = (True, 0, 0)
    engine.frames_played = 2 * RATE - 100      # playing, 100 frames before the boundary
    assert engine.move(1, 1) is None
    engine._requested = (False, 0, 0)      # incoming clocks may already have fired
    assert engine.move(1, 1) is None
    engine.frames_played = 0
    assert engine.move(1, 1) == 2
    engine._requested = (True, 1, 2)       # skip still settling
    assert engine.move(2, -1) is None


def test_restart_after_end_and_ended_reorder():
    now = [0.0]
    engine = make_engine(now=lambda: now[0])
    try:
        engine.prepare()
        wait_for_slot(engine, 1)
        engine._requested = (True, 0, 0)
        engine.skip()
        wait_for_skip(engine)
        callback(engine, 480)
        engine.skip()
        wait_for_skip(engine)
        callback(engine, 480)
        assert engine.position().ended
        # The whole set is reorderable once it has ended.
        assert engine.move(0, 1) == 1
        assert engine.order == (1, 0)
        assert engine.position().ended
        engine.restart()
        wait_for_skip(engine)
        wait_for_slot(engine, 0, FIXTURES / 'tone.flac')
        out = callback(engine, 480)
        with Decoder.open(FIXTURES / 'tone.flac') as source:
            np.testing.assert_allclose(out, source.read(480))
        now[0] = .005
        p = engine.position()
        assert (p.song_index, p.ended, p.playing) == (0, False, True)
        assert p.epoch == 3
    finally:
        engine.close()


@pytest.mark.parametrize('initial, gap, offset, presses', [
    (137, 0, 0, 1),             # partially consumed first song
    (2 * RATE + 137, 0, 0, 1),  # partially consumed second song
    (137, 0, .1, 1),            # still in the first-beat lead-in
    (RATE + 137, .25, 0, 1),    # silent inter-song gap
    (137, 0, 0, 3),             # several requests before decoding finishes
])
def test_restart_replays_audio_and_resets_clock(monkeypatch, initial, gap, offset, presses):
    from showsync.clock import CLOCK, START, STOP, ClockEngine

    now = [0.0]
    songs = (Song('one', FIXTURES / 'tone.wav', 120, gap=gap, offset=offset),
             Song('two', FIXTURES / 'tone.flac', 140))
    engine = AudioEngine(Setlist('test', songs), now=lambda: now[0])
    messages = []
    clock = ClockEngine(engine.maps, engine.position,
                        lambda byte: messages.append((now[0], byte)))
    release = threading.Event()
    opening = threading.Event()
    try:
        engine.prepare()
        wait_for_slot(engine, 1)
        engine._requested = (True, 0, 0)
        callback(engine, initial)
        now[0] = (initial - 1) / RATE
        clock.step()
        assert engine.position().playing
        messages.clear()
        old_epoch = engine.position().epoch

        # Hold new decoders so the callback must silence a pending rewind,
        # even while the original, partially consumed slot still exists.
        original_open = Decoder.open
        def blocked_open(path):
            opening.set()
            assert release.wait(5), 'test did not release decoder'
            return original_open(path)
        monkeypatch.setattr(Decoder, 'open', blocked_open)
        engine.restart()
        if presses > 1:
            assert opening.wait(5), 'rewind did not reopen the decoder'
        for _ in range(presses - 1):
            engine.restart()
        out = callback(engine, 256)
        np.testing.assert_array_equal(out, 0)
        assert engine.position().epoch == old_epoch
        assert engine.frames_played == initial
        clock.step()
        assert [byte for _, byte in messages] == [STOP]

        release.set()
        wait_for_skip(engine)
        base = now[0]
        out = callback(engine, 30_000)
        with original_open(songs[0].file) as source:
            np.testing.assert_array_equal(out, source.read(len(out)))
        assert engine.position().epoch == old_epoch + 1
        assert engine._skip_applied == engine._requested[1]
        # Interpolate within the real audio anchor using the injected time.
        clock.step()
        now[0] = base + offset
        for tick in range(24):
            now[0] = base + offset + tick / 48
            clock.step()
        assert [byte for _, byte in messages if byte != CLOCK] == [STOP, START]
        ticks = [stamp - base for stamp, byte in messages if byte == CLOCK]
        assert ticks == pytest.approx([offset + tick / 48 for tick in range(24)])
        # The second song's stale ring must also be discarded on rewind.
        wait_for_slot(engine, 1)
        out = callback(engine, engine._layout.starts[1] - 30_000 + 137)
        with original_open(songs[1].file) as source:
            np.testing.assert_array_equal(out[-137:], source.read(137))
        assert engine.position().epoch == old_epoch + 1
    finally:
        release.set()
        engine.close()


def test_callback_underrun_keeps_frame_counter():
    engine = make_engine()
    engine._requested = (True, 0, 0)
    out = callback(engine, 256)
    assert engine.frames_played == 256
    assert engine.underruns == 1
    np.testing.assert_array_equal(out, 0)


def test_underrun_log_carries_timeline_position_and_duration(caplog):
    # A recording gap can only be correlated with the logs if each underrun
    # warning names WHERE on the timeline it happened and HOW LONG it was.
    engine = make_engine()
    engine._requested = (True, 0, 0)
    engine.frames_played = RATE // 2          # 0.5 s into song one
    callback(engine, 256)                     # no slot: the whole block is lost
    with caplog.at_level('WARNING', logger='showsync.audio'):
        engine._log_events()
    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert 'audio underrun #1' in message
    assert '5.3 ms (256 frames)' in message
    assert "0:00.500 into the set (song 1 'one' at 0:00.500)" in message
    assert 'callback 1' in message


def halt_producer(engine):
    # Deterministic event tests: the producer thread also drains the event
    # log and refills rings, so stop it and drain manually instead.
    engine._halt.set()
    engine._worker.join(timeout=5)
    assert not engine._worker.is_alive()
    engine._events.clear()


def test_underrun_log_reports_partial_ring_shortfall(caplog):
    engine = make_engine()
    try:
        engine.prepare()
        halt_producer(engine)
        engine._requested = (True, 0, 0)
        # Leave only 100 frames in the ring: 156 of 256 requested are lost.
        slot = engine._slots[0]
        slot.ring.written = slot.ring.consumed + 100
        callback(engine, 256)
        assert engine.underruns == 1
        with caplog.at_level('WARNING', logger='showsync.audio'):
            engine._log_events()
        assert '3.2 ms (156 frames)' in caplog.records[0].getMessage()
    finally:
        engine.close()


def test_underrun_log_includes_portaudio_status(caplog):
    engine = make_engine()
    engine._requested = (True, 0, 0)
    output = np.empty((256, 2), dtype=np.float32)
    engine._callback(output, 256, SimpleNamespace(currentTime=10, outputBufferDacTime=10),
                     'output underflow')
    with caplog.at_level('WARNING', logger='showsync.audio'):
        engine._log_events()
    assert 'portaudio reported: output underflow' in caplog.records[0].getMessage()


def test_skip_settling_silence_is_logged_but_not_an_underrun(caplog):
    # A skip waiting for its prebuffer emits silence without touching the
    # underrun counter; that silence must still be visible in the logs.
    engine = make_engine()
    try:
        engine.prepare()
        wait_for_slot(engine, 1)              # 1 s songs prefetch immediately
        halt_producer(engine)
        engine._requested = (True, 0, 0)
        callback(engine, 256)
        engine.skip()
        callback(engine, 256)                 # not prepared yet: silent settling
        assert engine.underruns == 0
        engine._skip_ready = engine._requested[1]   # producer would publish this
        callback(engine, 256)                 # skip applies here
        with caplog.at_level('WARNING', logger='showsync.audio'):
            engine._log_events()
        messages = [r.getMessage() for r in caplog.records]
        transition = [m for m in messages if 'transition silence' in m]
        assert len(transition) == 1
        assert '5.3 ms (256 frames)' in transition[0]
        assert "song 2 'two' at 0:00.000" in transition[0]
        assert engine.underruns == 0
    finally:
        engine.close()


def test_start_prerolls_silent_callbacks_before_playback():
    # The stream must run silent warm-up callbacks before playback is
    # requested, so the set-start burst cannot starve the first audible
    # callbacks; the timeline still begins at frame 0.
    class FakeStream:
        def __init__(self, callback=None, **kwargs):
            self.callback = callback

        def start(self):
            for _ in range(3):
                out = np.empty((256, 2), dtype=np.float32)
                self.callback(out, 256, SimpleNamespace(currentTime=10, outputBufferDacTime=10.01), False)
                np.testing.assert_array_equal(out, 0)

        def stop(self):
            pass

        def close(self):
            pass

    songs = (Song('one', FIXTURES / 'tone.wav', 120),)
    engine = AudioEngine(Setlist('test', songs), stream_factory=lambda **kw: FakeStream(**kw))
    try:
        begin = time.monotonic()
        engine.start(warmup=5)
        assert time.monotonic() - begin < 2  # exits on callbacks, not the timeout
        assert engine.callbacks >= 2
        assert engine.frames_played == 0  # pre-roll never advances the timeline
        assert engine.underruns == 0      # silence warm-up is not an underrun
        assert engine._requested[0] is True  # playback requested only after warm-up
        assert engine._callback_schedule     # schedule readback captured for the log
    finally:
        engine.close()


def test_first_callback_elevates_its_own_thread_to_sched_rr(monkeypatch):
    # PortAudio creates the callback thread, so only the callback itself can
    # request SCHED_RR for it. The first (silent, pre-roll) callback must make
    # exactly one elevation attempt and store the kernel readback for the log.
    from showsync import audio
    calls = []

    def fake_elevate(priority):
        calls.append(priority)
        return f'SCHED_RR prio {priority}'

    monkeypatch.setattr(audio, 'elevate_thread', fake_elevate)
    engine = make_engine()
    try:
        engine.prepare()
        callback(engine, 256)
        callback(engine, 256)
        assert calls == [audio.CALLBACK_PRIORITY]  # once, not per callback
        assert engine._callback_schedule == f'SCHED_RR prio {audio.CALLBACK_PRIORITY}'
    finally:
        engine.close()


def test_audio_callback_thread_schedule_is_logged(caplog):
    import logging
    engine = make_engine()
    try:
        with caplog.at_level(logging.INFO, logger='showsync.audio'):
            engine.prepare()
            callback(engine, 256)
            deadline = time.monotonic() + 5
            while 'audio callback thread' not in caplog.text and time.monotonic() < deadline:
                time.sleep(.005)
        assert f'audio callback thread: {engine._callback_schedule}' in caplog.text
    finally:
        engine.close()


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
        assert engine.frames_played == 3 * RATE
        assert engine.error is None
    finally:
        engine.close()


def test_trimmed_decoder_skips_exactly_and_shrinks_metadata():
    song = Song('tone', FIXTURES / 'tone.wav', 120, trim=.25)
    skip = round(.25 * RATE)
    with Decoder.open(FIXTURES / 'tone.wav') as reference:
        reference.read(skip)
        expected = reference.read(1000)
    with Decoder.for_song(song) as trimmed:
        assert trimmed.frames == RATE - skip
        assert trimmed.duration == pytest.approx(.75)
        np.testing.assert_array_equal(trimmed.read(1000), expected)
        total = 1000
        while len(block := trimmed.read(4096)):
            total += len(block)
        assert total == RATE - skip


def test_engine_honors_trim_for_audio_and_clock():
    from showsync.clock import ClockEngine
    song = Song('tone', FIXTURES / 'tone.wav', 120, offset=.25, trim=.25)
    engine = AudioEngine(Setlist('trimmed', (song,)), now=lambda: 0)
    try:
        assert engine.durations == (pytest.approx(.75),)
        assert engine.total_frames == RATE - round(.25 * RATE)
        # Trim is t=0 for the map: the .25 s offset is consumed by the trim,
        # so beat 0 lands on the first played sample and MIDI starts at once.
        assert engine.maps[0].offset == 0
        engine.prepare()
        engine._requested = (True, 0, 0)
        sent = []
        clock = ClockEngine(engine.maps, engine.position, sent.append, now=lambda: 0)
        with Decoder.for_song(song) as reference:
            expected = reference.read(4800)
        output = callback(engine, 4800)
        clock.step()
        np.testing.assert_array_equal(output, expected)
        assert engine.frames_played == 4800
        assert engine.underruns == 0
        assert 0xFA in sent and 0xF8 in sent  # Start and the t=0 tick
    finally:
        engine.close()
