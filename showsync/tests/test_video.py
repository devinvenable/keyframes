"""Real container fixtures, audio-master transport, bounded decoding and Qt output."""
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
import threading
import time
import zipfile

import av
import numpy as np
import pytest
from PySide6.QtCore import QSettings, Qt

from showsync.audio import AudioEngine, Decoder, Position, RATE
from showsync.bpmdetect import _features
from showsync.bundle import BundleError, export_bundle
from showsync.document import Document, Row
from showsync.setlist import Setlist, SetlistError, Song, load_setlist
from showsync.video import Picture, VideoReader, VideoWorker
from showsync.video_window import VideoWindow


def make_video(path, *, audio=True, start=0, audio_start=0, rate=10, video_seconds=1):
    """One second of ten distinguishable frames and optional 44.1 kHz tone."""
    with av.open(str(path), 'w') as output:
        video = output.add_stream('mpeg4', rate=rate)
        video.width, video.height, video.pix_fmt = 64, 48, 'yuv420p'
        video.codec_context.gop_size = 5
        sound = output.add_stream('aac', rate=44100) if audio else None
        if sound:
            sound.layout = 'stereo'
        for index in range(rate * video_seconds):
            pixels = np.full((48, 64, 3), 20 + (index % rate) * 200 // rate, dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(pixels, format='rgb24')
            frame.pts, frame.time_base = start * rate + index, Fraction(1, rate)
            for packet in video.encode(frame):
                output.mux(packet)
        for packet in video.encode(None):
            output.mux(packet)
        if sound:
            for index in range(0, 44100, 1024):
                samples = np.arange(index, min(index + 1024, 44100))
                tone = (.1 * np.sin(2 * np.pi * samples * 440 / 44100)).astype('float32')
                frame = av.AudioFrame.from_ndarray(np.vstack((tone, tone)), format='fltp', layout='stereo')
                frame.sample_rate = 44100
                frame.pts, frame.time_base = audio_start * 44100 + index, Fraction(1, 44100)
                for packet in sound.encode(frame):
                    output.mux(packet)
            for packet in sound.encode(None):
                output.mux(packet)
    return path


@pytest.fixture
def clip(tmp_path):
    return make_video(tmp_path / 'clip.mp4')


def callback(engine, frames):
    out = np.empty((frames, 2), dtype=np.float32)
    engine._callback(out, frames, SimpleNamespace(currentTime=0, outputBufferDacTime=0), False)
    return out


def wait_for(predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        time.sleep(.002)
    assert predicate(), 'worker did not finish'


def test_embedded_audio_uses_existing_decoder_ring_and_analysis(clip):
    with Decoder.open(clip) as decoder:
        assert decoder.native_samplerate == 44100
        assert decoder.frames == RATE
        samples = decoder.read(RATE)
        assert samples.shape == (RATE, 2)
        assert np.max(np.abs(samples)) > .08
    _, power, _ = _features(clip, lambda: None)
    assert np.max(power) > .001
    engine = AudioEngine(Setlist('movie', (Song('clip', clip, 120),)))
    try:
        engine.prepare()
        engine._requested = (True, 0, 0)
        np.testing.assert_allclose(callback(engine, 4800), samples[:4800])
        assert engine.frames_played == 4800
        assert engine.underruns == 0
    finally:
        engine.close()


@pytest.mark.parametrize('has_audio,mute', [(False, False), (True, True)])
def test_silent_video_feeds_audio_master_and_clock(tmp_path, has_audio, mute):
    from showsync.clock import ClockEngine
    path = make_video(tmp_path / 'silent.mp4', audio=has_audio)
    song = Song('silent', path, 120, mute=mute)
    engine = AudioEngine(Setlist('silent set', (song,)), now=lambda: 0)
    try:
        engine.prepare()
        engine._requested = (True, 0, 0)
        sent = []
        clock = ClockEngine(engine.maps, engine.position, sent.append, now=lambda: 0)
        output = callback(engine, RATE)
        clock.step()
        assert not np.any(output)
        assert engine.durations == (1.0,)
        assert engine.frames_played == RATE
        assert engine.error is None and engine.underruns == 0
        assert sent
    finally:
        engine.close()


def test_separate_visuals_never_replace_backing_audio(clip):
    tone = Path(__file__).parent / 'fixtures' / 'tone.wav'
    song = Song('separate', tone, 120, video=clip)
    engine = AudioEngine(Setlist('show', (song,)))
    try:
        engine.prepare()
        engine._requested = (True, 0, 0)
        with Decoder.open(tone) as expected:
            np.testing.assert_allclose(callback(engine, 4800), expected.read(4800))
        assert song.video_source == clip
    finally:
        engine.close()


def test_pts_selects_due_frame_drops_late_frames_and_reseeks(clip):
    reader = VideoReader(clip, audio_origin=True)
    try:
        first = reader.frame_at(0)
        assert first.pts == 0
        assert reader.frame_at(.39).pts == pytest.approx(.3)
        assert reader.frame_at(.91).pts == pytest.approx(.9)
        rewind = reader.frame_at(.21)
        assert rewind.pts == pytest.approx(.2)
        assert rewind.until == pytest.approx(.3)
        assert rewind.rgb.mean() > first.rgb.mean() + 30
        assert reader.frame_at(.21) is rewind
        assert reader.frame_at(1) is None
    finally:
        reader.close()


def test_nonzero_pts_origin_and_audio_video_offset(tmp_path):
    path = make_video(tmp_path / 'offset.mp4', start=2, audio_start=1)
    embedded = VideoReader(path, audio_origin=True)
    separate = VideoReader(path)
    try:
        assert embedded.frame_at(.5) is None
        assert embedded.frame_at(1.25).pts == pytest.approx(1.2, abs=.03)
        assert separate.frame_at(.25).pts == pytest.approx(.2)
        assert separate.frame_at(.05).pts == 0
    finally:
        embedded.close()
        separate.close()


def test_stalled_video_never_blocks_audio_or_publishes_old_epoch(clip):
    entered, release = threading.Event(), threading.Event()
    closed = []
    class SlowReader:
        end = 1.0
        def __init__(self, path, audio_origin=False):
            pass
        def pictures_at(self, seconds, **kwargs):
            entered.set()
            release.wait(5)
            return (Picture(seconds, seconds + .1, np.zeros((2, 2, 3), dtype=np.uint8)),)
        def close(self):
            closed.append(True)
    worker = VideoWorker(SlowReader)
    engine = AudioEngine(Setlist('show', (Song('clip', clip, 120),)))
    old = (clip, True, 0, 0)
    new = (clip, True, 1, 0)
    try:
        engine.prepare()
        engine._requested = (True, 0, 0)
        worker.submit(old, .1)
        assert entered.wait(2)
        for _ in range(20):
            callback(engine, 480)
            worker.submit(old, .2)
        worker.submit(new, .3)
        assert engine.frames_played == 9600
        assert engine.underruns == 0
        assert worker.result is None
        release.set()
        wait_for(lambda: worker.result is not None)
        assert worker.result[0] == new
        assert worker.result[1][0].pts == .3
        assert closed
    finally:
        release.set()
        worker.close()
        engine.close()


def test_video_setlist_document_roundtrip_and_validation(tmp_path, clip):
    path = tmp_path / 'set.yaml'
    path.write_text('songs:\n  - name: Clip\n    file: clip.mp4\n    video: clip.mp4 # visuals\n    mute: true\n    bpm: 120\n')
    song = load_setlist(path).songs[0]
    assert song.video == clip and song.mute
    document = Document.load(path)
    assert document.setlist().songs[0] == song
    document.rows[0].name = 'Changed'
    document.save()
    assert '# visuals' in path.read_text()
    assert load_setlist(path).songs[0].mute
    assert load_setlist(path).songs[0].video == clip
    document = Document(tmp_path / 'new.yaml', rows=[Row('new', clip, 120, video=clip, mute=True)])
    document.save()
    assert load_setlist(document.path).songs[0].video == clip
    longer = make_video(tmp_path / 'longer.mp4', video_seconds=2)
    document.replace_file(document.rows[0], longer)
    assert document.rows[0].mute
    assert document.rows[0].duration == 2
    document.save()
    assert Document.load(document.path).rows[0].duration == 2
    text = path.read_text()
    path.write_text(text.replace('mute: true', 'mute: yesplease'))
    with pytest.raises(SetlistError, match='mute must be a boolean'):
        load_setlist(path)
    path.write_text(text.replace('video: clip.mp4', 'video: missing.mp4'))
    with pytest.raises(SetlistError, match='video does not exist'):
        load_setlist(path)
    assert 'video file not found' in Document.load(path).rows[0].problem()


def test_bundle_packs_deduplicates_video_and_warns_without_gating(tmp_path, clip, monkeypatch, caplog):
    from showsync import bundle
    other = tmp_path / 'visuals.mp4'
    other.write_bytes(clip.read_bytes())
    path = tmp_path / 'set.yaml'
    path.write_text('songs:\n  - name: Clip\n    file: clip.mp4\n    video: visuals.mp4\n    mute: true\n    bpm: 120\n  - name: Repeat\n    file: clip.mp4\n    video: visuals.mp4\n    bpm: 120\n')
    monkeypatch.setattr(bundle, 'SIZE_WARNING_BYTES', 1)
    output = tmp_path / 'show.zip'
    export_bundle(path, output)
    assert 'exceeds 1 GB' in caplog.text
    with zipfile.ZipFile(output) as archive:
        assert sorted(archive.namelist()) == ['clip.mp4', 'set.yaml', 'visuals.mp4']
        archive.extractall(tmp_path / 'stage')
    song = load_setlist(tmp_path / 'stage' / 'set.yaml').songs[0]
    assert song.video == tmp_path / 'stage' / 'visuals.mp4'
    assert song.mute and song.video.read_bytes() == other.read_bytes()
    other.unlink()
    with pytest.raises(BundleError, match='video file does not exist'):
        export_bundle(path, tmp_path / 'missing.zip')


def test_video_window_follows_pause_seek_gap_and_remembers_geometry(qtbot, tmp_path, clip):
    song = Song('clip', clip, 120)
    position = [Position(0, .25, True)]
    audio = SimpleNamespace(position=lambda: position[0], setlist=Setlist('show', (song,)))
    settings = QSettings(str(tmp_path / 'video.ini'), QSettings.IniFormat)
    window = VideoWindow(settings)
    qtbot.addWidget(window, before_close_func=lambda _: window.stop())
    window.start(audio)
    qtbot.waitUntil(lambda: not window.image.isNull())
    assert window.picture.pts == pytest.approx(.2)
    rendered = window.grab().toImage()
    assert rendered.pixelColor(rendered.width() // 2, rendered.height() // 2).red() == pytest.approx(60, abs=3)
    position[0] = replace(position[0], playing=False)
    qtbot.wait(50)
    assert window.picture.pts == pytest.approx(.2)
    position[0] = replace(position[0], song_time=.05, epoch=1)
    qtbot.waitUntil(lambda: window.picture is not None and window.picture.pts == 0)
    assert window.isFullScreen()
    qtbot.keyClick(window, Qt.Key_Escape)
    assert not window.isFullScreen()
    window.resize(640, 360)
    window.close()
    assert not window.isVisible()
    assert settings.value('video/screen') == window.screen().name()
    assert settings.value('video/geometry') is not None
    window.reveal()
    assert window.isVisible()
    position[0] = replace(position[0], gap=True)
    window.refresh()
    assert window.image.isNull() and not window.isVisible()
    position[0] = replace(position[0], gap=False, ended=True)
    window.refresh()
    assert not window.isVisible()
    window.stop()
    restored = VideoWindow(settings)
    qtbot.addWidget(restored)
    assert restored.size().width() == 640


def test_projector_defaults_to_fullscreen_and_keeps_windowed_escape(qtbot, tmp_path, clip):
    settings = QSettings(str(tmp_path / 'fullscreen.ini'), QSettings.IniFormat)
    audio = SimpleNamespace(position=lambda: Position(0, .25, True),
                            setlist=Setlist('show', (Song('clip', clip, 120),)))
    window = VideoWindow(settings)
    qtbot.addWidget(window, before_close_func=lambda _: window.stop())
    assert not window.isVisible()
    window.start(audio)
    qtbot.waitUntil(lambda: window.isVisible())
    assert window.isFullScreen()
    assert window.windowFlags() & Qt.FramelessWindowHint
    assert window.windowFlags() & Qt.WindowStaysOnTopHint
    screen = window.screen()
    qtbot.keyClick(window, Qt.Key_Escape)
    assert window.isVisible() and not window.isFullScreen()
    assert not window.windowFlags() & Qt.FramelessWindowHint
    assert not window.windowFlags() & Qt.WindowStaysOnTopHint
    window.resize(640, 360)
    # Use the action behind F11 (shortcut focus is platform-dependent offscreen).
    window.fullscreen.trigger()
    assert window.isFullScreen() and window.screen() == screen
    window.stop()
    assert not window.isVisible()
    window.start(audio)
    qtbot.waitUntil(lambda: window.isVisible())
    assert window.isFullScreen()
    window.stop()
    restored = VideoWindow(settings)
    qtbot.addWidget(restored, before_close_func=lambda _: restored.stop())
    assert restored.size().width() == 640
    assert restored.screen() == screen
    restored.start(audio)
    qtbot.waitUntil(lambda: restored.isVisible())
    assert restored.isFullScreen()
    restored.fullscreen.trigger()
    assert not restored.isFullScreen() and restored.size().width() == 640


def test_projector_hides_at_video_end_while_audio_continues(qtbot, tmp_path, clip):
    tone = Path(__file__).parent / 'fixtures' / 'tone.wav'
    songs = (Song('separate video', tone, 120, video=clip), Song('audio only', tone, 120))
    position = [Position(0, .25, True)]
    audio = SimpleNamespace(position=lambda: position[0], setlist=Setlist('show', songs))
    window = VideoWindow(QSettings(str(tmp_path / 'end.ini'), QSettings.IniFormat))
    qtbot.addWidget(window, before_close_func=lambda _: window.stop())
    window.start(audio)
    qtbot.waitUntil(lambda: window.isVisible())
    position[0] = replace(position[0], song_time=1.5)
    window.refresh()
    assert not window.isVisible() and window.image.isNull()
    assert audio.position().playing and not audio.position().ended
    window.reveal()
    assert not window.isVisible()
    position[0] = replace(position[0], song_time=.25, epoch=1)
    qtbot.waitUntil(lambda: window.isVisible())
    assert window.isFullScreen()
    window.close()
    window.refresh()
    assert not window.isVisible()
    window.reveal()
    assert window.isVisible()
    position[0] = replace(position[0], song_index=1, epoch=2)
    window.refresh()
    assert not window.isVisible()
    position[0] = replace(position[0], song_index=0, epoch=3)
    qtbot.waitUntil(lambda: window.isVisible())
    assert window.isFullScreen()


def test_projector_holds_last_frame_through_decoder_drought(qtbot, tmp_path, clip):
    """A decoder running behind mid-video must not hide the projector: hiding
    re-reveals a tick later, every reveal raises, and repeated raising is a
    visible stacking war against fullscreen Keyframes (task 144). Only a
    published end at or before the current time makes the blank authoritative."""
    song = Song('clip', clip, 120)
    position = [Position(0, .25, True)]
    audio = SimpleNamespace(position=lambda: position[0], setlist=Setlist('show', (song,)))
    window = VideoWindow(QSettings(str(tmp_path / 'drought.ini'), QSettings.IniFormat))
    qtbot.addWidget(window, before_close_func=lambda _: window.stop())

    class FakeWorker:
        result = None
        def submit(self, key, seconds=0):
            pass
        def close(self):
            pass

    window.audio = audio
    window.worker = FakeWorker()
    reveals = []
    real_show = window.show_projector
    window.show_projector = lambda: (reveals.append(True), real_show())[1]
    key = (clip, True, 0, 0)
    frame = Picture(.2, .3, np.zeros((48, 64, 3), dtype=np.uint8))
    window.refresh()
    assert not window.isVisible(), 'no frame published yet: stay hidden'
    FakeWorker.result = (key, (frame,), 1.0)
    window.refresh()
    assert window.isVisible() and window.picture is frame
    assert len(reveals) == 1
    # Drought: playback has run past every published frame, but the video is
    # not over. The projector must keep the last frame up, not hide.
    position[0] = replace(position[0], song_time=.5)
    window.refresh()
    assert window.isVisible() and window.picture is frame
    assert not window.image.isNull()
    # The worker catches up: the fresh frame replaces the held one in place,
    # with no hide/reveal cycle and therefore no second raise.
    caught_up = Picture(.5, .6, np.zeros((48, 64, 3), dtype=np.uint8))
    FakeWorker.result = (key, (caught_up,), 1.0)
    window.refresh()
    assert window.isVisible() and window.picture is caught_up
    assert len(reveals) == 1, 'holding through the drought must not re-reveal'
    # Past the published end the blank is authoritative: video over, hide.
    position[0] = replace(position[0], song_time=1.25)
    window.refresh()
    assert not window.isVisible() and window.image.isNull()
    # A failed decode publishes end 0.0, which also hides immediately.
    position[0] = replace(position[0], song_time=.75)
    FakeWorker.result = (key, (), 0.0)
    window.refresh()
    assert not window.isVisible()
    window.worker = None
    window.timer.stop()


def test_main_window_starts_and_stops_video(window_factory, clip, qtbot):
    document = Document(rows=[Row('clip', clip, 120)])
    window = window_factory(document)
    window.play()
    qtbot.waitUntil(lambda: not window.video_window.image.isNull())
    assert window.video_window.isVisible()
    window.stop()
    assert not window.video_window.isVisible()
    assert window.video_window.worker is None


def test_high_frame_rate_lookahead_is_bounded_and_ready_before_pts(tmp_path):
    path = make_video(tmp_path / 'fast.mp4', audio=False, rate=60)
    reader = VideoReader(path)
    try:
        pictures = reader.pictures_at(0)
        assert 5 <= len(pictures) <= 8
        # A 16 ms UI timer can select the due frame without waiting for a decode.
        due = [p for p in pictures if p.pts <= .04 < p.until]
        assert len(due) == 1 and due[0].pts == pytest.approx(2 / 60)
        pictures = reader.pictures_at(.035)
        assert 5 <= len(pictures) <= 8
        assert pictures[0].pts == pytest.approx(2 / 60)
        pictures = reader.pictures_at(.9)
        assert pictures[0].pts == pytest.approx(.9)
        assert len(pictures) <= 8
        assert reader.pictures_at(.1)[0].pts == pytest.approx(.1)
    finally:
        reader.close()


def test_mpeg_duration_includes_frames_after_last_keyframe(tmp_path):
    path = tmp_path / 'movie.mpeg'
    with av.open(str(path), 'w', format='mpeg') as output:
        video = output.add_stream('mpeg2video', rate=25)
        video.width, video.height, video.pix_fmt = 64, 48, 'yuv420p'
        for index in range(25):
            frame = av.VideoFrame.from_ndarray(np.full((48, 64, 3), index * 8, dtype='uint8'), format='rgb24')
            frame.pts, frame.time_base = index, Fraction(1, 25)
            for packet in video.encode(frame):
                output.mux(packet)
        for packet in video.encode(None):
            output.mux(packet)
    with Decoder.open(path) as decoder:
        assert decoder.duration == pytest.approx(1)
        assert decoder.frames == RATE
    reader = VideoReader(path)
    try:
        assert reader.frame_at(.97).pts == pytest.approx(.96)
        assert reader.frame_at(.25).pts == pytest.approx(.24)
    finally:
        reader.close()


def test_transport_skip_audio_only_song_and_restart_reseek_video(qtbot, tmp_path, clip):
    tone = Path(__file__).parent / 'fixtures' / 'tone.wav'
    songs = (Song('video', clip, 120), Song('audio', tone, 120))
    now = [0.0]
    engine = AudioEngine(Setlist('show', songs), now=lambda: now[0])
    window = VideoWindow(QSettings(str(tmp_path / 'transport.ini'), QSettings.IniFormat))
    qtbot.addWidget(window, before_close_func=lambda _: window.stop())
    try:
        engine.prepare()
        engine._requested = (True, 0, 0)
        callback(engine, 14400)
        now[0] = .25
        window.start(engine)
        qtbot.waitUntil(lambda: window.picture is not None)
        assert window.picture.pts == pytest.approx(.2)
        engine.toggle_pause()
        callback(engine, 480)
        qtbot.waitUntil(lambda: window.picture is not None and window.picture.pts == pytest.approx(.3))
        engine.skip()
        wait_for(lambda: engine._skip_ready == engine._requested[1])
        callback(engine, 480)
        window.refresh()
        assert window.image.isNull() and not window.isVisible()
        engine.restart()
        wait_for(lambda: engine._skip_ready == engine._requested[1])
        callback(engine, 480)
        qtbot.waitUntil(lambda: window.picture is not None and window.picture.pts == 0)
        assert window.isVisible()
    finally:
        window.stop()
        engine.close()


def test_hidden_reveal_reresolves_remembered_screen_not_current(qtbot, tmp_path, monkeypatch):
    """Task 140: while hidden, the window's own screen tracks the editor
    (transient parent), so show_projector must re-resolve the remembered
    monitor on every reveal instead of trusting self.screen()."""
    settings = QSettings(str(tmp_path / 'pin.ini'), QSettings.IniFormat)
    window = VideoWindow(settings)
    qtbot.addWidget(window, before_close_func=lambda _: window.stop())
    resolved = []
    real = window.remembered_screen

    def spy():
        resolved.append(True)
        return real()

    monkeypatch.setattr(window, 'remembered_screen', spy)
    assert not window.isVisible()
    window.show_projector()
    assert resolved, 'hidden reveal must resolve the remembered/primary screen'
    # A visible toggle keeps the screen the user put it on: no re-resolve.
    resolved.clear()
    window.toggle_fullscreen()
    assert not resolved
    window.hide()
