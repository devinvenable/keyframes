# Live show runbook — scripts/live.sh

How to run ShowSync + Keyframes for an actual performance (gig: epic 246),
and what to do when something goes wrong mid-set. This is the LIVE path:
real display, audio to the house, **no capture** — for recorded takes use
`scripts/perform.sh` instead.

## The one command

```sh
scripts/live.sh --bank <bank-name> songs/<set>.yaml
```

That starts, in order:

1. **ShowSync** — backing tracks + MIDI clock out. The set starts from the
   **editor UI or `--autostart`** — the KeyStep's Play/Stop belong to
   Devin's rig, not the backing set (decision D15), so live.sh **no longer
   adds `--midi-transport`**; pass it explicitly if a controller's Play
   really should drive the backing tracks. The editor window opens on the
   non-projector monitor when there is one (auto-detected on Linux; on
   macOS pass `--editor-screen INDEX` if Qt's remembered placement is
   wrong).
2. **Keyframes** — fullscreen on the first landscape display (the
   projector), always-on-top, KeyStep-triggered visuals. The ShowSync
   projector raises itself above Keyframes for video songs and hides
   after — the stacking is deterministic, no setup needed.

Useful variants:

```sh
scripts/live.sh --headless --autostart=10 songs/<set>.yaml   # projector only, clickless
scripts/live.sh --clock-offset -20 --bank robots songs/<set>.yaml
scripts/live.sh --no-restart songs/<set>.yaml                # disable crash supervisor
scripts/live.sh --midi-transport songs/<set>.yaml            # opt-in: MIDI Play/Stop drives the set
```

Anything live.sh doesn't recognize passes through to ShowSync
(`--audio-device`, `--autostart`, `--clock-offset`, `--editor-screen`, ...).
`--bank` picks the Keyframes media bank; F5/F6 still cycle banks live.

Per-song `.mid` playback is optional by design (decision D11): the set
plays identically whether or not songs carry `midi:` entries — don't build
the set around it.

## Audio and MIDI wiring

- **Audio to the house**: ShowSync plays through the system default output
  (or `--audio-device`). Nothing is captured; there is no recording
  routing to set up.
- **Behringer is input-only**: the KeyStep reaches Keyframes through it
  (note-ons for visuals). ShowSync's MIDI transport input exists but is
  **opt-in only** (`--midi-transport`) — by default nothing the KeyStep
  does starts or stops the backing set.

### Rig topology v3 — Devin is his rig's transport master (D15, D14)

The design intent: **Devin's synths hear ONLY the KeyStep's own output** —
clock while his sequencer plays, nothing when he stops. ShowSync keeps the
set's timebase; the KeyStep syncs its tempo to it over USB but Devin
starts/stops his own sequences freely, mid-song, without touching the
backing set, and his Stop never stops David or the tracks.

| Leg | Carries |
|---|---|
| ShowSync → KeyStep USB | **clock only** (tempo sync; the KeyStep's clock toggle stays **USB**) |
| KeyStep DIN OUT → thru box → Devin's synths | the KeyStep's own stream: notes, **his** transport, its regenerated clock |
| thru box return → TBOX In 1 | that same KeyStep stream, back into the computer (Keyframes sees his live seq edits) |
| ShowSync → TBOX Out 2 → David's rig | **clock only** + his per-song `midi:` file (per-song `midi.port`) |
| ShowSync → `ShowSync Cues` virtual port → Keyframes | **full egress** (clock, transport, PC + CC102–105 cues), no cable |
| TBOX Out 1 | spare — leave unconnected |

Why the return loop is safe now (it wedged the TBOX in v1, insight I51):
the I51 wedge needed a **doubled clock** — ShowSync's clock into the thru
box plus the KeyStep's regenerated echo of it. In v3 ShowSync sends the
thru box **nothing**: the only clock on the DIN chain is the KeyStep's
own single regenerated stream, so the return into TBOX In 1 carries one
clock, not two. ShowSync's transport echo gate (T169) stays as insurance,
and ShowSync never listens to its own virtual port.

**Bench-check (accepted behavior, not a bug):** if the KeyStep does not
pass clock to its DIN OUT while its sequencer is stopped, that is the
intent — Devin's synths hear nothing when he stops. Do **not** work
around it by feeding the thru box from a TBOX output: any DIN clock into
the thru box reaches ALL of his synths, re-creating the double-clock and
making his rig chase ShowSync when he has stopped it.

### Per-port egress filtering (`midi_outputs`)

ShowSync's egress has three classes — `clock` (0xF8), `transport`
(Start/Continue/Stop), and `cues` (everything else: the Keyframes PC +
CC102–105 cues, and file events routed through the clock port). Each
entry in the setlist's top-level `midi_outputs:` list is either a bare
port (name, substring, or index — **full egress**, as before) or a
filtered subset:

```yaml
midi_outputs:
  - {port: KeyStep, send: [clock]}      # KeyStep USB — tempo sync only (D15)
  - {port: Midi Out 2, send: [clock]}   # TBOX Out 2 — David: clock only
```

Substrings are the portable spelling — exact rtmidi names carry Linux
ALSA ids and differ on the Mac's CoreMIDI. The `ShowSync Cues` virtual
port always carries the full egress (Linux/macOS; Windows has no virtual
ports and degrades to the hardware mirrors) — Keyframes picks it up by
name on top of its normal hardware/`--port` selection, so cues and clock
reach Keyframes in software.

CLI override for one run: `--midi-outputs 'Midi Out 2,KeyStep'` (bare
ports, full egress). A port
missing on this host (or an ambiguous substring) **warns and is skipped —
the show always starts**. A port that dies mid-show (USB yanked) is
dropped the same way and **stays dropped for that engine's life**: a
replug does NOT self-heal. Recovery is the normal supervisor path — kill
or crash ShowSync, it relaunches, and restarting the set (editor Play or
the `--autostart` countdown) reopens all configured ports.

The virtual port exists for ShowSync's whole process life (opened at
launch, not at Play), which is why the launch order — ShowSync first,
then Keyframes — matters and is what live.sh already does. Keyframes also
**re-binds its cue-port connection every ~5 s**, so after a ShowSync
crash + supervisor relaunch the cues reach Keyframes again within seconds
— no Keyframes restart needed (a relaunched ShowSync is a new MIDI client
even when the port name looks identical; Keyframes reopens rather than
trusting the name).

## Ending the show

Any of these ends everything cleanly:

- **Esc in Keyframes** (the usual way),
- Esc in the ShowSync projector, or closing the ShowSync editor,
- set completion in `--headless` mode,
- **Ctrl+C** in the terminal running live.sh.

## Mid-set recovery

live.sh supervises both apps. **A crash of one never takes down the
other** — ShowSync's audio keeps playing through a Keyframes crash, and
the visuals keep running through a ShowSync crash. The crashed app is
restarted automatically, up to 3 times (then it stays down and the other
keeps going; restart limit: `LIVE_RESTART_LIMIT`). A **clean** exit is
never restarted — that's how the show ends.

### Keyframes crashed (visuals gone, music still playing)

Do nothing. It relaunches within a second or two, **in the bank that was
live on stage** — Keyframes publishes every bank load/F5/F6 switch to a
state file (`KEYFRAMES_BANK_STATE`), and the supervisor relaunches with
that bank, not the original `--bank`. Zoom ring / latch / pan state is
in-memory only and resets — re-set them by hand if the song used them.

### ShowSync crashed (music stopped, visuals still up)

It relaunches automatically, but a relaunch starts with **no set
playing** — someone must restart the music:

- In the **editor** window press Play — and to get back to the current
  song, use **Skip** repeatedly (or click the song) and start from there.
  A restart is always **from the top** of wherever you start it; there is
  no resume-from-position.
- With `--autostart`, the relaunch counts down and restarts the set from
  the top on its own.
- In `--headless` mode there is **no Skip** (and no editor), which is why
  the editor-on-second-screen layout is the recommended gig setup. (If
  you opted into `--midi-transport`, a MIDI Play also restarts from the
  top — by default the KeyStep's Play does nothing to the backing set.)

### A song stalls (audio hung / silent, nothing crashed)

The supervisor only sees process exits, so a wedged-but-alive ShowSync is
a manual call:

1. First try the transport: **Stop, then Play in the editor** (the set
   restarts from the top; use Skip to return to the song). The KeyStep's
   transport won't help here — it drives Devin's rig, not the set.
2. If it's truly wedged: kill ShowSync alone with
   `pkill -f showsync/main.py` from another terminal. (Do NOT Ctrl+C the
   live.sh terminal — that ends the whole show.) The supervisor treats
   the kill as a crash and relaunches ShowSync; continue as in
   "ShowSync crashed" above.
3. Keyframes wedged (black/frozen visuals, input dead):
   `pkill -f keyframes/main.py` — same deal, it relaunches into the live
   bank.

### Everything is wrong

Ctrl+C in the live.sh terminal, breathe, run the one command again. Cold
start to music is: command, wait for "Starting Keyframes", Play in the
editor (or let the `--autostart` countdown run).

## Platform notes (Mac mini target, Linux dev)

- live.sh is **bash-3.2 clean** (macOS stock bash) and contains no
  Linux-only hard requirements; all platform differences are isolated in
  the `PLATFORM` block at the top of the script.
- **Editor screen**: auto-picked via xrandr on Linux only. On macOS,
  ShowSync keeps its per-machine remembered screen; override with
  `--editor-screen INDEX` (Qt screen index) if it opens on the projector.
- **Keyframes always-on-top is X11/Windows only** today
  (`set_window_always_on_top` in keyframes/main.py returns False on
  macOS). On the Mac mini the show runs unpinned: after the ShowSync
  projector hides, whatever window was last raised could be revealed
  instead of Keyframes. Mitigations until a Cocoa window-level call is
  added (candidate follow-up task): keep nothing but the two apps on the
  projector display, and don't click other windows mid-set. **Verify
  stacking at the dress rehearsal (~Nov 3-4).**
- macOS will ask for **microphone / input-monitoring / accessibility**
  permissions on first run — do a full-path rehearsal run on the Mac mini
  well before the gig so every permission prompt is already answered.

## Smoke test

`scripts/live_smoke_test.sh` exercises launch order, env hygiene (no
capture sidecars), the crash supervisor, bank preservation across a
Keyframes restart, clean teardown, and the Darwin code path — all with
stub apps, no display or audio needed.
