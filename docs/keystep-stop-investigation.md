# KeyStep Stop investigation — task 278, 2026-10-10

The available capture does not establish the cause of the reported Stop
regression. No production routing or transport behavior has been changed.
D17 remains the current configuration: ShowSync sends clock + transport
to KeyStep USB, and live.sh enables incoming realtime transport. D17
supersedes D15's proposed independent local transport. D16 still prohibits
an additional TBOX DIN clock feed into the thru box.

## Evidence and limits

Analyzed `logs/kf-midi-20261010.jsonl` in the main checkout:

| Input | Clock messages | Start | Stop / Continue |
|---|---:|---:|---:|
| TBOX Midi Out 1 (the physical input name in ALSA) | 1965 | 1 | 0 / 0 |
| ShowSync Cues | 1963 | 1 | 0 / 0 |
| RtMidiOut Client 132 | 200 | 0 | 0 / 0 |
| RtMidiOut Client 133 | 200 | 0 | 0 / 0 |

The two Starts are at +5.911546s (TBOX) and +5.911824s (Cues), relative
to the first `log_open`. The last first-run clock is about +50.013s;
a second `log_open` occurs at +203.358s, with clocks resuming at +203.396s.
The raw RtMidiOut inputs appear only in that second run, whose last clock
is at +208.369s. This is not evidence of four concurrent hardware clock
feeds throughout the take. The Cues stream is an intentional software
egress mirror; an input subscription does not itself route bytes to DIN.
The raw clients' physical destinations cannot be inferred from this log.

Keyframes records messages while draining inputs on its render thread
(`process_midi_messages`), not at the MIDI receive callback. System Stop
bypasses note-source filtering, but a hung render thread can stop logging.
There is no timestamp marking a deliberate button press in this capture.
Therefore zero logged Stop messages cannot distinguish absent transmission,
loss in the return path, or loss of observation during the T277 hang.

ShowSync's `connect_transport` handles only FA/FB/FC. Its `TransportControl`
drops all such input within one second of its own transport egress, to
prevent song-boundary echoes restarting the set. Outside that window a
Stop while playing closes the engines; `ClockEngine` emits Stop and ceases
clock. Existing transport, headless, and egress tests pass (53 tests).
This verifies the software behavior in isolation, not the hardware symptom.
The four probe tests also pass. Each was checked against a deliberate
mutation (drop Stop, delay clock reporting, accept ambiguous ports, or
disconnect the receive callback), and each failed at its expected assertion.
The implementation was restored and the four tests passed again. Input
enumeration on this host confirms that the default selectors each resolve
to one hardware port; no test sent MIDI into the rig.

## Manufacturer documentation

The [Arturia KeyStep manual 1.1.2](https://downloads.arturia.net/products/keystep/manual/KeyStep_Manual_1_1_2_EN.pdf)
documents external synchronization forwarding and local sequencer control
in section 6.2 (printed page 39). Section 8.10.3.12 (page 69) describes
Arm to Start separating local sequence activation from forwarded sync.
Section 8.10.5 (page 73) documents configurable CC/MMC transport messages.
It does **not** establish that receiving external Start suppresses a local
outgoing realtime Stop, or that selecting CC/MMC disables realtime output.
Those remain hypotheses requiring observation of this unit and its settings.

## Passive capture, independent of Keyframes

From the repository root, while the normal live session is running, launch
in a second terminal:

```sh
venv/bin/python scripts/midi_transport_probe.py --seconds 90 --output "$HOME/keystep-stop-$(date +%Y%m%d-%H%M%S).jsonl"
```

Before this branch is merged, use
`worktrees/transport-regression-keystep-stop-no-longer-stops-278/scripts/midi_transport_probe.py`
as the script path from the main checkout. `--list` prints inputs;
repeat `--port 'unique substring'` to override the defaults (`KeyStep`
and `Midi Out 1`). Missing/ambiguous inputs fail instead of guessing.
No MIDI output is opened and no clocks or transport are generated.
The output must be a new file. The probe captures CC and SysEx/MMC as well
as realtime transport, with epoch and monotonic timestamps. Clock summaries
contain count plus first/last callback times, and flush before other events.

ShowSync logs transport decisions at INFO by default; no extra environment
variable is needed. Append this to the normal live.sh launch command to
preserve its terminal output:

```sh
2>&1 | tee "$HOME/keystep-stop-showsync-$(date +%Y%m%d-%H%M%S).log"
```

After the probe prints `Listening`, start the set normally. Wait 10 seconds,
press KeyStep Stop, wait 3 seconds, Stop again, wait 3 seconds, Stop again.
Wait 5 seconds, press KeyStep Play, wait 10 seconds, press Stop. Note the
approximate wall-clock time of each press and whether the local sequence,
drums, and backing tracks stopped. Let the probe finish or Ctrl+C it after
the final press. Preserve both logs and the KeyStep sync/Arm to Start/
transport settings. These intervals avoid the one-second echo gate.

| Observation around a marked press | Next conclusion/check |
|---|---|
| Stop on USB and TBOX, ShowSync acts | Verify emitted Stop and cessation of clock at TBOX; inspect any later Start and the drum receiver |
| Stop on USB but absent from TBOX | Investigate DIN output/thru/return path; a return-jack capture does not locate the loss by itself |
| Stop on TBOX but ShowSync does not act | Compare transport INFO logs, input subscriptions and echo-window timing |
| CC/MMC only on both inputs | Compare bytes with MCC settings; current ShowSync does not interpret these as realtime Stop |
| No transport on either input while other traffic continues | Investigate device settings/firmware and external-sync behavior |

## Conditional configuration proposal for review

If an authorized A/B test proves external Start/Stop causes the loss of
KeyStep's own outgoing Stop, change only its `midi_outputs` entry from
`{port: KeyStep, send: [clock, transport]}` to
`{port: KeyStep, send: [clock]}`. Keep the USB sync clock, TBOX wiring, and
other ports unchanged for that experiment. Inspect effective run overrides:
bare `--midi-outputs` entries send full egress and can defeat setlist filters.

This is **not an applied or confirmed fix**. It removes D17's song-boundary
Stop/Start re-anchor, so verify sequence step-one alignment as well as Stop
authority before adopting it. Any topology/egress change requires Devin's
sign-off through the PM. Making Cues cue-only or removing raw clients is not
justified as a fix for hardware Stop by the current evidence.
