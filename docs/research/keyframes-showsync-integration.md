# Keyframes ↔ ShowSync integration architecture

**Task 270 · 2026-10-10 · research only, no code changes.**
Prompted by Devin: "keyframes and showsync are mostly independent but they
don't have to be. If a bridge between them is more useful than standalone, we
can do that. Not everything has to be MIDI. Functionality unique to showsync
could be more tightly integrated if needed."

Constraints: gig Nov 11, dress rehearsal ~Nov 3-4 (epic 246), Linux rig is
the priority platform. Work order D18 puts ShowSync integration LAST, after
standalone Keyframes correctness — this report informs that final phase.

## TL;DR recommendation

Keep the two-process model and MIDI for **clock + notes** (they must stay
MIDI — hardware synths and the KeyStep live on that wire). Move **cues +
state** onto a tiny one-way localhost datagram channel (UDP, OSC-style or
newline JSON) from ShowSync to Keyframes, with a 1 Hz full-state heartbeat,
while keeping the existing MIDI cue path as a flag-guarded fallback during
migration. This is option (b) below, sized at roughly 2–4 agent-days plus one
live verification by Devin — comfortably inside the month. Do **not** start
it before D18 phases 1–3 land: the bridge does not fix the T266 lockup class
by itself, and layering it over an unfixed ingestion bug would repeat the
"integration fixes that didn't help" pattern D18 exists to stop.

Tight coupling (option c) is rejected for this gig: it destroys the failure
isolation that live.sh's crash supervisor is built around, and pygame +
PyQt in one process is a stability regression, not an improvement.

## Current coupling — all MIDI, three paths

Everything between the two apps today rides MIDI (docs/visual-control-midi.md):

1. **Virtual cue port.** ShowSync opens a process-lifetime virtual output
   `'ShowSync Cues'` (`showsync/showsync/egress.py`, VIRTUAL_PORT_NAME) that
   carries the full egress: clock (0xF8), transport (0xFA–0xFC), and the
   per-song visual cues — bank Program Change + CC102–105 reset / enabled /
   probability / allow-scene (`showsync/showsync/visuals.py`). Keyframes
   always subscribes to any port containing that name
   (`keyframes/main.py` SHOWSYNC_CUE_PORT) and additionally **reopens every
   cue port every 5 s** (CUE_PORT_RESCAN_S) because a crashed-and-relaunched
   ShowSync reappears under the same ALSA name with a new client — a name
   diff can't detect it, so the binding is blindly refreshed.
2. **Hardware return.** Keyframes also auto-opens hardware inputs (TBOX
   In 1), which carry the KeyStep's DIN output: Devin's live notes, his
   transport presses, the KeyStep's regenerated clock — and, per midi:I70,
   an **unconditional echo of any USB-in clock to DIN OUT**, which the D17
   restore feeds (KeyStep USB mirror now carries clock+transport again).
3. **Transport back-path.** With `--midi-transport` (live.sh default again
   per D17), ShowSync listens on **all** hardware inputs for Start/Stop
   (`showsync/showsync/transport.py`), suppressing echoes of its own egress
   inside a 1 s window (ECHO_WINDOW) and skipping its own virtual port.

Per-song cues are emitted by the clock thread at each song start
(`clock.py step()`: `self.controls[p.song_index]` sent before the song's
START/first tick), from a vocabulary mirrored by hand in two files
(`visuals.KEYFRAMES_SCENES` ↔ `keyframes SCENE_MIDI_IDS`, append-only ids).

### Known pain, mapped to mechanism

- **I51 wedge (September):** doubled clock on the DIN chain wedged the TBOX
  (enumerates, passes zero events). Fixed by topology (single clock stream on
  the return leg), but the class remains: the KeyStep's unconditional USB→DIN
  clock echo (I70) means any config that mirrors clock to KeyStep USB puts a
  second clock image on the return path.
- **T266 lockups (current, unfixed):** Keyframes freezes mid-set; Devin's
  hypothesis is a MIDI loop/flood. Relevant code facts: Keyframes is a
  single-threaded pygame loop; `process_midi_messages()` drains **the entire
  backlog** of each input every frame (`iter_pending()` with no cap), and
  mido's rtmidi backend buffers unboundedly between frames — a stall (video
  decode hiccup, bank load) followed by a burst means unbounded per-frame
  work, which lengthens the frame, which grows the next backlog. Keyframes
  also ingests **clock on two ports by design** (cue port + hardware return),
  so every tick is processed twice at baseline.
- **Rescan races:** the 5 s cue-port refresh closes/reopens ports on the
  render thread; T266 flags it as a suspect for lock/ordering interaction
  with the flood path. It exists *only* because cue delivery rides MIDI —
  ALSA client identity is the thing being chased.
- **Fragile shared vocabulary:** 7-bit values (probability quantized to
  1/127), two hand-mirrored tables, no way to say "song 3 of 9, 'Title',
  playing, bar 17" — the cue channel is write-only and stateless, so a
  late-joining or restarted Keyframes can only be repaired by the *next*
  cue-bearing song.

## Option (a): status quo MIDI-only, hardened

Keep everything as is; fix the lockup class in Keyframes ingestion
(bounded per-frame drain with clock-coalescing, stall watchdog/traceback
dump — already the T266 plan) and keep the topology discipline (D16/D17,
per-port egress filters from T261).

- **Reliability:** the hardening is *necessary under every option* — floods
  can still arrive on the hardware port (notes + regenerated clock) no matter
  where cues travel. But cues remain exposed to the same wire: a TBOX wedge
  or ALSA stall takes bank changes down with it, and the rescan race stays.
- **Latency/jitter:** fine. Verified egress numbers (verification.md,
  commit 100f562): 1 port 0.011/0.142 ms, 4 ports 0.022/0.581 ms.
- **Cost:** zero beyond T266 work already in flight.
- **Debuggability:** poor at the cue layer — aseqdump mid-show, 7-bit values,
  no state snapshot, "did the cue arrive?" is unanswerable after the fact
  (KEYFRAMES_MIDI_LOG helps but must be pre-armed).
- **Failure isolation:** good (two processes, live.sh supervisor restarts
  either). Recovery is partial: a restarted Keyframes lands in the right
  *bank* (KEYFRAMES_BANK_STATE) but loses scene overrides until the next
  cue-bearing song; a restarted ShowSync is only re-bound by the 5 s rescan.

## Option (b): local non-MIDI bridge for cues + state (recommended)

MIDI keeps what MIDI is good at — clock and notes to hardware and to
Keyframes' clock_tracker. A one-way localhost datagram channel carries what
MIDI is bad at: structured cues and state.

**Shape.** ShowSync → UDP datagrams to 127.0.0.1:<port> (OSC framing or
newline JSON — JSON is less show-control-standard but zero-dependency and
greppable; either works, pick at implementation time):

- on song start (same place `clock.py` sends `controls[p.song_index]`):
  `{song_index, song_title, bank, scenes: {enabled, probability, allow}}`
- on transport change: `{playing: bool, song_index}`
- **1 Hz heartbeat carrying the full current state** (same payload as the
  song-start cue + playing flag + a sequence number).

Keyframes: a non-blocking `recvfrom` drain in the main loop (bounded, e.g.
max 16 datagrams/frame — trivially bounded because the heartbeat is 1 Hz,
not 48 Hz clock), translated into the *existing* VisualControl actions
(bank program → `apply_program_change` path, scene overrides → the same
rebase/override lifecycle). No new thread, no Qt, no new deps.

Why the heartbeat is the key design element — it converts every known
coordination failure into a ≤1 s self-heal:

- ShowSync crash+relaunch: no rescan needed at all; the next heartbeat from
  the new process carries full state. **The 5 s rescan and its race are
  deleted** (or retained only while the MIDI-cue fallback flag is on).
- Keyframes crash+relaunch (live.sh restarts it): first heartbeat restores
  bank *and* scene overrides — better than today's bank-only recovery.
- A lost or late cue (UDP loss on loopback is effectively nil, but still):
  repaired within 1 s.
- Stage debuggability: Keyframes can render a one-line status overlay
  ("ShowSync: 3/9 'Title' ▶" / "ShowSync: no heartbeat 4s") and the channel
  is observable with `nc -ul`/`oscdump` without touching ALSA.

**Reliability vs the lockup class:** the bridge removes cue delivery from
the flood domain and deletes a race suspect, but Keyframes still listens to
TBOX In 1 for notes/clock — **the T266 ingestion hardening is still the
actual lockup fix**. The bridge's honest claim is: when a MIDI storm or
wedge happens anyway, *visual cues and state no longer share its fate*, and
recovery of either process is faster and more complete.

**Latency:** song-start cues need tens of ms at most (they land at a song
boundary); loopback UDP is sub-millisecond. Clock stays MIDI — no change to
the tight path.

**Failure isolation:** unchanged two-process model, plus liveness becomes
*visible* (heartbeat age) instead of silent.

**Cost:** small and testable headless.
- ShowSync emitter: ~100–150 lines (a `CueBridge` with `send(state)`;
  call sites: the `controls` emission in `clock.step()`, transport
  start/stop, a 1 Hz timer; config: `--cue-bridge-port`, default on).
- Keyframes receiver: ~100 lines + tests (socket drain → existing
  VisualControl/bank paths; heartbeat-age overlay).
- Dual-emit migration: ShowSync keeps sending MIDI cues; Keyframes prefers
  bridge when heartbeats are fresh, falls back to MIDI cues otherwise. One
  flag reverts the whole thing on stage.
- Estimate: 2–4 agent-days including tests, then one Devin live run.

## Option (c): tight integration (shared process / library)

Fold Keyframes into ShowSync (or vice versa) so setlist state and
song-aware visual control live in one process.

- Pygame (SDL main-loop, fullscreen, owns the display) + PyQt (ShowSync GUI,
  Qt event loop, audio callbacks) in one process is an event-loop and GIL
  fight; ShowSync's audio graph must never compete with video decode
  (canon midi:I39 — live.sh even `nice`s Keyframes for this).
- One crash takes the whole show down. live.sh's supervisor exists
  precisely so a Keyframes wedge never stops the audio; T266 is *unfixed* —
  merging the wedging process into the audio process is the worst possible
  move before the root cause is known.
- Cost is weeks (process model, window stacking, packaging for the Mac mini
  later), far outside the pre-Nov-3 window, and it contradicts D18's
  "provably correct standalone foundation first."

Rejected for this gig. If the bridge later proves insufficient (e.g. frame-
accurate beat-position-driven visuals), revisit *after* Nov 11 — and even
then, a richer bridge (beat position in the heartbeat) likely beats merging.

## Migration sketch (fits the remaining month)

1. **Now → D18 phases 1–3 complete** (standalone Keyframes correctness,
   T266 ingestion hardening + watchdog, T269 invert fix). The bridge waits
   behind these — hard gate.
2. **Bridge, dual-emit (≈2–4 days once gated work lands, target ~Oct 24
   merge):** ShowSync emitter + heartbeat; Keyframes receiver preferring
   fresh heartbeats, MIDI cues as fallback; rescan kept but only active in
   fallback mode; headless tests both sides (fake socket, fake clock).
3. **Devin live-verifies** (he is the live verifier) in a normal live.sh
   run — no new flags needed if bridge defaults on with fallback armed.
4. **Dress rehearsal Nov 3–4** runs dual-emit. If the bridge misbehaves,
   one flag restores today's exact behavior.
5. **Post-gig cleanup:** retire the MIDI cue vocabulary (or keep for
   non-localhost rigs), delete the rescan, consider beat-position in the
   heartbeat for song-aware visuals.

## Facts this rests on (for canon)

- Clock and performer notes must remain MIDI: hardware consumers (synths via
  thru box, KeyStep) and Keyframes' clock_tracker all sit on the physical
  chain; nothing about cue transport changes that.
- The cue-port 5 s rescan exists solely to chase ALSA client identity across
  ShowSync relaunches; a stateful heartbeat channel makes it unnecessary.
- A cue bridge does not fix the T266 lockup class; bounded ingestion in
  Keyframes does, and is prerequisite work under any architecture.
- Tight coupling trades away the failure isolation live.sh is designed
  around and is not achievable safely before Nov 3–4.
