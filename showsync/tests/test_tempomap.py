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
