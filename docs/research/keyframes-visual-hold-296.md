# Keyframes visual hold, 2026-10-10 (T296)

The captured late-show behavior is consistent with sparse note coverage,
not a wedged render loop. The brain-surgery bank assigns only notes 41–58.
The final 20 seconds contain 100 positive note-ons, **all `mapped:false`**.
The last mapped hit, note 53 at session +135.080 seconds, selected
`brain_surgery_18_bw.png`; it was followed by 32.65 seconds with no mapped hit.
Holding that still is the intended latch/unmapped-note behavior. This explains
the apparent freeze at the end; it does not prove that every earlier visible
hold had the same cause. No frame-content evidence was recorded in that take.

Preserved before investigation in this worktree's ignored `logs/` directory:

- `kf-stall-20261010-night.log`, SHA256
  `8786cf6108c8251c082980d13aa0924f845e09f46b71ceed326a48056a59c983`
- `kf-midi-20261010-night.jsonl`, SHA256
  `f905dc02c8a4fa4bebc4e9fa4afa092711564fd5cf061d76f8171fa3e1c2ae2a`

The latest MIDI session runs 23:08:39.294–23:11:27.026 America/Chicago.
The render watchdog was armed for PID 2420234 and did not fire. Earlier
Timeout stacks belong to old sessions. PM relayed that ending ShowSync
also let Keyframes exit cleanly; shutdown and ingestion remained functional.

Brain-surgery was selected by program 1 at +80.762 seconds. Its only GIF
hits were note 58 at +103.888 and note 55 at +104.327. Note 53 subsequently
replaced the GIF with a still seven times between +127.806 and +135.080.
The 103 records without `type` are valid diagnostics identified by `event`:
67 `clock_source_filtered`, 33 `note_source_filtered`, and one each of
`log_open`, `note_source`, and `clock_source`. They are not malformed MIDI.

## Changes and limits

Startup now prints actual mapped count and notes separately from the playable
range. Neither default seeding nor the robot bank cycles media: the manifest
is deliberately sparse and exclusive. The new bank-local `playback.json`
option can cycle unmapped playable notes without adding aliases to the
manifest or changing grid assignment semantics. **It ships disabled for
brain-surgery pending Devin's preference**, per PM direction. Existing 41–58
assignments are preserved. See `keyframes/banks/README.md` for the rule.

A separate latent defect was confirmed by fault injection: a failed GIF
rewind permanently set `finished=True`, holding the last frame forever.
Failed seeks now reopen; failed loop reads and decode exceptions retry with
one-second backoff. Non-looping EOF retains its intentional final-frame hold.
This hardening is not evidence that GIF failure caused the captured incident.
VideoPlayer decodes synchronously, with no overlay-style decoder worker/ring.
Existing bank-switch ownership intentionally keeps the current player alive
until another mapped trigger; no stale-player defect was found there.

With `KEYFRAMES_STALL_LOG`, a small displayed-pixel sample detects unchanged
plain-video/GIF content after five seconds and writes `display_stagnation`
to the stall log and enabled MIDI sidecar. It excludes intentional still,
scene, grid and completed non-looping-video holds. It is diagnostic only;
static passages and sampling aliasing are possible. Moving overlays can mask
an underlying frozen source because the detector observes composed pixels.

Accepted clock ticks now produce five-second per-port `clock_summary`
records, with count, first/last monotonic timestamps and arrival-rate BPM.
Every non-clock message retains its original event record. Pending clock
counts flush on clean close; a kill can lose the latest five-second window.
The sidecar therefore no longer contains individual clock timing/beat phase.

Cues-port note-ons still bypass `--note-source tbox`, by existing contract.
`test_note_source.py::test_main_wires_default_cli_and_open_failure_fallback` injects
notes from fake ports and asserts the selected source, Cues and keyboard
survive. T297 owns stopping unintended ShowSync file-note broadcasts at their
source; T296 does not change this gate.

## Separate audio finding (not fixed here)

PM's recording/log review associates the song-boundary bank load with a
ShowSync audio underrun burst around recording 1:16.98. Bank loading builds
media caches/thumbnails synchronously. Preloading banks at startup is a
follow-up candidate; this task does not change bank loading or establish its
CPU cost as the sole cause of the audio underruns.

## Validation

Headless SDL dummy, fake input queues only; no live.sh, real MIDI ports or
load generator. All 372 Keyframes tests passed (3 skipped). Fault injection
against the original VideoPlayer produced four assertion failures (both seek
failure forms, poisoned-frame exception, permanent failure/backoff). Disabling
clock aggregation, stagnation reporting/finished-video exclusion, cycle policy,
cycle fallback and truthful coverage each failed their respective assertions
(12 failing cases total across seven negative runs). The exact implementation
was restored from a file backup after every mutation.

The four actual brain-surgery GIFs each completed 200 loops / 12,200 displayed
frames at simulated media time. Every clip produced 12,196 pixel transitions
and 61 distinct frames in the final loop. Eight MIDI program changes switched
between robot and brain banks during playback; the displayed player's identity
and content progress survived each switch. Total: 800 loops / 48,800 frames,
152 seconds wall time, rendering at 64×64 while decoding the real 480×480 GIFs.
No natural GIF/ownership wedge reproduced. The script and detailed output are
preserved as `logs/soak-brain-surgery.py` and `.out` in the task worktree.

A further headless replay retriggered notes 55–58 three times each (12
triggers), checked that each prior capture was released, and verified changing
displayed content for 130 frames / more than two loops after every trigger.
After mutation restoration, the 35 directly affected tests passed again.
