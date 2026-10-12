# Kaiju booster liftoff — tasks 305 and 306

A nine-second Blender continuation of `teaser2.mp4`, using the original
mountain-valley scene and skinned robot. All art outputs are separate from
Devin's originals in:

`/home/devin/src/2026/videdit/work/liftoff_305/`

## Cinematic camera revision (T306)

`kaiju_liftoff_shot.blend` remains the untouched approved T305 baseline.
`kaiju_liftoff_cinematic.blend` changes only its camera animation. Every camera
sample through frame **111** is identical, including quarter-frame samples.
After full thrust, the camera sweeps left and pulls back, then cranes from 1.5
to 22.1 world units. It tilts into the sky and finishes the move at frame 205,
leaving a half-second slow glide. Lens stays at 12 mm. Robot, ring, hatch,
booster, exhaust and dust animation remain unchanged.

The rise is delayed until frame 144: the original shallow fog volume has a
visible flat upper boundary from elevated viewpoints. Once the camera leaves
the haze, even the bottom of its view points above the horizon. This keeps the
finite stage out of shot without changing the environment or effect assets.

`cinematic_verification.json` records comparison against the actual packed
baseline, including geometry, used packed textures, materials, lights, camera
data, render settings, non-camera actions and every evaluated animation frame.
Blender discards unused image datablocks on save, so only images with users
participate. Negative controls reopen the candidate before each in-memory
mutation; none of the saved assets are changed. The original passive camera,
a changed join key, altered lift, and abrupt camera jump must all fail.

The refreshed draft uses `cinematic_v4_frames/` and the same public preview
filenames below. Frames 2–110 reuse the approved 8-sample images because both
the scene and camera match exactly; later frames are newly rendered. The old
previews are preserved as `*_approved_t305.mp4`.

Devin pre-approved the final render on 2026-10-11, relayed by `pm-midi-1` during
T306. No further visual approval is required after draft QA. The actual source
settings are **4096 maximum Cycles samples, adaptive threshold 0.01, original
volume quality and AgX color settings**, not the 64-sample cap in the saved
T305 draft. `render_final.py` restores those settings from the source before
rendering every frame 2–217 at 1920×1080/24 fps. The final artifacts are:

- `kaiju_liftoff_final.blend` — packed scene with restored source quality.
- `cinematic_final_frames/` — 216 native frames and render settings/provenance.
- `kaiju_liftoff_final.mp4` — 216 frames, 9 seconds, 1080p24.
- `teaser2_with_liftoff_final.mp4` — 652 frames, 27.1667 seconds, 1080p24.
- `final_media_verification.json` — frame counts, dimensions, decode checks,
  content hashes and render settings. Its PASS confirms encoding completed;
  a running render alone is not a completed deliverable.

The extension remains silent. No sound design is added by this camera task.

```bash
blender -b /home/devin/src/2026/videdit/work/liftoff_305/kaiju_liftoff_shot.blend \
  --python-exit-code 1 --python blender/kaiju_liftoff/rework_camera.py -- \
  --output /home/devin/src/2026/videdit/work/liftoff_305/kaiju_liftoff_cinematic.blend

blender -b --python-exit-code 1 --python blender/kaiju_liftoff/verify_camera.py -- \
  --baseline /home/devin/src/2026/videdit/work/liftoff_305/kaiju_liftoff_shot.blend \
  --candidate /home/devin/src/2026/videdit/work/liftoff_305/kaiju_liftoff_cinematic.blend \
  --output /home/devin/src/2026/videdit/work/liftoff_305/cinematic_verification.json \
  --negative-controls

blender -b /home/devin/src/2026/videdit/work/liftoff_305/kaiju_liftoff_cinematic.blend \
  --python-exit-code 1 --python blender/kaiju_liftoff/render_preview.py -- \
  --output /home/devin/src/2026/videdit/work/liftoff_305/cinematic_v4_frames \
  --animation --step 2 --percent 33 --samples 8

python3 blender/kaiju_liftoff/package_preview.py \
  --directory /home/devin/src/2026/videdit/work/liftoff_305 \
  --frames-directory /home/devin/src/2026/videdit/work/liftoff_305/cinematic_v4_frames \
  --reference /home/devin/src/2026/videdit/work/liftoff_refs/teaser2.mp4

blender -b --python-exit-code 1 --python blender/kaiju_liftoff/render_final.py -- \
  --source /home/devin/src/2026/videdit/work/kaiju_mountain_valley.blend \
  --candidate /home/devin/src/2026/videdit/work/liftoff_305/kaiju_liftoff_cinematic.blend \
  --output /home/devin/src/2026/videdit/work/liftoff_305/cinematic_final_frames \
  --save-scene /home/devin/src/2026/videdit/work/liftoff_305/kaiju_liftoff_final.blend

python3 blender/kaiju_liftoff/package_final.py \
  --directory /home/devin/src/2026/videdit/work/liftoff_305 \
  --reference /home/devin/src/2026/videdit/work/liftoff_refs/teaser2.mp4
```

The renderer writes a temporary PNG before atomically accepting each frame.
Resume uses the same command and checks input hashes/settings against the
manifest; use a fresh directory when either changes. Never reduce render quality
just to resume an existing final sequence. The RTX 3060/OptiX is the final device.

### Overnight job and completion contract

`run_final.py` performs preflight, rendering, encoding, source-integrity checks
and completion/failure notification to the PM. Run it from a copied
`render_job_306/` bundle under the output directory, with `render_final.py`,
`package_final.py`, `package_preview.py` and `asset_hashes.json` alongside it.
This lets the render survive worktree cleanup. Its `--preflight-only` mode checks
the candidate hash against camera QA, all four negative controls, the audited
draft hashes/frame counts and original asset hashes without rendering.

The overnight unit is `midi-liftoff-306.service` in the user systemd manager.
Status is in `final_job_status.json`; complete logs are in `final_job.log`.
`phase: COMPLETE` requires both encoding and source-quality audit to pass.
Verify `final_media_verification.json` has `status: PASS`, 216 extension frames,
652 joined frames, 1920×1080 and `24/1` on both videos, plus a 4096-sample cap,
0.01 adaptive threshold and original volume settings. A `FAILED` status includes
the exception and is reported to the PM. Check logs before restarting the unit;
accepted PNGs resume while partial `pending_*.png` files are rendered again.

On 2026-10-11 the PM explicitly authorized handing off a running overnight job:
push all code, leave the job self-contained, and report render status plus these
verification criteria in `axon done`. The PM will pick up the completed result.
Such a handoff is not a claim that the final movie already exists.

## T305 baseline and preview deliverables

- `kaiju_liftoff_shot.blend` — packed scene, 1920×1080, 24 fps, frames 1–217.
  Frame 1 is the join reference; render frames **2–217** when appending.
- `kaiju_liftoff_preview.mp4` — nine-second draft, sampled at 12 fps.
- `teaser2_with_liftoff_preview.mp4` — original teaser followed by the draft.
- `staging_contact_sheet.jpg` and `review_frames/` — six Cycles staging frames.
- `join_comparison.jpg` — exported teaser endpoint (left), draft join (right).
- `verification.json` — pose, body geometry, camera, ascent, ring fade and
  resource checks; `media_verification.json` — encoded video audit.

These T305 artifacts were the approved draft; see T306 above for final outputs.
The draft is silent during the extension; ignition, mechanical and flight sound
design remain a separate creative pass. Low samples soften dust and metal detail.

## Choreography and inventions

| Extension time | Beat |
| --- | --- |
| 0–0.58 s | Existing ring reflections finish and disappear. |
| 0.9–2.6 s | Two dorsal armor doors unlock and swing outward. |
| 1.7–3.7 s | Twin engine cassettes rise from the back bay, then sweep around the shoulders on hydraulic yokes. Firing arm settles into a brace. |
| 3.9–5.0 s | Pilot throats ignite, white/amber jets grow, warm light reaches the sandstone, dust spreads, body compresses before release. |
| 5.0–9.0 s | Heavy, accelerating vertical climb clears the arch. Camera continues its ground drift, curves left to reveal the machinery, and tilts upward. |

The additions use the robot's rectangular armor, rivets and dark metal language:
faceted nozzle bells, cooling collars, bolted ribs and paired piston supports.
The nozzles point **vertically down in world space**. Their apparent outward
splay in the low wide-angle view is perspective, not a sideways thrust vector.

The original robot mesh and skin weights are retained. Only the two triangles
forming the rear torso face are replaced by articulated hatch leaves. There are
no new leg pods. Jets and dust are deterministic Blender geometry/materials and
keyframes, so no external simulation bake or AI-generated frame is needed.

## Continuity and limitations

The supplied mountain-valley blends were saved with a later village camera.
`camera_match.json` recovers the low **12 mm** firing view from the actual teaser
endpoint: SIFT correspondences, Blender raycasts, RANSAC and a fit constrained to
the historical camera rail. The matched landmarks have about 1.2 px RMS error at
960×540. This measures camera alignment, not pixel-identical grading/lighting.
The exported teaser frame is also the authority for the robot pose. A measured
three-landmark fit adjusts the firing arm; nine body landmarks set a 0.87% scale
correction and small X/Z position offsets. Arm/body landmark errors are 1.52/1.37
pixels RMS at 960×540. `pose_landmarks.json`, `match_pose.py` and `pose_match.json`
record the measurements and reproducible fit. The original mesh geometry and
skin weights remain intact. The corrected join is in `join_comparison.jpg`;
softness/grade remains an accepted preview artifact for final rendering.

The reference rings have already left the photographed view. During the brief
carryover their camera visibility is disabled while their actual glossy and
lighting contributions continue. Their geometry scales away at frame 15. Ring
material animation is rebased along with transforms; later source volleys cannot
reappear during ascent. The booster throats have their own blue pilot light.

EEVEE was tried but lost too much atmospheric/reflection continuity. The motion
preview uses Cycles at 634×356 and 8 samples, with every other 24 fps scene frame
rendered for a 12 fps draft. Final settings remain 1080p24 in the saved blend.
The full teaser preview repeats each draft image at 24 fps; it does not invent
intermediate motion. Framing, timing and machinery are ready for visual review;
polished exhaust/dust and sound can follow that review.

## Rebuild and render

Run from the repository root with Blender 5.1.2 and the original source assets:

```bash
blender -b /home/devin/src/2026/videdit/work/kaiju_mountain_valley.blend \
  --python-exit-code 1 --python blender/kaiju_liftoff/build.py -- \
  --output /home/devin/src/2026/videdit/work/liftoff_305/rebuild_306

blender -b /home/devin/src/2026/videdit/work/liftoff_305/kaiju_liftoff_shot.blend \
  --python-exit-code 1 --python blender/kaiju_liftoff/render_preview.py -- \
  --output /home/devin/src/2026/videdit/work/liftoff_305/matched_preview_frames \
  --animation --step 2 --percent 33 --samples 8

python3 blender/kaiju_liftoff/package_preview.py \
  --directory /home/devin/src/2026/videdit/work/liftoff_305 \
  --reference /home/devin/src/2026/videdit/work/liftoff_refs/teaser2.mp4

blender -b --python-exit-code 1 --python blender/kaiju_liftoff/verify.py -- \
  --source /home/devin/src/2026/videdit/work/kaiju_mountain_valley.blend \
  --candidate /home/devin/src/2026/videdit/work/liftoff_305/kaiju_liftoff_shot.blend \
  --output /home/devin/src/2026/videdit/work/liftoff_305/verification.json
```

The renderer targets the RTX 3060 via CUDA or OptiX. It resumes existing PNGs; use a fresh
output directory after changing the scene. `build.py` overwrites only its named
output blend, never its input, and packs external image resources before saving.

`inspect_scene.py` inventories an original scene without modifying it.
`match_camera.py` contains the camera recovery stages. The checked-in numerical
fit lets normal rebuilds avoid repeating that photogrammetry work.

## Preparing a new shot from the valley scene

T307 adds `restore_teaser_state.py` for new shots that expose the saved scene's
reflective robot override, HDRI hillside or flat fog boundary. It restores the
native robot's mesh, weights and ten material assignments, then uses named
material copies to reconstruct the footage's charcoal palette. It retains the
original ground textures and HDRI lighting, with a camera-only upper-sky sample
and height-faded fog. The original robot asset and source scene stay untouched.

This is an **opt-in continuity reconstruction**, not a modification of the
accepted T305/T306 scenes, nor a pixel-exact recovery of the teaser setup. Its
robot materials remain nonemissive; blue reflections/spill come from lighting.
Camera matching remains a separate step. See the [beetle builder notes](../kaiju_beetle/README.md)
for the reviewed look, source reference, use as a Python helper, and validation.
For a separate prepared scene:

```bash
blender -b /home/devin/src/2026/videdit/work/kaiju_mountain_valley.blend \
  --python-exit-code 1 --python blender/kaiju_liftoff/restore_teaser_state.py -- \
  --output /home/devin/src/2026/videdit/work/new_shot/teaser_prepared.blend
```
