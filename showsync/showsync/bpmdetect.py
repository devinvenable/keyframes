"""Conservative, bounded tempo suggestions; never a playback tempo authority.

Only NumPy and the playback Decoder are used. Decode sequentially (the MP3
backend deliberately cannot seek), retaining at most 90 seconds from the
middle. Analysis uses 12 kHz mono / 100 Hz positive spectral flux. A weak or
nonperiodic envelope yields None, not a guessed default tempo.
"""
import threading
from queue import Queue, Empty

import numpy as np

from .audio import Decoder


class Cancelled(Exception):
    pass


def estimate_bpm(path, *, cancelled=lambda: False):
    """Return a BPM float or None. Cancellation is checked between small blocks."""
    def check():
        if cancelled():
            raise Cancelled

    chunks = []
    with Decoder.open(path) as decoder:
        rate = decoder.samplerate
        start = max(0, int((decoder.duration - 90) / 2 * rate))
        stop = start + int(min(decoder.duration, 90) * rate)
        cursor = 0
        while cursor < stop:
            check()
            block = decoder.read(min(12000, stop - cursor))
            if not len(block):
                break
            begin = max(0, start - cursor)
            if begin < len(block):
                chunks.append(block[begin:].mean(axis=1))
            cursor += len(block)
    check()
    if not chunks:
        return None
    audio = np.concatenate(chunks)
    # Decoder outputs 48 kHz. Averaging before decimation reduces aliasing.
    factor = rate // 12000
    audio = audio[:len(audio) // factor * factor].reshape(-1, factor).mean(axis=1)
    if len(audio) < 12000 * 6 or np.max(np.abs(audio)) < 1e-5:
        return None
    windows = np.lib.stride_tricks.sliding_window_view(audio, 512)[::120]
    previous = np.zeros(257)
    flux = []
    for begin in range(0, len(windows), 128):
        check()
        spectra = np.log1p(np.abs(np.fft.rfft(windows[begin:begin + 128] * np.hanning(512))))
        differences = np.diff(np.vstack((previous, spectra)), axis=0)
        flux.extend(np.maximum(differences, 0).sum(axis=1))
        previous = spectra[-1]
    envelope = np.asarray(flux)
    # Noise has near-constant flux. Beats must produce distinct transients.
    floor = np.median(envelope)
    if np.percentile(envelope, 99) < max(1e-8, floor * 2.0):
        return None
    envelope = np.maximum(envelope - floor, 0)
    envelope -= envelope.mean()
    check()
    size = 1 << (2 * len(envelope) - 1).bit_length()
    spectrum = np.fft.rfft(envelope, size)
    ac = np.fft.irfft(spectrum * spectrum.conj(), size)[:201]
    ac /= np.maximum(1, len(envelope) - np.arange(len(ac)))
    if ac[0] <= 1e-10:
        return None
    ac /= ac[0]
    # Local peaks suppress adjacent lag duplicates; interpolate to avoid the
    # integer-lag tempo quantization (100 Hz would otherwise miss ~2 BPM).
    candidates = []
    for lag in range(30, 101):
        if ac[lag] > ac[lag - 1] and ac[lag] >= ac[lag + 1]:
            shift = .5 * (ac[lag - 1] - ac[lag + 1]) / (ac[lag - 1] - 2 * ac[lag] + ac[lag + 1])
            bpm = 6000 / (lag + shift)
            if 60 <= bpm <= 200:
                candidates.append((float(ac[lag]), bpm))
    if not candidates:
        return None
    strongest = max(score for score, _ in candidates)
    if strongest < .22:
        return None
    # Near-equal octave peaks favor a practical tapping range. Otherwise keep
    # the strongest periodicity, including genuine slow beats below 90 BPM.
    tied = [(score, bpm) for score, bpm in candidates if score >= strongest * .93]
    score, bpm = max(tied, key=lambda item: (90 <= item[1] <= 180, item[1]))
    check()
    return float(round(bpm, 1))


class Suggestions:
    """Single worker; only the GUI thread reads/writes rows and UI state.

    Estimators are injectable callables accepting (path, cancelled=callback).
    Entries retain row identities, so deletion/reorder cannot retarget a result.
    """
    def __init__(self, estimator=estimate_bpm):
        self.estimator = estimator
        self.entries = {}  # id -> (row, state); UI-only, never persisted
        self.results = Queue()
        self.halt = threading.Event()
        self.worker = None

    def state(self, row):
        return self.entries.get(id(row), (None, ''))[1]

    def manual(self, row):
        self.entries[id(row)] = (row, 'manual')

    def update(self, rows):
        """Apply completed estimates; queue new empty rows; return changed rows."""
        changed = []
        while True:
            try:
                row, value = self.results.get_nowait()
            except Empty:
                break
            if (any(item is row for item in rows) and row.bpm is None
                    and self.state(row) == 'analyzing'):
                row.bpm = value
                self.entries[id(row)] = (row, 'estimated' if value is not None else 'no estimate')
                if value is not None:
                    changed.append(row)
        for row in rows:
            if row.bpm is None and not row.file_error and id(row) not in self.entries:
                self.entries[id(row)] = (row, 'queued')
        if not self.halt.is_set() and (self.worker is None or not self.worker.is_alive()):
            for row in rows:
                if self.state(row) == 'queued' and row.bpm is None:
                    self.entries[id(row)] = (row, 'analyzing')
                    self.worker = threading.Thread(target=self._estimate, args=(row,),
                                                   name='showsync-bpm', daemon=True)
                    self.worker.start()
                    break
        return changed

    def _estimate(self, row):
        try:
            value = self.estimator(row.file, cancelled=self.halt.is_set)
            if value is not None and not (np.isfinite(value) and 60 <= value <= 200):
                value = None
        except Cancelled:
            return
        except Exception:
            value = None
        if not self.halt.is_set():
            self.results.put((row, value))

    def close(self):
        self.halt.set()
        if self.worker is not None:
            self.worker.join()
