# Clock Divider — phosphor wire title

Start with `generated/clockdivider/laser-wide/laser-wide-preview.mp4`, then
`fly-wide/fly-wide-preview.mp4`. `contact-sheet.jpg` compares the six treatments;
`alpha-checkerboard.png` demonstrates compositing over a colored background.
Final renders are also copied to `/home/devin/src/2026/midi/generated/clockdivider/`
so they survive removal of the task worktree. Generated media is intentionally ignored
by Git; the six compact `.blend` scenes, source artwork, traced outlines and scripts
are versioned under `blender/clockdivider/`.

| Treatment | Motion | Duration / rate | Sizes |
| --- | --- | --- | --- |
| `laser` | Arc-length stroke drawing for 3.5s, with a slow turn continuing through the hold | 6s / 30fps | 1920×1080, 1080×1080 |
| `fly` | Complete title turns and approaches, then travels through and behind the camera | 6s / 30fps | 1920×1080, 1080×1080 |
| `orbit` | Extra experiment: continuous full 360° turntable | 6s / 30fps | 1920×1080, 1080×1080 |

Only `orbit` is a seamless loop (the unrendered frame 181 matches frame 1).
`laser` is an entrance followed by a hold; `fly` is an entrance/exit. They are intended
as triggered overlays. A full turn deliberately shows the reversed back of the wire
letters, as a real 3D object would.

## What was recovered

Read-only headless excavation inspected curve datablocks in **275 `.blend` files**
under `~/src/blender`, with no read failures. None contains text matching Clock Divider
or cloc.kdivider. This establishes what remains in these saved files, not what may
have existed in earlier unsaved work. `excavation.json` records all file paths, text counts and matching
bodies; `workshop.json` records the eight laser workshop scenes and their actions.

`laser/lazer 2.blend` (frames 1–120) has two animated planes (`PlaneAction` and
`PlaneAction.002`) and uses `clockdivider-long2.png`; it has no text geometry. The
`gear thing` scenes animate gears and the camera, not a title. The `public domain`
scenes reference the old clock MP4 renders in larger video compositions.

The actual logo is **small CLOC. + large KDIVIDER**, with a shared baseline and stepped
pixel letterforms. Its font name was not recoverable from saved text datablocks.
Rather than substitute a similar font, this asset traces the original pixels:

- `reference-lockup.png`: exact copy of `laser/clockdivider-long.png` (1920×1080),
  used for the wide treatment; 17 closed contours, 210 corners.
- `reference-tall.png`: exact copy of `laser/clockdivider-long2.png` (1920×3582),
  used for the square treatment; 17 closed contours, 258 corners. Its taller letter
  proportions are preserved, with empty surrounding source pixels cropped away.

The source resolves the spelling choice, so both formats retain that original lockup.
No substitute font or uppercase redesign is required. These source images are Devin's
existing artwork; the scenes have no external font or image dependency.

## Rebuild and edit

Tested with Blender **5.1.2** and FFmpeg 7.1.1; requires FFmpeg with `prores_ks` and `libx264`. Python's standard
library is enough to orchestrate rendering. Pillow is only needed to retrace the PNGs
or run the artifact QA script. GPU rendering prefers an OptiX RTX 3060, then any
available OptiX device; otherwise it falls back to CPU.

From the repository root:

```sh
# All six scenes, sequences and movies. Default is one render at a time.
python3 blender/clockdivider/render_all.py --jobs 3

# One scene or one proof, without invoking the full batch.
blender -b -t 4 --python-exit-code 1 --python blender/clockdivider/build.py -- \
  --treatment laser --format square --frame 120
blender -b -t 4 --python-exit-code 1 --python blender/clockdivider/build.py -- \
  --treatment fly --format wide --render

# Package completed sequences again without rendering.
python3 blender/clockdivider/render_all.py --package-only

# Requires Pillow in the selected Python environment.
python3 blender/clockdivider/verify.py
```

`--output PATH` selects another media destination. Batch rendering resumes existing
frames; remove that variant's generated PNG sequence before rebuilding after artistic
changes. Single-scene `build.py --render` overwrites frames unless `--resume` is supplied.
All runs are background Blender processes; no running desktop session is controlled.

Every `.blend` contains reusable native POLY curve datablocks for front outlines,
rear outlines and depth connections, plus an animated `TITLE • animated transform`
parent. The `Clock Divider - title` collection is marked as an asset; append that
collection into a new scene to bring the complete title hierarchy, or reuse `outlines.json` /
`outlines-tall.json` to construct new treatments without retracing. Laser drawing uses
keyframed `bevel_factor_end`; motion uses native transform keyframes. There are no
frame handlers, external add-ons or auto-run scripts required to play the scenes.

The material is approximately sRGB `#00FF66`, with dimmer depth lines. Only contours
and depth edges are present—no distracting triangulation diagonals. Cycles renders
64 samples with persistent scene data with Standard color management. The compositor adds a restrained fog glow
and extends alpha to include that glow. The background remains transparent.

## Formats and verification

Each `<treatment>-<format>/` directory contains:

| File | Transparency |
| --- | --- |
| `png/frame_0001.png` … `frame_0180.png` | **Real RGBA**, straight alpha; preferred master |
| `*-alpha.mov` | **Real ProRes 4444 alpha**, encoded `yuva444p10le`; FFprobe decodes as `yuva444p12le` |
| `*-preview.mp4` | **Opaque black**, H.264 `yuv420p`; quick review only |

Transparent pixels can retain green RGB data; a viewer that ignores alpha may show a
solid green field. Use an alpha-aware compositor or the explicitly flattened MP4.
Do not chroma-key green: it is the artwork itself.

`verify.py` checks all 1,080 PNGs for RGBA, dimensions and sequential frame names;
checks six movie pairs for frame counts, 30fps and expected pixel formats; and decodes
a frame from every MOV to compare its alpha against the source PNG. It also checks
that the laser starts empty and grows, and that fly-past finishes outside the camera.
`verification.json` contains the measured results. Review the contact sheet for motion
and the 480px-wide proofs for small-size letter and depth readability.

The application and its overlay playback code are unchanged.

Verification completed 2026-10-04: all 1,080 RGBA frames and all 12 videos passed.
Decoded MOV alpha mean error ranged from 0.0017 to 0.0063 on the 0–255 scale.
All six native scene checks passed, including the marked title collection, laser
completion, camera exit and turntable closure. A deliberately opaque RGBA sequence
failed the QA transparency assertion as expected. Committed evidence is in `review/`.
