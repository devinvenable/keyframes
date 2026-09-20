# Continuous MIDI clock — T93 verification

From `showsync/`, with the project virtualenv and `QT_QPA_PLATFORM=offscreen`:

```sh
python -m pytest -q
```

Result after restoring every mutation and merging current `origin/main`:
**219 passed in 14.18s, exit code 0**. Keyframes is unchanged.

The injected audio-clock tests cover four songs and three natural boundaries,
a ramp interlude, gap silence, first-beat lead-ins, and compensation at −250,
0, +32, and +250 ms, with transport enabled and disabled. Independently
calculated tick deadlines and a six-clocks-per-step, 16-step slave verify
continuous indices, phrase position, and tempo takeover both before and after
the audio boundary. Eighty songs bound handover error without accumulation.
A ramp case distinguishes nearest time from rounding the beat count; short
songs sharing one handover do not duplicate or lose clocks.

Other checks cover intentional skip/restart/pause, per-song restart and its
lead-in, a stall crossing an explicit reset and another song, and recovery
from a three-second stall at twice the normal rate before returning to the
absolute audio grid. Audio callback integration, coherent layout snapshots,
live and paused reorder guards, strict boolean schema validation, and the Qt
checkbox's comment-preserving autosave/playback path are exercised. Existing
T80 decoder rewind and T87 startup-index regressions remain green.

## Negative tests

Implementation was committed before mutations. Each mutation used an exact
file backup, asserted unique replacement targets, ran the relevant tests,
and restored that backup in `finally`. All **19 mutations** produced only
assertion failures (62 failing test cases across runs), with pytest exit 1;
no collection/import/runtime errors counted as evidence.

| Deliberately broken behavior | Result |
|---|---|
| Reset transport on every song | Caught |
| Anchor directly to audio without quantization | Caught |
| Accumulate the preceding handover error | Caught |
| Round beat count instead of choosing nearest time during a ramp | Caught |
| Skip clock indices | Caught |
| Remove the catch-up rate limit | Caught |
| Ignore per-song restart | Caught |
| Allow tempo lookahead across an explicit restart | Caught |
| Recover a missed restart from the later song's anchor | Caught |
| Ignore manual transport epochs | Caught |
| Omit Stop on pause | Caught |
| Restore the old half-second reorder margin | Caught |
| Permit unsafe reorder while paused | Caught |
| Omit the position's layout snapshot | Caught |
| Ignore checkbox changes | Caught |
| Omit restart persistence | Caught |
| Omit restart from the playback Song | Caught |
| Invert the loaded restart value | Caught |
| Accept non-boolean restart values | Caught |

Session logs: `/tmp/midi-93-mutations-78n_d0p6/` (temporary local artifacts).

## Hardware acceptance still pending

Devin will verify `three-song-set.yaml` on the live rig: one Start/Stop pair
for the set, uninterrupted KeyStep patterns through both interlude boundaries,
and an intentional reset only when requested. These automated results do not
establish physical MIDI jitter or the rig's audible phase tolerance. The
[design](design-v1.md#continuous-handover-and-beatbar-position) documents the
half-beat tradeoff, rate-limited recovery, and manual-restart escape hatch.
