# midi

This repository hosts two independent programs for Devin and David's live show:
**Keyframes** (MIDI-triggered visuals) and **showsync** (backing-track player +
MIDI clock master).

- [`keyframes/`](keyframes/README.md) — real-time MIDI-triggered image and
  video display for live performance. Run it from `keyframes/`
  (`python main.py`); the Windows release is built with
  `keyframes/scripts/build-windows.sh`.
- [`showsync/`](showsync/README.md) — live-performance backing-track player
  that emits MIDI clock so external hardware stays tempo-locked.
  Requirements spec only — no implementation yet.

Repo-level infrastructure (`docs/`, `scripts` inside each subproject, agent
tooling) stays at the root; each program is self-contained in its directory.
