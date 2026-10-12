# Kaiju booster liftoff — task 305

A nine-second Blender continuation of `teaser2.mp4`, using the original
mountain-valley scene and skinned robot. All art outputs are separate from
Devin's originals in:

`/home/devin/src/2026/videdit/work/liftoff_305/`

## Review deliverables

- `kaiju_liftoff_shot.blend` — packed scene, 1920×1080, 24 fps, frames 1–217.
  Frame 1 is the join reference; render frames **2–217** when appending.
- `kaiju_liftoff_preview.mp4` — nine-second draft, sampled at 12 fps.
- `teaser2_with_liftoff_preview.mp4` — original teaser followed by the draft.
- `staging_contact_sheet.jpg` and `review_frames/` — six Cycles staging frames.
- `join_comparison.jpg` — exported teaser endpoint (left), draft join (right).
- `verification.json` — pose, body geometry, camera, ascent, ring fade and
  resource checks; `media_verification.json` — encoded video audit.

These are review artifacts. The final-quality sequence has not been rendered.
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
  --output /home/devin/src/2026/videdit/work/liftoff_305

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
