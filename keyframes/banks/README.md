# Bank note coverage

`mapping.json` is a sparse, exclusive mapping: each file gets one note.
A bank with 18 files does **not** automatically cover the 64 playable notes
(36–99 by default). The robot bank maps 41–92; brain-surgery maps 41–58.
Unmapped notes intentionally hold the current picture. Check the startup
`Mapped notes` list against the song's actual keyboard range before performing.

An optional `playback.json` in a bank folder can enable performance-only
cycling for unmapped notes:

```json
{"cycle_unmapped": true}
```

The default is false, including brain-surgery's checked-in configuration.
Explicit assignments always win. Other in-range notes cycle through media
in ascending assigned-note order, anchored to the lowest assigned note:
`(played_note - lowest_assigned_note) % number_of_assignments`.
This leaves the mapping file and grid assignments unchanged; grid cells
continue to show explicit assignments, not fallback aliases. Out-of-range
notes remain ignored. The default bank reads `images/playback.json`.
Bank switches reload this policy. Missing or invalid policy files disable it.

Brain-surgery has 14 stills (41–54) and four looping orbit GIFs (55–58),
480×480, 61 frames at 15 fps. It inherits global scenes and overlays.
