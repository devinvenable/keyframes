"""Real Decoder fixtures plus deterministic worker lifecycle/race checks."""
from pathlib import Path
import runpy
import threading

import numpy as np
import pytest
import soundfile as sf

from showsync.bpmdetect import Cancelled, Suggestions, estimate_bpm
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


@pytest.mark.parametrize('name, expected', [('100', 100), ('140', 140), ('ramp', 140)])
def test_demo_accuracy(demos, name, expected):
    # Ramp chooses the dominant 140 BPM section, not a ramp reconstruction.
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
