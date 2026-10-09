"""Gate verdict of the jitter harness: judged on send-time interval error.

The harness itself needs real devices; evaluate() is pure and tested here with
synthetic timestamp streams.
"""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    'measure_jitter', Path(__file__).resolve().parents[1] / 'scripts' / 'measure_jitter.py')
measure_jitter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(measure_jitter)

TICKS = 200
PERIOD = .02
LATENCY = .0002


def streams(send_offsets=(), receive_offsets=()):
    """Ideal 50 Hz ticks; per-index extra delays in seconds, zero elsewhere."""
    sent, received = [], []
    for i in range(TICKS):
        ideal = 100.0 + i * PERIOD
        tx = ideal + dict(send_offsets).get(i, 0.0)
        sent.append((ideal, tx, i))
        received.append(tx + LATENCY + dict(receive_offsets).get(i, 0.0))
    return sent, received


def test_clean_run_passes():
    result = measure_jitter.evaluate(*streams(), dropped_ticks=0, audio_underruns=0)
    assert result['passed']
    assert result['send_worst_abs_ms'] < .01
    assert len(result['samples']) == TICKS


def test_send_side_spike_fails():
    result = measure_jitter.evaluate(*streams(send_offsets=[(50, .003)]),
                                     dropped_ticks=0, audio_underruns=0)
    assert result['send_worst_abs_ms'] == pytest.approx(3, rel=.01)
    assert not result['passed']


def test_receiver_only_spike_is_diagnostic_not_gate():
    # A cold-start delivery stall at the receiver (the pattern behind every
    # recorded Mac worst-case failure) must not fail the clock's gate.
    result = measure_jitter.evaluate(*streams(receive_offsets=[(1, .02)]),
                                     dropped_ticks=0, audio_underruns=0)
    assert result['interval_worst_abs_ms'] == pytest.approx(20, rel=.01)
    assert result['send_worst_abs_ms'] < .01
    assert result['passed']


def test_dropped_ticks_and_underruns_still_fail():
    assert not measure_jitter.evaluate(*streams(), dropped_ticks=1, audio_underruns=0)['passed']
    assert not measure_jitter.evaluate(*streams(), dropped_ticks=0, audio_underruns=2)['passed']


def test_count_mismatch_raises():
    sent, received = streams()
    with pytest.raises(RuntimeError):
        measure_jitter.evaluate(sent, received[:-1], dropped_ticks=0, audio_underruns=0)
    with pytest.raises(RuntimeError):
        measure_jitter.evaluate(sent[:10], received[:10], dropped_ticks=0, audio_underruns=0)
