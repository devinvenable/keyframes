"""Real Decoder fixtures plus deterministic worker lifecycle/race checks."""
from pathlib import Path
import runpy
import threading

import numpy as np
import pytest
import soundfile as sf

from showsync.bpmdetect import BeatGrid, Cancelled, Suggestions, estimate_bpm, estimate_grid
from showsync.document import Row


@pytest.fixture(scope='module')
def demos(tmp_path_factory):
    directory = tmp_path_factory.mktemp('bpm-demos')
    script = Path(__file__).parents[1] / 'demo' / 'make_demo.py'
    runpy.run_path(str(script))['main'](directory)
    # A reproducible, beatless ambient bed, not silence disguised as noise.
    rng = np.random.default_rng(74)
    noise = rng.normal(0, .08, 48000 * 20)
    sf.write(directory / 'ambient.wav', noise, 48000)
    return directory


@pytest.mark.parametrize('name, expected', [('100', 100), ('140', 140)])
def test_demo_accuracy(demos, name, expected):
    assert estimate_bpm(demos / f'demo-{name}.wav') == pytest.approx(expected, abs=2)


def test_ambient_has_no_estimate(demos):
    assert estimate_bpm(demos / 'ambient.wav') is None


def test_cancel_closes_decoder(monkeypatch):
    from showsync import bpmdetect
    closed = []
    class Decoder:
        samplerate = 48000
        duration = 100
        def __enter__(self):
            return self
        def __exit__(self, *args):
            closed.append(True)
        def read(self, count):
            return np.empty((0, 2))
    monkeypatch.setattr(bpmdetect.Decoder, 'open', lambda path: Decoder())
    with pytest.raises(Cancelled):
        estimate_bpm('unused', cancelled=lambda: True)
    assert closed == [True]


def test_worker_serial_identity_manual_delete_and_failure():
    entered, release = threading.Event(), threading.Event()
    calls = []
    def estimator(path, *, cancelled):
        calls.append(path)
        entered.set()
        assert release.wait(2)
        if path == Path('bad'):
            raise ValueError('cannot decode')
        return 118.5
    saved = Row('saved', Path('saved'), 99)
    manual = Row('manual', Path('manual'), None)
    removed = Row('removed', Path('removed'), None)
    keep = Row('keep', Path('keep'), None)
    bad = Row('bad', Path('bad'), None)
    rows = [saved, manual, removed, keep, bad]
    worker = Suggestions(estimator)
    try:
        assert worker.update(rows) == []
        assert entered.wait(2)
        assert worker.state(manual) == 'analyzing'
        assert worker.state(keep) == 'queued'
        assert calls == [Path('manual')]
        worker.manual(manual)  # even an empty in-progress edit must win
        rows.remove(removed)
        rows.reverse()
        release.set()
        worker.worker.join(2)
        worker.update(rows)  # schedules bad after reorder
        worker.worker.join(2)
        worker.update(rows)  # schedules keep after failure
        worker.worker.join(2)
        changed = worker.update(rows)
        assert changed == [keep]
        assert keep.bpm == 118.5 and worker.state(keep) == 'estimated'
        assert manual.bpm is None and saved.bpm == 99 and removed.bpm is None
        assert worker.state(bad) == 'no estimate'
        assert calls == [Path('manual'), Path('bad'), Path('keep')]
    finally:
        release.set()
        worker.close()


def test_close_cancels_active_work_and_never_starts_queue():
    entered = threading.Event()
    calls = []
    def estimator(path, *, cancelled):
        calls.append(path)
        entered.set()
        # close must set cancellation before joining (no decoding during play).
        assert worker.halt.wait(2)
        assert cancelled()
        raise Cancelled
    rows = [Row(str(i), Path(str(i)), None) for i in range(2)]
    worker = Suggestions(estimator)
    worker.update(rows)
    assert entered.wait(2)
    worker.close()
    assert worker.halt.is_set()
    assert not worker.worker.is_alive()
    assert calls == [Path('0')]
    assert worker.results.empty()


def test_deleted_active_row_does_not_fill_replacement():
    release = threading.Event()
    def estimator(path, *, cancelled):
        assert release.wait(2)
        return 120.0
    deleted = Row('same', Path('same.wav'), None)
    replacement = Row('same', Path('same.wav'), None)
    worker = Suggestions(estimator)
    try:
        worker.update([deleted])
        release.set()
        worker.worker.join(2)
        assert worker.update([replacement]) == []
        assert deleted.bpm is None and replacement.bpm is None
    finally:
        release.set()
        worker.close()


def test_ramp_is_not_misrepresented_as_a_constant_grid(demos):
    assert estimate_grid(demos / 'demo-ramp.wav') is None


def test_cropped_first_attack_fits_in_wav_and_mp3():
    # Same 120 BPM signal cut 15 ms into a kick, generated independently of
    # the detector by scripts/make_cropped_beat_fixtures.py. The fitted first
    # pulse precedes the file by less than one MIDI tick in both containers.
    fixtures = Path(__file__).parent / 'fixtures'
    grids = [estimate_grid(fixtures / f'cropped-beat.{ext}')
             for ext in ('wav', 'mp3')]
    for grid in grids:
        assert grid is not None
        assert grid.bpm == pytest.approx(120, abs=.01)
        assert grid.offset == 0
    assert grids[0].bpm == pytest.approx(grids[1].bpm, abs=.01)


def test_cropped_attack_tolerance_scales_with_clock_tick():
    from showsync.bpmdetect import _fit

    for period in (.31, .5, .9):
        # The first observed onset is the clipped tail at t=0; the remaining
        # onsets establish a pulse just before the cut. Keep all rhythm checks
        # satisfied while straddling the single-tick boundary (1/24 beat).
        for cut, accepted in [(.035, True), (.047, False)]:
            times = (np.arange(32) - cut) * period
            times[0] = 0
            weights = np.ones(32)
            weights[0] = .2
            result = _fit(times, weights, 1 / period, lambda: None)
            if accepted:
                assert result is not None
                assert result[1].offset == 0
            else:
                assert result is None


def rhythmic_file(path, bpm, offset, seconds=240, *, busy=False, rate=48000):
    """Known beat times independent of the detector and playback tempo map."""
    rng = np.random.default_rng(89)
    audio = np.zeros(round(seconds * rate), dtype=np.float32)
    beats = np.arange(offset, seconds - .1, 60 / bpm)
    t = np.arange(round(.04 * rate)) / rate
    kick = .7 * np.sin(2 * np.pi * 90 * t) * np.exp(-t * 100)
    hat = rng.normal(0, .08, len(t)) * np.exp(-t * 200)
    for i, beat in enumerate(beats):
        # Missing beats, changing accents, offbeat hats and a quiet background
        # exercise regression against more than identical isolated impulses.
        if not busy or i % 13 != 8:
            start = round(beat * rate)
            audio[start:start + len(kick)] += kick * (1 if i % 4 == 0 else .7)
        if busy:
            start = round((beat + 30 / bpm) * rate)
            end = min(len(audio), start + len(hat))
            if end > start:
                audio[start:end] += hat[:end-start]
    if busy:
        audio += .001 * rng.normal(size=len(audio)).astype(np.float32)
    sf.write(path, audio, rate)
    return beats


@pytest.mark.parametrize('bpm, offset, busy, rate', [
    (112.37, 0, False, 48000), (137.123, .237, True, 44100),
    (73.891, 2.183, True, 48000), (179.731, .419, False, 48000),
])
def test_full_song_precision_and_tick_counting_slave(tmp_path, bpm, offset, busy, rate):
    from showsync.tempomap import TempoMap
    path = tmp_path / 'precise.wav'
    beats = rhythmic_file(path, bpm, offset, busy=busy, rate=rate)
    grid = estimate_grid(path)
    assert grid is not None
    assert grid.offset == pytest.approx(offset, abs=.01)
    assert grid.bpm == pytest.approx(bpm, abs=.003)
    assert abs(grid.bpm - bpm) * 240 / 60 < .02  # end-to-end tempo drift in beats
    tempo = TempoMap(grid.bpm, offset=grid.offset)
    # Slave advances one step for each 24 received F8 ticks. Use all scheduled
    # tick times, not rounded BPM labels; compare each step with fixture audio.
    ticks = np.array([tempo.T(k / 24) for k in range(len(beats) * 24)])
    slave_steps = ticks[::24]
    assert np.max(np.abs(slave_steps - beats)) * bpm / 60 < .05
    assert abs((slave_steps[-1] - beats[-1]) - (slave_steps[0] - beats[0])) * bpm / 60 < .02


@pytest.mark.parametrize('kind', ['silence', 'tone', 'irregular'])
def test_nonrhythmic_audio_is_inconclusive(tmp_path, kind):
    rate = 48000
    audio = np.zeros(rate * 30, dtype=np.float32)
    if kind == 'tone':
        audio = (.1 * np.sin(2 * np.pi * 440 * np.arange(len(audio)) / rate)).astype(np.float32)
    elif kind == 'irregular':
        rng = np.random.default_rng(891)
        for start in rng.integers(0, len(audio) - 2000, 45):
            audio[start:start + 2000] += rng.normal(0, .1, 2000) * np.exp(-np.arange(2000) / 200)
    path = tmp_path / 'nonrhythmic.wav'
    sf.write(path, audio, rate)
    assert estimate_grid(path) is None


@pytest.mark.parametrize('explicit, offset, expected', [(False, 0, .237), (True, 0, 0), (False, .5, .5)])
def test_grid_suggestion_respects_offset_intent(explicit, offset, expected):
    row = Row('Song', Path('song'), None, offset=offset, offset_explicit=explicit)
    worker = Suggestions(lambda *a, **kw: BeatGrid(112.371234, .237))
    try:
        worker.update([row])
        worker.worker.join(2)
        assert worker.update([row]) == [row]
        assert row.bpm == 112.371234
        assert row.offset == expected
    finally:
        worker.close()


def test_tempo_change_outside_old_analysis_window_is_inconclusive(tmp_path):
    first, second = tmp_path / 'first.wav', tmp_path / 'second.wav'
    rhythmic_file(first, 112.37, 0, seconds=180)
    rhythmic_file(second, 119.23, 0, seconds=60)
    a, rate = sf.read(first)
    b, _ = sf.read(second)
    path = tmp_path / 'change.wav'
    sf.write(path, np.concatenate((a, b)), rate)
    assert estimate_grid(path) is None
