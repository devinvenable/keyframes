import math

import pytest
from hypothesis import given, strategies as st

from showsync.tempomap import TempoEvent as E, TempoMap


def test_constant_and_jump():
    tempo = TempoMap(120, [E(10, 60)])
    assert tempo.B(10) == 20
    assert tempo.B(12) == 22
    assert tempo.T(22) == 12
    assert tempo.bpm_at(9.999) == 120
    assert tempo.bpm_at(10) == 60


def test_analytic_ramp_and_gap_tail():
    tempo = TempoMap(120, [E(20, 140, 45)])
    assert tempo.B(65) == pytest.approx(40 + 97.5)
    assert tempo.bpm_at(42.5) == 130
    assert tempo.ramp_target(42.5) == 140
    assert tempo.ramp_target(65) is None
    assert tempo.B(68) - tempo.B(65) == pytest.approx(7)


@given(st.floats(1, 400), st.floats(1, 400), st.floats(.001, 300), st.floats(0, 1))
def test_round_trip_property(start, end, duration, fraction):
    tempo = TempoMap(start, [E(1, end, duration), E(duration + 2, start)])
    for t in (0, 1, 1 + fraction * duration, 1 + duration, 2 + duration, 10 + duration):
        assert tempo.T(tempo.B(t)) == pytest.approx(t, rel=2e-10, abs=1e-9)
    assert tempo.B(1 + duration) - tempo.B(1) == pytest.approx(duration * (start + end) / 120)


def test_near_flat_inverse_is_stable():
    tempo = TempoMap(120, [E(0, 120 + 1e-10, 30)])
    assert tempo.T(tempo.B(12.345)) == pytest.approx(12.345, abs=1e-12)


@pytest.mark.parametrize('events', [[E(2, 120), E(1, 90)], [E(1, 120), E(1, 90)],
                                    [E(1, 130, 3), E(2, 90)], [E(0, 0)],
                                    [E(-1, 120)], [E(0, math.inf)], [E(0, 120, -1)],
                                    [E(0, 120, math.nan)], [E(10, 120)], [E(8, 100, 3)]])
def test_reject_bad_events(events):
    with pytest.raises(ValueError):
        TempoMap(120, events, duration=10)


@pytest.mark.parametrize('value', [-1, math.inf, math.nan])
def test_reject_bad_positions(value):
    for method in (TempoMap(120).B, TempoMap(120).T, TempoMap(120).bpm_at):
        with pytest.raises(ValueError):
            method(value)


def test_offset_anchors_beat_zero():
    tempo = TempoMap(120, offset=2.5)
    assert tempo.T(0) == 2.5
    assert tempo.B(2.5) == 0
    assert tempo.B(0) == 0          # lead-in accumulates no beats
    assert tempo.B(1.0) == 0
    assert tempo.bpm_at(0) == 120   # GUI readout during the lead-in
    assert tempo.B(2.5 + 30) == pytest.approx(60)
    assert tempo.T(60) == pytest.approx(32.5)


def test_offset_with_ramp_positions_stay_absolute():
    plain = TempoMap(120, [E(20, 140, 45)])
    shifted = TempoMap(120, [E(20, 140, 45)], offset=5)
    # Event times are absolute file positions; only beat 0 moves.
    assert shifted.bpm_at(42.5) == plain.bpm_at(42.5) == 130
    assert shifted.B(65) == pytest.approx(plain.B(65) - plain.B(5))
    assert shifted.T(shifted.B(33.3)) == pytest.approx(33.3, abs=1e-9)


@pytest.mark.parametrize('kwargs', [dict(offset=-1), dict(offset=math.nan),
                                    dict(offset=math.inf), dict(offset=10, duration=10),
                                    dict(offset=11, duration=10)])
def test_reject_bad_offsets(kwargs):
    with pytest.raises(ValueError, match='offset'):
        TempoMap(120, **kwargs)


@pytest.mark.parametrize('at', [1, 1.999])
def test_reject_events_inside_lead_in(at):
    with pytest.raises(ValueError, match='first-beat offset'):
        TempoMap(120, [E(at, 140)], offset=2)


def test_ramp_may_begin_exactly_at_beat_zero():
    # A whole-song glide: the ramp starts on the first-beat offset itself.
    tempo = TempoMap(120, [E(2, 140, 10)], offset=2, duration=20)
    assert tempo.bpm_at(2) == 120
    assert tempo.bpm_at(12) == 140
    assert tempo.ramp_target(7) == 140
