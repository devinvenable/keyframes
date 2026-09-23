# T120: kick-band phase selection and suite flake investigation

Verified 2026-09-23 on Linux with Python 3.13.3, NumPy 2.4.3,
pytest 9.0.2 and PySide6 6.11.2. Implementation: `6a78293`.

## Real-file regression

Local input: `songs/clock_divider_missing.mp4`, SHA-256
`7637a9a11b487c0437952d274554fed9991e62e38795202ea5d059fbb9577d08`.
The media is not committed. The PM reported that Devin listened to a
trim-aligned render and confirmed the approximately 0.165 s phase by ear.

All seven agreeing windows project onto the offbeat, approximately 0.448 s.
Changing the scoring signal alone cannot recover a phase that no window
proposes. The fix evaluates each projected phase and its half-beat shift,
using spectral power below 280 Hz from the existing FFT pass. It retains one
additional 100 Hz scalar feature stream without decoding again.

The full `estimate_grid` call through the real Decoder returns:

| Scorer | BPM | Offset (s) | Partial |
| --- | ---: | ---: | --- |
| Original window phases | 105.99893058020838 | 0.4483363800562499 | true |
| Kick power plus half-beat alternatives | 105.99893058020838 | 0.16308457746396798 | true |

The corrected offset differs from the validated target by less than 2 ms.
Over the agreeing spans, the existing neighborhood-max scorer gives kick
power support of approximately 2.86 million at 0.165 s versus 2.17 million
at 0.448 s. These are unnormalized spectral-power scores, with overlapping
windows counted as in the original scorer, not calibrated audio levels.

## Discriminating synthetic regression

The deterministic 205 s fixture has a beatless intro, a 106 BPM steady
section with loud offbeat hats, and a drifting outro. The integration test
checks all of the following in one real-decoder call:

- The full-file fit rejects and at least three window fits succeed.
- Every successful window chooses the hat phase.
- Broadband flux prefers the hat phase by more than 2:1; low-band power
  prefers the kick phase by more than 2:1.
- The final partial grid has the correct tempo and kick offset within 10 ms.
- Feature extraction and Decoder opening each occur exactly once.

After committing the implementation, two independent, uniquely matched
mutations were applied to the scorer. Each failed the final offset assertion
with a 0.2827 s phase error (exit 1):

1. Feed broadband flux to `_phase_support` while retaining half-beat candidates.
2. Remove half-beat candidates while retaining kick-band scoring.

The exact implementation file was restored from a temporary copy after each
mutation. There were no collection or import errors masquerading as failures.

## Repeated suite investigation

Twenty full-suite runs completed, two concurrent pytest processes at a time.
Every run reported **511 passed, 4 skipped, exit 0** (27.61–31.67 s per run).
Command from `showsync/`, with a unique `--basetemp` for each repetition:

```sh
QT_QPA_PLATFORM=offscreen python -m pytest -q --basetemp /tmp/task120-pytest-N
```

Twenty additional runs of the worker/cancellation and Qt/editor subset each
passed all 52 cases, with zero failures. The subset runner and two competing
CPU-bound processes shared CPU affinity `{4, 5}`. The full-suite runners were
also active during this stress experiment. Subset selection:

```text
tests/test_bpmdetect.py::test_worker_serial_identity_manual_delete_and_failure
tests/test_bpmdetect.py::test_close_cancels_active_work_and_never_starts_queue
tests/test_bpmdetect.py::test_deleted_active_row_does_not_fill_replacement
tests/test_bpmdetect.py::test_grid_suggestion_respects_offset_intent
tests/test_bpmdetect.py::test_cancellation_mid_windowed_pass
tests/test_bpmdetect.py::test_partial_grid_state_and_manual_override
tests/test_editor.py
tests/test_gui.py
```

The suspected cancellation-mid-windowed-pass test is synchronous: its
cancellation predicate flips after the full-file analysis returns. The
worker and editor cases above exercise actual threads and event-loop timing.

All repetitions use `QT_QPA_PLATFORM=offscreen`, fresh pytest processes and
separate temporary directories. BLAS thread settings were left at environment
defaults (no `OPENBLAS_NUM_THREADS`, `OMP_NUM_THREADS` or `MKL_NUM_THREADS`
overrides). Local raw logs are `/tmp/task120-suite-runs/run-01.log` through
`run-20.log` and `/tmp/task120-stress-runs/run-01.log` through `run-20.log`.

The previously reported one-off suite failure did not reproduce in these
20 full runs or 20 stressed subset runs. No race fix is claimed or speculative
timing change included; its original cause remains unidentified.
