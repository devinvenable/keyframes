"""Full-file, constant-tempo beat-grid suggestions using NumPy and Decoder.

Audio stays untouched. Decode in small blocks and retain only 100 Hz spectral
flux, 100 Hz kick-band power and 1 kHz power, not the waveform. A fine periodicity
search removes lag quantization; robust regression fits beat times over the
entire rhythmic span.
Changing tempo / weak or inconsistent grids are inconclusive. Beat zero is the
first supported pulse, not a claim about musical meter or bar numbering.
"""
from dataclasses import dataclass
import threading
from queue import Queue, Empty

import numpy as np

from .audio import Decoder


class Cancelled(Exception):
    pass


@dataclass(frozen=True)
class BeatGrid:
    bpm: float
    offset: float
    # True when only a steady section supports the grid (windowed fallback);
    # tempo is trustworthy there but intro/outro may not follow it.
    partial: bool = False


def _features(path, check):
    flux, power, kick_power = [], [], []
    previous = np.zeros(257)
    pending = np.zeros(512 - 120, dtype=np.float32)
    window = np.hanning(512)
    kick_bins = np.fft.rfftfreq(512, 1 / 12000) < 280
    with Decoder.open(path) as decoder:
        while True:
            check()
            block = decoder.read(12000)
            if not len(block):
                break
            # 48 kHz engine frames; channel power avoids antiphase cancellation.
            mono_power = np.mean(block ** 2, axis=1)
            n = len(block) // 48 * 48
            power.append(mono_power[:n].reshape(-1, 48).mean(axis=1))
            mono = block.mean(axis=1)
            mono = mono[:len(mono) // 4 * 4].reshape(-1, 4).mean(axis=1)
            pending = np.concatenate((pending, mono))
            if len(pending) < 512:
                continue
            windows = np.lib.stride_tricks.sliding_window_view(pending, 512)[::120]
            magnitudes = np.abs(np.fft.rfft(windows * window))
            kick_power.append((magnitudes[:, kick_bins] ** 2).sum(axis=1))
            spectra = np.log1p(magnitudes)
            differences = np.diff(np.vstack((previous, spectra)), axis=0)
            flux.append(np.maximum(differences, 0).sum(axis=1))
            previous = spectra[-1]
            pending = pending[len(windows) * 120:]
    return (np.concatenate(flux) if flux else np.empty(0),
            np.concatenate(power) if power else np.empty(0),
            np.concatenate(kick_power) if kick_power else np.empty(0))


def _onsets(envelope, power, check=lambda: None):
    floor = np.median(envelope)
    if np.percentile(envelope, 99) < max(1e-8, floor * 2):
        return None
    envelope = np.maximum(envelope - floor, 0)
    peaks = np.flatnonzero((envelope >= np.roll(envelope, 1)) &
                           (envelope > np.roll(envelope, -1)) &
                           (envelope > np.percentile(envelope, 95) * .15))
    times, weights = [], []
    for i, peak in enumerate(peaks):
        if i % 128 == 0:
            check()
        # Flux window center is 11.3 ms before its frame timestamp. Locate the
        # energy attack locally, so the FFT window does not bias beat zero.
        center = round(peak * 10 - (392 - 256) / 12)
        lo, hi = max(0, center - 25), min(len(power), center + 35)
        if hi - lo < 5:
            continue
        local = power[lo:hi]
        baseline = np.min(local)
        threshold = baseline + .08 * (np.max(local) - baseline)
        crossings = np.flatnonzero(local > threshold)
        if not len(crossings):
            continue
        time = (lo + crossings[0]) / 1000
        weight = envelope[peak] * np.sqrt(max(0, np.max(local) - baseline))
        if times and time - times[-1] < .05:
            if weight > weights[-1]:
                times[-1], weights[-1] = time, weight
        else:
            times.append(time)
            weights.append(weight)
    return envelope, np.asarray(times), np.asarray(weights)


def _candidates(envelope):
    envelope = envelope - envelope.mean()
    size = 1 << (2 * len(envelope) - 1).bit_length()
    spectrum = np.fft.rfft(envelope, size)
    ac = np.fft.irfft(spectrum * spectrum.conj(), size)[:102]
    ac /= np.maximum(1, len(envelope) - np.arange(len(ac)))
    if ac[0] <= 1e-10:
        return []
    ac /= ac[0]
    candidates = []
    for lag in range(30, 101):
        if ac[lag] > ac[lag - 1] and ac[lag] >= ac[lag + 1] and ac[lag] > .15:
            shift = .5 * (ac[lag - 1] - ac[lag + 1]) / (ac[lag - 1] - 2 * ac[lag] + ac[lag + 1])
            candidates.append(100 / (lag + shift))
    return candidates


def _fit(times, weights, frequency, check):
    span = times[-1] - times[0]
    # Grid spacing bounds trial phase drift to 0.05 beat across the whole file.
    frequencies = np.arange(max(1, frequency - .025), min(200 / 60, frequency + .025),
                            .05 / span)
    if not len(frequencies):
        return None
    best = None
    for start in range(0, len(frequencies), 64):
        check()
        trial = frequencies[start:start + 64]
        phases = np.exp(2j * np.pi * trial[:, None] * times)
        coherence = phases @ weights / weights.sum()
        index = np.argmax(np.abs(coherence))
        score = abs(coherence[index])
        if best is None or score > best[0]:
            best = score, trial[index], np.angle(coherence[index]) / (2 * np.pi)
    score, frequency, phase = best
    period, offset = 1 / frequency, phase / frequency
    for _ in range(5):
        check()
        beats = np.rint((times - offset) / period)
        residual = times - (offset + beats * period)
        mask = np.abs(residual) < period * .08
        if mask.sum() < 12:
            return None
        x, y, w = beats[mask], times[mask], weights[mask]
        # Downweight outliers while retaining genuine timing scatter.
        w = w / np.maximum(1, np.abs(residual[mask]) / .008)
        xmean, ymean = np.average(x, weights=w), np.average(y, weights=w)
        period = np.sum(w * (x - xmean) * (y - ymean)) / np.sum(w * (x - xmean) ** 2)
        offset = ymean - period * xmean
    residual = times - (offset + beats * period)
    mask = np.abs(residual) < period * .05
    if mask.sum() < 12 or weights[mask].sum() / weights.sum() < .35:
        return None
    # Every part of the rhythmic span must support the same grid. This rejects
    # a dominant steady section hiding a ramp or a tempo change elsewhere.
    for section in np.array_split(np.arange(len(times)), 8):
        check()
        good = section[mask[section]]
        if (len(good) < 2 or weights[good].sum() / weights[section].sum() < .25
                or abs(np.median(residual[good])) > period * .025):
            return None
    if np.quantile(np.abs(residual[mask]), .9) > period * .035:
        return None
    # Require many distinct supported beats, not just sparse accidental hits.
    supported = np.unique(beats[mask])
    if len(supported) / (supported[-1] - supported[0] + 1) < .45:
        return None
    first = offset + supported[0] * period
    # A file trimmed into its first attack can place the fitted pulse just
    # before zero. Allow at most one MIDI clock tick of boundary uncertainty;
    # the full-span rhythm and residual checks above still have to pass.
    if first < -period / 24:
        return None
    return float(score), BeatGrid(float(60 / period), float(max(0, first)))


def _analyze(envelope, power, check):
    """Fit one constant grid to a feature span; return (score, BeatGrid) or None."""
    if len(envelope) < 600 or not len(power) or np.max(power) < 1e-10:
        return None
    onsets = _onsets(envelope, power, check)
    if onsets is None:
        return None
    envelope, times, weights = onsets
    if len(times) < 16 or times[-1] - times[0] < 6:
        return None
    if weights.sum() <= 0:
        return None
    weights = np.minimum(weights, np.percentile(weights, 90))
    fits = []
    for frequency in _candidates(envelope):
        result = _fit(times, weights, frequency, check)
        if result is not None:
            fits.append(result)
    if not fits:
        return None
    strongest = max(score for score, grid in fits)
    if strongest < .12:
        return None
    tied = [(score, grid) for score, grid in fits if score >= strongest * .93]
    score, grid = max(tied, key=lambda item: (90 <= item[1].bpm <= 180, item[1].bpm))
    # Strong alternating beats can mean a slow pulse with weak offbeat hats.
    # Favor half-time only when its pulses carry >75% of the double-time energy;
    # an evenly accented click track keeps its actual pulse rate.
    def support(candidate):
        phase = (times - candidate.offset) * candidate.bpm / 60
        return weights[np.abs(phase - np.rint(phase)) < .05].sum()

    for fit_score, candidate in fits:
        if (abs(candidate.bpm * 2 - grid.bpm) < .02
                and support(candidate) > .75 * support(grid)):
            score, grid = fit_score, candidate
    check()
    return score, grid


# Fallback windows: long enough for a solid fit, overlapped so a steady
# section shorter than the file still covers several independent starts.
_WINDOW = 60.0
_HOP = 30.0
_CLUSTER_TOLERANCE = .005  # windows agree when tempos match within 0.5%
_MINIMUM_WINDOWS = 3


def _phase_support(kick_power, period, spans, phase):
    """Low-band spectral power near grid pulses across the agreeing spans."""
    total = 0.0
    for start, stop in spans:
        beats = np.arange(np.ceil((start - phase) / period),
                          np.floor((stop - phase) / period) + 1)
        if not len(beats):
            continue
        # Spectral frame timestamps run 11.3 ms behind audio time; a small
        # neighborhood max absorbs attack scatter without blurring phases.
        centers = np.rint((phase + beats * period) * 100 + 1.13).astype(int)
        indices = np.clip(centers[:, None] + np.arange(-3, 4), 0, len(kick_power) - 1)
        total += kick_power[indices].max(axis=1).sum()
    return total


def _steady_section(envelope, power, kick_power, check):
    """Partial estimate from overlapping windows of already-computed features.

    Used when no single grid spans the whole file. Windows whose tempos agree
    within a tight tolerance form the steady section; its tempo is reported
    with partial=True and an offset projected back to the start of the song.
    """
    duration = len(power) / 1000
    fits = []
    start = 0.0
    while duration - start >= _WINDOW * .75:
        check()
        stop = min(start + _WINDOW, duration)
        result = _analyze(envelope[int(start * 100):int(stop * 100)],
                          power[int(start * 1000):int(stop * 1000)], check)
        if result is not None:
            fits.append((result[0], start, stop, result[1]))
        start += _HOP
    if len(fits) < _MINIMUM_WINDOWS:
        return None
    bpms = np.array([grid.bpm for _, _, _, grid in fits])
    scores = np.array([score for score, _, _, _ in fits])
    best = None
    for center in bpms:
        members = np.flatnonzero(np.abs(bpms - center) <= center * _CLUSTER_TOLERANCE)
        key = (len(members), scores[members].sum())
        if best is None or key > best[0]:
            best = key, members
    members = best[1]
    if len(members) < _MINIMUM_WINDOWS:
        return None
    bpm = float(np.median(bpms[members]))
    period = 60 / bpm
    spans = [(fits[i][1], fits[i][2]) for i in members]
    # Windows can all lock to the offbeat. Project each window's beat zero
    # and its half-beat alternative back to the song start. Keep the phase that
    # kick power of ALL agreeing windows supports best; strongest window first,
    # so a genuine tie stays with the most confident anchor.
    chosen = None
    for index in sorted(members, key=lambda i: -fits[i][0]):
        check()
        _, start, _, grid = fits[index]
        for shift in (0, period / 2):
            phase = (start + grid.offset + shift) % period
            supported = _phase_support(kick_power, period, spans, phase)
            if chosen is None or supported > chosen[0]:
                chosen = supported, phase
    return BeatGrid(bpm, float(chosen[1]), partial=True)


def estimate_grid(path, *, cancelled=lambda: False):
    """Return a precise BeatGrid or None; check cancellation between small jobs.

    When no single constant grid spans the file, fall back to overlapping
    ~60 s windows over the same features and report the tempo of the
    strongest steady section as a partial estimate (BeatGrid.partial).
    """
    def check():
        if cancelled():
            raise Cancelled

    envelope, power, kick_power = _features(path, check)
    check()
    result = _analyze(envelope, power, check)
    if result is not None:
        return result[1]
    return _steady_section(envelope, power, kick_power, check)


def estimate_bpm(path, *, cancelled=lambda: False):
    """Compatibility helper for callers needing only the refined BPM."""
    grid = estimate_grid(path, cancelled=cancelled)
    return grid.bpm if grid is not None else None


class Suggestions:
    """Single worker; only the GUI thread reads/writes rows and UI state.

    Estimators are injectable callables accepting (path, cancelled=callback).
    Entries retain row identities, so deletion/reorder cannot retarget a result.
    """
    def __init__(self, estimator=estimate_grid):
        self.estimator = estimator
        self.entries = {}  # id -> (row, state); UI-only, never persisted
        self.results = Queue()
        self.halt = threading.Event()
        self.worker = None
        self.generations = {}
        self.replacements = set()
        self.detected = {}
        self.bpm_edits = set()

    def state(self, row):
        return self.entries.get(id(row), (None, 'estimated' if row.bpm_estimated else ''))[1]

    def offset_estimated(self, row):
        return bool(row.offset) and not row.offset_explicit

    def manual(self, row):
        row.bpm_estimated = False
        if id(row) in self.replacements:
            self.bpm_edits.add(id(row))
            return
        self.entries[id(row)] = (row, 'manual')

    def confirm_timing(self, row):
        """Explicit timing intent supersedes even an unfinished replacement scan."""
        key = id(row)
        self.generations[key] = self.generations.get(key, 0) + 1
        self.replacements.discard(key)
        self.bpm_edits.discard(key)
        row.timing_review = ''
        row.offset_explicit = True
        self.manual(row)

    def replaced(self, row):
        key = id(row)
        self.generations[key] = self.generations.get(key, 0) + 1
        self.replacements.add(key)
        self.detected.pop(key, None)
        self.bpm_edits.discard(key)
        self.entries[key] = (row, 'queued')

    def update(self, rows):
        """Apply completed estimates; queue new empty rows; return changed rows."""
        changed = []
        while True:
            try:
                row, generation, value = self.results.get_nowait()
            except Empty:
                break
            if not any(item is row for item in rows) or generation != self.generations.get(id(row), 0):
                continue
            if id(row) in self.replacements:
                self.replacements.remove(id(row))
                self.detected[id(row)] = value
                edited = id(row) in self.bpm_edits
                protected = edited or (row.bpm is not None and not row.bpm_estimated) or row.offset_explicit
                applied = False
                if value is not None:
                    if not edited and (row.bpm is None or row.bpm_estimated):
                        row.bpm = value.bpm if isinstance(value, BeatGrid) else value
                        row.bpm_estimated = True
                        applied = True
                    if isinstance(value, BeatGrid) and not row.offset_explicit:
                        row.offset = value.offset
                row.timing_review = ('inconclusive' if value is None else 'review' if protected else '')
                partial = applied and getattr(value, 'partial', False)
                self.entries[id(row)] = (row, ('partial' if partial else 'estimated')
                                         if row.bpm_estimated else 'manual')
                changed.append(row)
                continue
            if (any(item is row for item in rows) and row.bpm is None
                    and not row.tempo and self.state(row) == 'analyzing'):
                row.bpm = value.bpm if isinstance(value, BeatGrid) else value
                row.bpm_estimated = value is not None
                if (isinstance(value, BeatGrid) and not row.offset_explicit
                        and row.offset == 0 and not row.tempo):
                    row.offset = value.offset
                self.entries[id(row)] = (row, 'no estimate' if value is None else
                                         'partial' if getattr(value, 'partial', False) else 'estimated')
                if value is not None:
                    changed.append(row)
        for row in rows:
            if row.timing_review and id(row) not in self.entries:
                self.replaced(row)
            if id(row) in self.replacements:
                continue
            if row.tempo and self.state(row) in ('queued', 'analyzing'):
                self.manual(row)
            if row.bpm is None and not row.tempo and not row.file_error and id(row) not in self.entries:
                self.entries[id(row)] = (row, 'queued')
        if not self.halt.is_set() and (self.worker is None or not self.worker.is_alive()):
            for row in rows:
                if self.state(row) == 'queued' and (row.bpm is None or id(row) in self.replacements):
                    self.entries[id(row)] = (row, 'analyzing')
                    self.worker = threading.Thread(target=self._estimate,
                                                   args=(row, self.generations.get(id(row), 0), row.file, row.duration),
                                                   name='showsync-bpm', daemon=True)
                    self.worker.start()
                    break
        return changed

    def _estimate(self, row, generation, path, duration):
        try:
            value = self.estimator(path, cancelled=self.halt.is_set)
            if value is not None:
                bpm = value.bpm if isinstance(value, BeatGrid) else value
                if not (np.isfinite(bpm) and 60 <= bpm <= 200):
                    value = None
                elif isinstance(value, BeatGrid) and not (
                        np.isfinite(value.offset) and value.offset >= 0
                        and (duration is None or value.offset < duration)):
                    value = None
        except Cancelled:
            return
        except Exception:
            value = None
        if not self.halt.is_set():
            self.results.put((row, generation, value))

    def close(self):
        self.halt.set()
        if self.worker is not None:
            self.worker.join()
