# Bar-complete MIDI song starts — T104 verification

T104 replaces T93's continuous-clock handover after its live acceptance failed:
gear did not re-anchor when the next song had a different BPM. Every natural
transition now finishes the outgoing four-beat bar, then sends Stop/Start and
begins the next song's audio and tempo map. There is one behavior; old YAML
`restart` booleans remain inert and comment-preserving.

## Restored full-suite result

After restoring every mutation and merging current `origin/main` (already up
to date), from `showsync/` with the project virtualenv:

```sh
QT_QPA_PLATFORM=offscreen python -m pytest -q -rs --junitxml=/tmp/t104-final-suite.xml
```

**446 passed, 4 skipped in 23.47s; exit code 0.** The four existing skips are
inapplicable replacement-audio timing-fit combinations at
`tests/test_replace_audio.py:229` (`Detected timing requires a fit`). The final
JUnit case names were compared with mutation results: all 210 boundary cases
have at least one assertion-level negative result. `git diff --check` passed.

## Automated matrix

`tests/test_bar_boundaries.py` contains 210 deterministic cases:

- 60 edge cases: 60, 90, 120, 137.123, 180, and 300 BPM; ends exactly on a
  bar, one tick into the next bar, one sample before/after a bar, and one-sample
  songs; transport both enabled and disabled. Subsequent songs include
  back-to-back 180 → 60 → 180 BPM changes.
- 100 seeded random setlists of 4–24 songs, with fractional BPMs from 40–240,
  first-beat offsets, gaps, exact/adjacent bar frames, sub-bar songs, and
  arbitrary lengths. An independent oracle enumerates constant-tempo bars;
  the simulation checks every emitted byte, tick index, tick deadline, and
  six-clocks-per-step slave position. Every enabled song starts at step 1.
- A 100-song set checks repeated frame rounding and phase resets.
- Two analytic ramp/jump cases verify that a 60 → 180 BPM ramp finishes its
  wait at 180 BPM, followed by a jump map, lead-in, and two more boundaries.
  The expected ramp times use the independent quadratic inverse.
- Four compensated lead-in cases and eight compensated starts without
  lead-in cover −250, −32, +32, and +250 ms. The audio layout and transport
  stay at the same boundaries; initial indices remain gapless, including
  positive-offset startup bursts.
- Two stall cases cover rate-limited recovery within a song and re-anchoring
  the current song after a stall crossing multiple boundaries.
- One reorder case checks immutable snapshots, recalculated waits, and the
  half-second live/paused callback guard.
- Ten real-callback cases compare every decoded file sample and every silent
  padding sample, with gaps of 0, .25, 1, 1.01, and 4.25 seconds and transport
  both enabled and disabled. Four songs share a callback without epoch bumps;
  their first clocks land at their audio starts.
- Eighteen real transport cases exercise skip, restart, and pause/resume at
  .4, 1.2, and 1.999 seconds (mid-song, in padding, and immediately before the
  next bar), with transport enabled and disabled. Skip/restart produce one
  reset; resuming preserves the next unsent tick, with a separate reset if a
  natural boundary subsequently occurs.
- Four pending-seek cases verify that skip/restart during padding emit Stop
  once while waiting for a fresh buffer, then Start once when it is ready.

Existing decoder-thread rewind tests still cover stale-ring invalidation,
multiple rapid restart requests, and replayed samples. Setlist/editor tests
verify that legacy `restart` values have no runtime attribute or checkbox,
while quotes, tempo maps, comments, and old keys survive ruamel round trips.
Keyframes code is unchanged.

## Mutation method

Implementation and tests were committed before mutation. Each mutation used
an exact file backup, asserted every replacement target was unique, cleared
the affected bytecode cache, and restored the backup in `finally`. The harness
requires pytest exit 1, at least one assertion failure, and zero test errors.
An initial UI mutation that caused a Qt paint error was rejected and corrected;
that error is not counted as evidence. Transport expectations use the requested
preference rather than reading the mutated engine's preference back.

All **27 mutations** were caught with assertion failures and pytest exit 1:
**1,462 assertion failures** across runs. Every one of the **210 boundary test
cases**, both editor legacy cases, both schema legacy cases, and the updated
schema-default case failed under at least one mutation (215 distinct cases).

| Mutation | Assertion failures |
|---|---:|
| `omit-padding` | 200 |
| `extra-bar-on-exact-end` | 60 |
| `misalign-one-frame` | 60 |
| `compress-tick-deadlines` | 160 |
| `microshift-incoming-map` | 62 |
| `keep-old-tempo` | 62 |
| `continuous-no-boundary-reset` | 61 |
| `omit-stop` | 41 |
| `omit-start` | 41 |
| `ignore-transport-preference` | 51 |
| `ignore-manual-epoch` | 8 |
| `double-stop-on-reset` | 11 |
| `skip-tick-zero` | 206 |
| `drop-tick-indices` | 186 |
| `emit-outgoing-downbeat` | 2 |
| `sleep-past-boundary` | 1 |
| `ignore-rig-compensation` | 12 |
| `reset-ticks-on-resume` | 4 |
| `unbounded-stall-catchup` | 1 |
| `corrupt-padding-silence` | 20 |
| `ignore-gap` | 99 |
| `ignore-first-beat-offset-in-padding` | 100 |
| `old-reorder-guard` | 1 |
| `bypass-seek-readiness` | 4 |
| `restore-song-restart-attribute` | 5 |
| `restore-restart-column` | 2 |
| `discard-legacy-yaml` | 2 |

Temporary local evidence: `/tmp/t104-mutations-w7v1svqe/` contains each exact
backup, pytest log, JUnit XML, and the aggregate `summary.json`.
The harness used for this run is `/tmp/t104-mutations.py`.


## Hardware acceptance

Devin still needs to verify `three-song-set.yaml` on the live rig. Listen for
unchanged outgoing tick spacing through padding, completed KeyStep phrases,
and step-1 re-anchoring with each new BPM. Also check skip/restart and pause
while waiting. There are no per-song boundary toggles.

Zero rig compensation is the exact bar-completion baseline. Fixed rig
compensation keeps its existing semantics: positive offsets without enough
lead-in clamp overdue initial ticks to startup; negative offsets can leave
outgoing tail ticks beyond the audio cut. These intentional phase adjustments
are separate from bar padding. The final song stops at EOF; it has no following
song and receives no added final bar or configured gap.

The tests establish deterministic scheduling and sample preservation, not
physical MIDI wire jitter or the audible alignment of a particular rig.
