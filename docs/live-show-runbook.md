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

1. **ShowSync** — backing tracks + MIDI clock out, with `--midi-transport`
   added automatically so the KeyStep's hardware **Play/Stop start and stop
   the set** hands-free. The editor window opens on the non-projector
   monitor when there is one (auto-detected on Linux; on macOS pass
   `--editor-screen INDEX` if Qt's remembered placement is wrong).
2. **Keyframes** — fullscreen on the first landscape display (the
   projector), always-on-top, KeyStep-triggered visuals. The ShowSync
   projector raises itself above Keyframes for video songs and hides
   after — the stacking is deterministic, no setup needed.

Useful variants:

```sh
scripts/live.sh --headless --autostart=10 songs/<set>.yaml   # projector only, clickless
scripts/live.sh --clock-offset -20 --bank robots songs/<set>.yaml
scripts/live.sh --no-restart songs/<set>.yaml                # disable crash supervisor
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
- **Behringer is input-only**: the KeyStep reaches both apps through it.
  Keyframes reads note-ons for visuals; ShowSync reads MIDI realtime
  Start/Continue/Stop for the transport, and sends MIDI clock out to
  David's rig via the thru box (that clock is the core of the set —
  decision D11).

### Multi-port egress (task 259 — no hardware return loop)

ShowSync mirrors its full egress — clock, Start/Stop/Continue, and the
Keyframes visual cues (PC + CC102–105) — to **every port in the setlist's
top-level `midi_outputs:` list**, plus a **virtual output named `ShowSync
Cues`** that is always opened (Linux/macOS; Windows has no virtual ports
and degrades to the hardware mirrors). Keyframes picks up `ShowSync Cues`
by name, always, on top of its normal hardware/`--port` selection — so
cues and clock reach Keyframes **in software**, and the old DIN return
cable into TBOX In 1 is GONE. No return loop means no echoed/doubled
clock and no wedged TBOX (insight I51); ShowSync's transport echo gate
(T169) stays as insurance, and ShowSync never listens to its own virtual
port.

Gig topology (decision D14, revised):

| Destination | Port | Carries |
|---|---|---|
| Devin's synths (thru box) | TBOX Out 1 | full egress |
| David's rig | TBOX Out 2 | full egress + his per-song `midi:` file (per-song `midi.port`) |
| KeyStep (sync source; its clock toggle stays **USB**) | KeyStep USB | full egress |
| Keyframes | `ShowSync Cues` virtual port | full egress, no cable |

Declared in the setlist (substrings are the portable spelling — exact
rtmidi names carry Linux ALSA ids and differ on the Mac's CoreMIDI):

```yaml
midi_outputs:
  - Midi Out 1      # TBOX Out 1 — thru box / Devin's synths
  - Midi Out 2      # TBOX Out 2 — David
  - KeyStep         # KeyStep USB — its MIDI-sync clock source
```

CLI override for one run: `--midi-outputs 'Midi Out 1,KeyStep'`. A port
missing on this host (or an ambiguous substring) **warns and is skipped —
the show always starts**. A port that dies mid-show (USB yanked) is
dropped the same way and **stays dropped for that engine's life**: a
replug does NOT self-heal. Recovery is the normal supervisor path — kill
or crash ShowSync, it relaunches, KeyStep Play restarts the set from the
top with all configured ports reopened.

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

- Press **Play on the KeyStep**: the set restarts **from the top** (that
  is the restart semantic — there is no resume-from-position).
- To get back to the current song: in the **editor** window use
  **Skip** repeatedly (or click the song) and start from there. In
  `--headless` mode there is **no Skip** — the KeyStep can only restart
  from the top, which is why the editor-on-second-screen layout is the
  recommended gig setup.

### A song stalls (audio hung / silent, nothing crashed)

The supervisor only sees process exits, so a wedged-but-alive ShowSync is
a manual call:

1. First try the transport: KeyStep **Stop**, then **Play** (set restarts
   from the top; use the editor's Skip to return to the song).
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
start to music is: command, wait for "Starting Keyframes", KeyStep Play.

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
