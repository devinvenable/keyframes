# Per-song visual control: the ShowSync → Keyframes MIDI vocabulary

ShowSync cues Keyframes at the start of each song — which image **bank** is
live, whether **scenes** may activate, how often, and which ones — on the
same egress that carries the clock. The messages are plain MIDI (one
Program Change plus four CCs), so any gear or DAW can send them, not just
ShowSync, and the show never depends on per-song `.mid` playback (decision
midi:D11).

**Delivery (task 259):** the egress — clock, transport, and these cues —
is mirrored to every port in the setlist's top-level `midi_outputs:` list
*and* to a virtual output port named **`ShowSync Cues`** that ShowSync
always opens (Linux/macOS; Windows has no virtual ports). Keyframes always
listens to a port containing that name, in addition to its normal
hardware/`--port` selection, while continuing to skip other virtual ports
(Midi Through etc.). That software path replaces the old hardware return
loop (KeyStep thru → thru box → TBOX In 1), whose echoed clock could
double-clock and wedge the interface — the return DIN cable is removed
from the rig (see docs/live-show-runbook.md for the full topology).

This file is the spec both sides implement: `keyframes/main.py`
(`SCENE_CC_*`, `SCENE_MIDI_IDS`, `VisualControl`) and
`showsync/showsync/visuals.py` (`CC_*`, `KEYFRAMES_SCENES`,
`song_controls`). Change it in lockstep or not at all.

## Message map (user-facing — sendable from any MIDI gear)

| Message | Meaning | Value |
| --- | --- | --- |
| Program Change | Select bank | `0` = default bank; `1..N` = the `keyframes/banks/` folder names **sorted alphabetically** |
| CC 102 | Reset scene overrides | any value; drops every per-song override, back to the active bank's `scenes.json` defaults |
| CC 103 | Scenes enabled | `0–63` = off, `64–127` = on |
| CC 104 | Scene probability | `value / 127` → `0.0–1.0` |
| CC 105 | Allow a scene | `value` = scene id (table below); the first add after a reset switches activation to an exclusive allowlist |

**Channel:** Keyframes accepts all five messages on **any** channel
(deliberately unlike notes, which honour `--channel`): ShowSync's cue channel
must not depend on Keyframes' filter, and a KeyStep patch change should work
however the performer has channels set. The tradeoff is equally deliberate:
*any* device on Keyframes' input port that emits a patch change will switch
banks — keep other PC-emitting gear off that port. ShowSync emits on
`keyframes.channel` (default 16) purely to stay clear of performance channels
for other listeners.

**CC 104 quantization:** probability travels as a 7-bit value, so steps are
~0.8%. `0.15` is sent as `19/127 ≈ 0.150`; `0.05` as `6/127 ≈ 0.047`. If a
measured activation rate looks slightly off the YAML number, this is why —
nothing is wrong.

## Scene ids (CC 105 values)

| id | scene |
| --- | --- |
| 0 | `four-bar-sweep` |
| 1 | `four-bar-sweep-black` |
| 2 | `four-bar-sweep-tinted` |
| 3 | `concentric-rings` |
| 4 | `concentric-rings-timed` |

Ids are **append-only**. A new scene takes the next free number; existing
scenes are never renumbered — ShowSync mirrors this table in
`showsync/showsync/visuals.py`, and stable ids are what keep already-written
setlists valid as scenes are added. Unknown ids are logged and ignored.

## Setlist YAML

```yaml
title: "Fall set"
keyframes:
  # The COMPLETE list of keyframes/banks/ folders, sorted alphabetically.
  # Program numbers are derived from positions here (1-based; 'default' is
  # always program 0 and must not be listed). The loader rejects an unsorted
  # list, but only Keyframes can see whether it is complete — when you add a
  # bank folder, add it here too, or every bank after it cues wrong.
  banks: [insect-war-aged, robot-society-symbols]
  channel: 16        # optional, 1-16

songs:
  - name: "Robot Society"
    file: robot-society.wav
    bpm: 120
    keyframes:
      bank: robot-society-symbols
      scenes:
        enabled: true
        probability: 0.15
        allow: [four-bar-sweep-tinted]

  - name: "Interlude"          # no keyframes block: nothing is sent,
    file: ambient.wav          # bank and scene settings persist
    bpm: 120

  - name: "Quiet One"
    file: quiet.wav
    bpm: 90
    keyframes:
      scenes: {enabled: false}   # no scenes at all this song; bank unchanged
```

Semantics:

- **No `keyframes:` block** → nothing is emitted; the previous song's bank
  and scene overrides persist.
- **A `keyframes:` block** → ShowSync sends the bank program first (when
  `bank:` is given), then **CC 102 reset**, then only the values the block
  sets. Every cue-bearing song therefore starts from its bank's
  `scenes.json` defaults plus exactly its own overrides.
- `keyframes: {}` is legal and means "reset to bank defaults, change nothing
  else".
- `allow: []` is rejected at load: there is no MIDI message for an empty
  allowlist — spell "no scenes this song" as `enabled: false`.
- Scene names are validated against the id table at load; bank names against
  the top-level `banks` list.

Messages are emitted by `ClockEngine` at each song start, on the full clock
egress (every `midi_outputs` mirror plus the `ShowSync Cues` virtual port),
before that song's Start byte and first tick — so the bank is live before the
new song produces any note. A set restart re-emits the current song's cue,
which also re-cues a crash-restarted Keyframes.

## Keyframes behaviour

- A program change naming the **already-live bank is a no-op** (no reload,
  no cache flush) — ShowSync re-sends the program on every cue-bearing song.
- Out-of-range programs and failed bank loads set the on-screen bank notice
  and are otherwise ignored; a bad cue must never take down the show.
- Overrides layer **over** the active bank's `scenes.json`; a manual F5/F6
  bank switch mid-song keeps the song's overrides (they rebase onto the new
  bank's defaults). CC 102 is the only thing that clears them.
- A bank's `scenes.json` may itself carry an `allow` list
  (`{"enabled": true, "probability": 0.1, "allow": ["concentric-rings"]}`) as
  the per-bank default; `[]` there means "no scenes may activate".
- Free win: the KeyStep's program-change buttons switch banks live, same
  rules.
