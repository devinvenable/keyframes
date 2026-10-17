# Mac mini gig checklist (T248 — epic 246, show Nov 11/12 2026)

The software side is deployed and verified (2026-10-17): code + media live at
`~/src/2026/midi` on the mini, the venv passes both test suites
(ShowSync 832, Keyframes 371), `live_smoke_test.sh` is 39/39, and a real
headless ShowSync run delivered clock + Start/Stop through CoreMIDI to a
loopback destination. What remains needs **hands at the machine** — this is
the guided session, in order. Everything here is doable in one sitting of
~30 minutes plus one quiet-mini timing run.

## 0. Known machine facts (read first)

- **The mini's `/usr/local` is Intel Homebrew.** A plain `bash` resolves to
  x86_64 bash and runs children under Rosetta. The deployed venv's
  interpreter has been **lipo-thinned to arm64** so this cannot flip the
  show's Python; `scripts/deploy-mac.sh` re-applies the thin on every
  deploy because a venv rebuild restores the universal binary. The manual
  command, if ever needed:

  ```sh
  cd ~/src/2026/midi/venv/bin
  lipo python3.11 -thin arm64 -output python3.11.arm64
  mv python3.11.arm64 python3.11 && chmod +x python3.11
  ```

  One-line verify (must print `arm64`, run through bash so the Intel-bash
  parent case is the one tested):

  ```sh
  bash -c '~/src/2026/midi/venv/bin/python -c "import platform, rtmidi; print(platform.machine())"'
  ```

- Redeploy after any merge to main: `scripts/deploy-mac.sh` from the Linux
  checkout (syncs code + songs + banks/images, updates deps, re-thins,
  verifies arm64).

## 1. GO/NO-GO: quiet-mini clock timing run

The 2026-10-17 gate runs happened while **EOS Utility pinned a core at
~100% and Logic Pro X + an ffmpeg were running** (load 3.3). Run 1 failed
the gate on one genuine mid-run 16.9 ms send spike (σ 0.526); run 2 passed
cleanly (σ 0.169, worst 1.498 ms) under the same load. The known T67
20–33 ms *receive* spikes reappeared on ticks 3–5 in both runs and are
receiver cold-start, excluded by the restated gate. Verdict so far:
promising, not yet gig-clean.

- [ ] Quit EOS Utility, Logic Pro X, and anything else busy
      (`ps -Ao %cpu,comm -r | head`; load should be well under 1).
- [ ] Run twice; **both must print `"passed": true`**:

  ```sh
  cd ~/src/2026/midi/showsync
  ../venv/bin/python scripts/measure_jitter.py --seconds 30 --freeze-gc \
      --mirror-ports 3 --json docs/measurements/macmini-quiet-runN.json
  ```

- [ ] If a run fails, check whether the spike tick correlates with anything
      running (`scripts/analyze_jitter.py <json>` shows send vs delivery
      split per tick) — a genuine send spike on a quiet mini is a NO-GO and
      goes back to engineering.

## 2. Thru box / David's gear (hardware in the loop)

- [ ] Plug the thru box into the Quantum 2626 MIDI OUT (the mini's only
      hardware MIDI out; ShowSync resolves it by unique substring
      `Quantum`).
- [ ] Repeat one `measure_jitter.py` run with David's receiving device
      attached and listening — this is the "actual gig gear" re-run the
      verification doc calls for.
- [ ] Audible check: start a set headless (section 4 command), confirm the
      downstream drum machine locks tempo and re-anchors at a song
      boundary Stop/Start (D17 behavior).

## 3. KeyStep + projector + permissions (one combined pass)

- [ ] Plug in the KeyStep (through the Behringer — input-only, per the
      perform setup) and the projector.
- [ ] First GUI launch will raise macOS **microphone / input-monitoring /
      accessibility** prompts — answer them all now, at the machine; they
      cannot be answered over SSH (runbook: do this well before the gig).
- [ ] `scripts/live.sh songs/three-song-set.yaml` from a Terminal on the
      mini. Confirm:
  - [ ] ShowSync editor lands on the mini's own display, projector output
        on the projector. If the editor opens on the projector, relaunch
        with `--editor-screen INDEX`.
  - [ ] KeyStep Play starts the set (`--midi-transport` is injected by
        live.sh); Stop stops it.
  - [ ] KeyStep bottom key (MIDI note 41) triggers the first Keyframes
        slot; bank switching via F5/F6 works.
  - [ ] **Stacking (macOS has no always-on-top):** during a video song the
        projector covers Keyframes, and when it hides, Keyframes — not a
        stray window — is revealed. Keep nothing else on the projector
        display; don't click other windows mid-set.
- [ ] Kill Keyframes once (`kill -9` its pid) mid-set: the supervisor must
      relaunch it in the live bank while audio never stops.

## 4. Full live-path rehearsal (dress-rehearsal shape)

- [ ] Quiet mini (section 1 state), everything cabled:

  ```sh
  cd ~/src/2026/midi
  scripts/live.sh --headless songs/three-song-set.yaml
  ```

- [ ] KeyStep Play → set runs end-to-end; audio to the house via the
      Quantum (pass `--audio-device Quantum` if the default picks the
      wrong output); clock solid on David's gear; visuals on the
      projector.
- [ ] After the run, re-check `ps` — macOS may have throttled nothing, but
      note anything (Spotlight `mdworker` on fresh media, Time Machine)
      that woke up mid-set.

## Notes for the operator

- The show must not depend on per-song `midi:` playback (decision D11) —
  the set plays with or without it.
- Headless mode has no Skip/Restart controls; mid-set recovery notes are
  in `docs/live-show-runbook.md`.
- SSH session for anything long-lived: run inside the existing keep-alive
  session (midi:I6), or `nohup`/`tmux` on the mini.
