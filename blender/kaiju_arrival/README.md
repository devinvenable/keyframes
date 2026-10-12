# Beetle-knight arrival — T311

A 108-frame / 24 fps / 4.5-second draft shot. Both creatures remain in the sandstone scene, facing each other 650 units apart.
The robot is entirely behind the arrival camera for a later reverse shot. The
arrival opens on the empty valley; the beetle leaps in from screen left, plants both
feet at frame 52, compresses into the landing, and settles into a guarded pose.
A fixed-position camera pans toward the beetle and zooms from 32 to 72 mm over
frames 46–63. A brief impact recoil accompanies the low powder burst and rigid
ballistic dirt fragments. All beetle motion uses the approved rigid FK controls.

Artifacts live in `/home/devin/src/2026/videdit/work/kaiju_arrival_311_beetle_only/`:

- `beetle_arrival.blend`: baked animation, opens at frame 86; Blender 5.1.2.
- `beetle_arrival_preview.mp4`: silent 960×540, 24 fps timing preview.
- `key_beats.jpg`: labeled six-beat contact sheet.
- `final_stills/frame_0001.png`: empty valley establishing.
- `final_stills/frame_0040.png`: beetle airborne.
- `final_stills/frame_0052.png`: initial sole contact and powder onset.
- `final_stills/frame_0058.png`: spreading dirt and powder during the fast zoom.
- `final_stills/frame_0063.png`: end of the zoom.
- `final_stills/frame_0086.png`: settled fighting pose.
- `verification.json`, `media_verification.json`: scene and encoded-media checks.

Earlier `draft_stills` and `revised_stills` are preserved iteration references;
use `final_stills` for the delivered dust timing. Preview frames use 8 Cycles
samples, stills 16, with denoising and the recovered film compositor. This is
review footage, not a final-resolution delivery; fine grit and volumetric detail
can shimmer at these draft sample counts. There is no sound design.

## Reproduce

Run from this repository root. All writes go into a new output directory; never
use the T307 source directory as the output. The original T307 review manifest
provides SHA-256 hashes, checked again during packaging.

```bash
SHOT=/home/devin/src/2026/videdit/work/kaiju_arrival_311_beetle_only
BLENDER=/home/devin/bin/blender-5.1.2-linux-x64/blender
GRADE_BLENDER=/home/devin/bin/blender-4.1.1-linux-x64/blender

"$BLENDER" -b --python-exit-code 1 --python blender/kaiju_arrival/build.py -- \
  --source /home/devin/src/2026/videdit/work/kaiju_beetle_307/beetle_faceoff.blend \
  --output "$SHOT"

"$BLENDER" -b "$SHOT/beetle_arrival.blend" --python-exit-code 1 \
  --python blender/kaiju_arrival/render.py -- --output "$SHOT/preview_exr" \
  --frames all --samples 8 --percent 75 --device 3060

"$BLENDER" -b "$SHOT/beetle_arrival.blend" --python-exit-code 1 \
  --python blender/kaiju_arrival/render.py -- --output "$SHOT/final_still_exr" \
  --frames 1,40,52,58,63,86 --samples 16 --percent 75 --device 1050

"$GRADE_BLENDER" -b --python-exit-code 1 --python blender/kaiju_arrival/grade.py -- \
  --input "$SHOT/preview_exr" --output "$SHOT/preview_frames"
"$GRADE_BLENDER" -b --python-exit-code 1 --python blender/kaiju_arrival/grade.py -- \
  --input "$SHOT/final_still_exr" --output "$SHOT/final_stills"

"$BLENDER" -b "$SHOT/beetle_arrival.blend" --python-exit-code 1 \
  --python blender/kaiju_arrival/verify.py -- --output "$SHOT/verification.json" \
  --negative-checks
/home/devin/src/2026/videdit/venv/bin/python blender/kaiju_arrival/package.py --directory "$SHOT"
```

The renderer selects CUDA devices by name substring. Change `--device` for a
different workstation. Python packaging requires Pillow, ffmpeg and ffprobe; the existing videdit venv
provides Pillow on this workstation.
No paid or newly downloaded landscape assets are used. Existing T307 sandstone,
PBR ground, overcast HDRI, robot, and beetle are reused; additional sandstone
pieces share existing mesh data. New ground grit, powder volumes, and airborne
dirt are authored by this builder. The unrelated legacy village import is
removed from the derivative scene only.

## Film and motion verification

Native scene-linear half-float EXRs go straight through the SHA-pinned recovered
`kaiju_1960s` compositor in Blender 4.1.1, then AgX with exposure −0.8. The profile
adds the same grain, vignette, bloom and chromatic aberration used for T309.
Inverse AgX and the separately estimated −3-code-value reconstruction trim
belonged to the 8-bit salvage path; neither is needed for these native renders.

The scene verifier measures airborne clearance, contact, lens endpoints,
framing, opponent separation and robot exclusion throughout the shot, and rigid construction.
Seven in-memory negative mutations remove leap height, raise contact above the
ground, remove the zoom, suppress the dust, shift powder onset early or late, and restore the superseded
visible robot placement; each must fail its intended
assertion, then pass after exact restoration. The unanimated T307 source also
fails the new shot-duration assertion. Mutated scenes are never saved.

The final media check counts decoded frames, checks resolution/rate/duration,
fully decodes the MP4, and re-hashes every original T307 artifact. Visual review
of the graded frames remains necessary: the first pass passed geometric checks
but its inherited fog swallowed the foot contact and dust. The final shot uses
thin ground haze, an immediately expanding powder skirt, and fading dust density.

The earlier `/home/devin/src/2026/videdit/work/kaiju_arrival_311/` renders are
superseded staging with a visible robot. The delivered beetle-only framing keeps
the robot in the scene and out of frame throughout all 108 frames.

For the robot shot, switch the scene camera to **Robot reverse | same tripod**.
It is aimed at the persistent robot mark at 50 mm. **SceneCamera** retains the
complete approved beetle arrival animation. Named **Shot target** empties mark
both opponents for subsequent camera work; switching cameras does not re-stage
either character. The reverse camera is a saved starting composition, not a
rendered or approved robot-shot deliverable.
