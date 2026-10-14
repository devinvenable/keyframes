# T333 — approved round 07 full-quality render

Devin approved round 07 on 2026-10-14 (`midi:D23`). The final pipeline renders
all 192 frames at 1920×1080, 24 fps and 64 samples, using both GPUs. The scene
is a byte-identical copy of the approved `round_07/unified.blend`; it is never
rebuilt or saved by the render or QA scripts. `verify_final.py` also hashes
non-camera transforms/visibility, geometry, and camera matrices/lens/shifts over
all 192 frames, with deliberate mutations that must fail each parity check.
Existing round-07 scene/pixel checks and actual earlier-scene negative controls
run before rendering. Native EXRs pass through the pinned Blender 4.1.1
`kaiju_1960s` grade and CRF16 encode. Full decode compares every encoded frame
with its graded source and retains native/graded hashes.

Output: `/home/devin/src/2026/videdit/work/kaiju_flight_unified_325/final/`.
The pipeline emits `unified_flight_impact_final.mp4`, `SHA256SUMS`, `review.html`,
decoded beat stills, and `final_verification.json` only after media QA passes.

Delivered final: 192 frames / 8.000 seconds, 1080p, 24 fps, 64 samples, CRF16.
Full decode and all 192 encoded/source comparisons pass (maximum MAE 1.861);
384 native/graded frame hashes are retained. Scene byte SHA-256 matches approved
round 07 exactly, with matching all-frame performance/geometry/camera hashes.
All scene, rendered-mask, actual earlier-scene and in-memory negative controls
passed, including deliberate final-camera and geometry changes, wrong media
source, and a missing review link. The decoded 13-beat sheet and 65-sample motion
sheet were inspected through the final settle. Durable evidence lives in
`final_333_results.json` and `final_333_beats.jpg`.

The initial dual-GPU assignment completed frames 1–184. The last eight were
reassigned as 185–189 on the 3060 and 190–192 on the 1050 Ti. All 184 preserved
EXR hashes remained unchanged. No creative scene changes were made.

MP4 SHA-256:
`74ed88917ced60856c00ac0254eb7493e3e9d4c3973a468a667cf6f610479de7`.

```bash
ROOT=/home/devin/src/2026/videdit/work/kaiju_flight_unified_325
mkdir -p "$ROOT/final"
setsid -f /home/devin/src/2026/videdit/venv/bin/python blender/kaiju_unified/final.py \
  --source "$ROOT/round_07" --directory "$ROOT/final" \
  > "$ROOT/final/pipeline.log" 2>&1 < /dev/null
# After FINAL_VERIFIED, generate decoded motion sampling and check review links:
/home/devin/src/2026/videdit/venv/bin/python blender/kaiju_unified/review_final.py \
  --directory "$ROOT/final"
```

If one GPU finishes first, stop the old pipeline/workers before resuming with
`--rebalance`. Preserve the render logs and quarantine any EXR without a completed
`ARRIVAL_RENDER` log marker. Record completed-frame hashes in
`render_interruption.json` (`preserved_native_sha256`, keyed by filename); the
pipeline verifies these remain unchanged. The resume assigns two thirds of the
missing frames to the 3060, records `render_allocations.json`, archives old logs,
and reruns preflight under the identical scene/settings plan.

## Historical T331 — close camera through crash, slide and settle

Current review candidate:
`/home/devin/src/2026/videdit/work/kaiju_flight_unified_325/round_07/`.

Round 07 patches the actual saved round 06. Only camera keys after frame 124
change. The camera follows the head as the hinged body crumples and eases closer
to maintain the impact's projected body height. Its orientation and 42 mm lens
stay fixed. Frames 1–124 retain the approved camera exactly; all non-camera
object transforms, visibility and mesh coordinates remain identical to round 06.

The review excerpt now covers frames 100–192: 93 frames / 3.875 seconds at
960×540, 24 fps, eight samples, pinned Blender 4.1.1 `kaiju_1960s` grade, CRF18.
`review.html` includes the clip, ten decoded beat stills, the motion strip and a
round-06/round-07 slide comparison. No full 1080p/64 render is authorized yet.

`verify_331.py` checks every frame 124–192 for projected height 1.85–2.30 screen
heights, 43–67% bottom crop, and the whole head inside the frame. It retains the
approved fly-with checks and independent whole-mesh solidity at every frame
113–192, centered torso contact, constant airborne speed and debris clearance.
It also compares all non-camera transforms and visibility on all 192 frames,
mesh coordinates, and the original camera through frame 124 against round 06.
Negative controls use the actual round-06 scene plus in-memory mutations; no
verification script saves a mutated scene. Rendered masks include the final
frame 192, bilateral rock pixels at impact and unobstructed slide visibility.

Measured post-impact projected height is 2.051 screen heights, with 53.5–58.6%
bottom crop. Head bounds remain inside the frame on every frame 124–192.
Actual round 06 fails the new size floor at frame 130 (height 1.750). Negative
controls also reject excessive crop, an out-of-frame head, a wide final frame,
a changed slide pose, changed approved camera keys and changed mesh coordinates.
Camera preservation error through frame 124 is exactly zero. The rendered
frame-124 torso band retains 1,572 left and 5,005 right rock pixels; mid-slide
beetle visibility is 100% of the otherwise identical no-sandstone render.

Delivered media QA passes: full decode, all 93 encoded/source comparisons
(maximum MAE 2.257), and 186 native/graded frame hashes.
The decoded beat sheet and every-third-frame motion strip were reviewed through
frame 192. Durable Git evidence: `draft_331_results.json` and
`draft_331_beats.jpg`. MP4 SHA-256:
`3504c5f9ffdb4a2c15112ed4347d38c84abb074b1108d2439d2eb411245b4f0e`.

## Reproduce round 07

```bash
BLENDER=/home/devin/bin/blender-5.1.2-linux-x64/blender
ROOT=/home/devin/src/2026/videdit/work/kaiju_flight_unified_325
SHOT="$ROOT/round_07"
"$BLENDER" -t 6 -b --python-exit-code 1 \
  --python blender/kaiju_unified/revise_331.py -- \
  --source "$ROOT/round_06/unified.blend" --output "$SHOT"
"$BLENDER" -t 6 -b "$SHOT/unified.blend" --python-exit-code 1 \
  --python blender/kaiju_unified/verify_331.py -- --directory "$SHOT" \
  --baseline "$ROOT/round_06/unified.blend" --negative-checks
"$BLENDER" -t 6 -b "$SHOT/unified.blend" --python-exit-code 1 \
  --python blender/kaiju_unified/verify.py -- --directory "$SHOT" --negative-checks
"$BLENDER" -t 6 -b "$SHOT/unified.blend" --python-exit-code 1 \
  --python blender/kaiju_unified/pixel_contract.py -- --directory "$SHOT" --negative-checks
setsid -f /home/devin/src/2026/videdit/venv/bin/python blender/kaiju_unified/draft.py \
  --directory "$SHOT" > "$SHOT/pipeline.log" 2>&1 < /dev/null
```

## Historical T330 — centered torso smash and head/torso fly-with

Current review candidate:
`/home/devin/src/2026/videdit/work/kaiju_flight_unified_325/round_06/`.

Delivered: `review.html`, `impact_draft.mp4`, decoded beat stills, and
`motion_sampling.jpg`. The clip is 81 frames / 3.375 seconds at 960×540, 24 fps,
eight samples, pinned Blender 4.1.1 `kaiju_1960s` grade, and CRF18. Full decode and
all 81 source comparisons pass (maximum MAE 2.257); 162 native/graded frame hashes
are retained. Durable Git evidence: `draft_330_results.json` and
`draft_330_beats.jpg`. MP4 SHA-256:
`ff0231e715bec2aa8b8761a6a5ee3f7a7a70d595ef1666e5e86caf1d912004f2`.

Measured bottom crop is 57.6–59.2%. The closest left/right rear-shell distances
at impact are 0.424 / 0.524 units; feet remain roughly 13 units clear of the face.
Airborne speed is constant at 6.852 units/frame, with essentially zero lateral
travel. The frame-124 torso band contains 1,572 rock pixels on the left and
5,005 on the right. Mid-slide rendered beetle visibility is 100% relative to the
same frame without sandstone. Contact/launch transform error is zero.

Round 06 removes the 26-unit lateral detour. It restores the original centered
strike station, broadens the sandstone formation, and recesses the lower ledges
so the rear torso reaches the face with both feet clear. The original sandstone
UVs and materials remain; its geometry is deliberately reshaped for this revision.
The background rocks are restaged behind the face and stay fixed from frame 1.
All contact/launch actor transforms and hinge timing remain unchanged.

The camera frames head and torso with about 60% bottom crop throughout frames
106–124, follows at a fixed beetle-relative offset, then opens out over 30 frames
to reveal the outside slide and slump. The elevated shoulder-side position clears
the robot's raised hatches at first contact. At frame 124, rock pixels are visible
on both sides of the torso, and fragments appear on that same frame.

`verify_330.py` reuses the independent whole-mesh BVH/parity checks for every frame
113–192, and checks centered flight, bilateral rear-shell proximity, head bounds,
bottom crop, constant airborne speed, and preserved contact/launch transforms.
The actual round 05 fails the crop and centered-flight assertions. Its rendered
impact mask also fails the bilateral-rock assertion: zero rock pixels appear to
the left of its torso. Actual round 04 still fails solidity and slide visibility.
Additional scene mutations exercise penetration, missing torso contact, a frozen
camera, excessive bottom crop, and a cropped head. These controls run after the
implementation commits; scenes are never saved by verification.

Relocated fragments are integrated again against the ground plane, preserving
gravity and damped bounces. The internal `round_06_pre_effects/unified.blend`
captures the unfixed translated trajectories and must fail the ground-clearance
check. Keep that negative baseline alongside round 06 when reproducing QA.

Only the 81-frame 540p/eight-sample review excerpt is rendered. The full
1080p/64-sample render remains pending Devin's impact approval.

## Reproduce round 06

```bash
BLENDER=/home/devin/bin/blender-5.1.2-linux-x64/blender
ROOT=/home/devin/src/2026/videdit/work/kaiju_flight_unified_325
SHOT="$ROOT/round_06"
"$BLENDER" -t 6 -b --python-exit-code 1 \
  --python blender/kaiju_unified/revise_330.py -- \
  --source "$ROOT/round_05/unified.blend" \
  --performance "$ROOT/round_04/unified.blend" --output "$SHOT"
"$BLENDER" -t 6 -b "$SHOT/unified.blend" --python-exit-code 1 \
  --python blender/kaiju_unified/verify_330.py -- --directory "$SHOT" \
  --baseline "$ROOT/round_05/unified.blend" --negative-checks
"$BLENDER" -t 6 -b "$SHOT/unified.blend" --python-exit-code 1 \
  --python blender/kaiju_unified/verify.py -- --directory "$SHOT" --negative-checks
"$BLENDER" -t 6 -b "$SHOT/unified.blend" --python-exit-code 1 \
  --python blender/kaiju_unified/pixel_contract.py -- --directory "$SHOT" --negative-checks
"$BLENDER" -t 6 -b "$ROOT/round_05/unified.blend" --python-exit-code 1 \
  --python blender/kaiju_unified/pixel_contract.py -- \
  --directory "$SHOT/negative_round05" --flanks-only --expect-flanks-failure
"$BLENDER" -t 6 -b "$ROOT/round_04/unified.blend" --python-exit-code 1 \
  --python blender/kaiju_unified/pixel_contract.py -- \
  --directory "$SHOT/negative_round04" --slide-only --expect-slide-failure
setsid -f /home/devin/src/2026/videdit/venv/bin/python blender/kaiju_unified/draft.py \
  --directory "$SHOT" > "$SHOT/pipeline.log" 2>&1 < /dev/null
```

## Historical round 05 (T328)

Current review candidate:
`/home/devin/src/2026/videdit/work/kaiju_flight_unified_325/round_05/`.

`review.html` presents the 540p / eight-sample contact-through-settle draft,
`impact_draft.mp4`, decoded beat stills and a three-frame motion strip. Full
1080p/64 rendering remains pending Devin's approval; this task only delivers
the revised impact excerpt.

Delivered media: 81 frames / 3.375 seconds at 960×540, 24 fps. Full decode and all
81 encoded/source comparisons pass (maximum mean absolute error 2.247); 162
native/graded frame hashes are retained in `media_qa.json`. Durable Git evidence
is `draft_328_results.json` and `draft_328_beats.jpg`. MP4 SHA-256:
`1b52d8a0caafd58710b47325ad11bcc50a52ccb61a0461f2acc607c4fb5c0b57`.

Round 05 patches the actual saved round 04. The frame-106 contact and frame-112
launch transforms are identical. All original hinged poses, rocks, terrain,
robot motion, and frame-124 debris timing remain. The camera travels at a fixed
world-space offset from the beetle during frames 106–124. Its deliberate crop is
entirely at the bottom: approximately 9–14% of projected beetle height, leaving
the head and both sides inside frame. It opens out after the strike to show the
outside slide, feet and ground.

The old take already put the feet through two sandstone meshes at frame 124.
Clearing only frame 125 would cause a 45-unit pop. With the PM's agreement,
`revise_328.py` instead routes the last twelve airborne frames 26 units toward
the cliff's outer edge, reaching contact at constant 7.013 units/frame. Launch
travel is 126.645 units; slide drop remains 24.715 units. Whole evaluated meshes
follow the solid contour, including both legs and feet. The minimum contact is
now the right foot against the original sandstone, with the torso beside the
stack's edge, rather than a penetrating shell against the stack.

`verify_328.py` independently checks triangle intersections and volume
containment against all three sandstone meshes on every frame 124–192 (7,286
evaluated beetle vertices/frame). It checks screen-space size, bottom-only crop
and camera-relative drift on every frame 106–124, constant airborne speed, and
preserved contact/launch transforms. Actual round 04 fails solidity at frame
130 and framing at frame 106. Additional in-memory controls freeze the camera
and change the launch pose. All controls run after committing the checks.

The rendered mid-slide sanity check compares frame 148 with an otherwise
identical render hiding only sandstone: round 05 retains 100% of beetle pixels;
actual round 04 retains 87.703% and fails the 95% visibility threshold. Existing
approach-speed, static environment, airborne feet, ground, debris timing,
occlusion and media checks remain active. Beauty stills and the decoded motion
strip remain the aesthetic review; collision tests do not establish performance
quality.

## Reproduce round 05

```bash
BLENDER=/home/devin/bin/blender-5.1.2-linux-x64/blender
ROOT=/home/devin/src/2026/videdit/work/kaiju_flight_unified_325
SHOT="$ROOT/round_05"
"$BLENDER" -t 6 -b --python-exit-code 1 \
  --python blender/kaiju_unified/revise_328.py -- \
  --source "$ROOT/round_04/unified.blend" --output "$SHOT"
"$BLENDER" -t 6 -b "$SHOT/unified.blend" --python-exit-code 1 \
  --python blender/kaiju_unified/verify_328.py -- --directory "$SHOT" \
  --baseline "$ROOT/round_04/unified.blend" --negative-checks
"$BLENDER" -t 6 -b "$SHOT/unified.blend" --python-exit-code 1 \
  --python blender/kaiju_unified/verify.py -- --directory "$SHOT" --negative-checks
"$BLENDER" -t 6 -b "$SHOT/unified.blend" --python-exit-code 1 \
  --python blender/kaiju_unified/pixel_contract.py -- --directory "$SHOT" --negative-checks
"$BLENDER" -t 6 -b "$ROOT/round_04/unified.blend" --python-exit-code 1 \
  --python blender/kaiju_unified/pixel_contract.py -- \
  --directory "$SHOT/negative_round04" --slide-only --expect-slide-failure
setsid -f /home/devin/src/2026/videdit/venv/bin/python blender/kaiju_unified/draft.py \
  --directory "$SHOT" > "$SHOT/pipeline.log" 2>&1 < /dev/null
```

Use a fresh output directory for any scene change. Draft rendering is resumable
only under its hash-locked plan. The pipeline grades native EXRs using pinned
Blender 4.1.1 `kaiju_1960s`, encodes CRF18, fully decodes and compares every frame.

## Historical round 04 (T325)

The notes and historical reproduction commands below describe commit
`858e65c`. Use the round-05 commands above with the current scripts.

Review candidate:
`/home/devin/src/2026/videdit/work/kaiju_flight_unified_325/round_04/`.

The complete `unified.blend` contains one 192-frame / eight-second timeline at
24 fps. All original terrain and the collision sandstone instance exist from
frame 1. `impact_draft.mp4` is a 960×540 excerpt, frames 100–180, rendered from
that scene. `review.html` presents the clip and eight decoded key stills;
`impact_beats.jpg` is the full-resolution contact sheet.

The delivered draft is 81 frames / 3.375 seconds. All 81 decoded pictures match
their graded sources (maximum mean absolute error 2.084 code values); 162 native
and graded frames are hashed. `draft_325_results.json` and `draft_325_beats.jpg`
retain the delivery evidence in Git. MP4 SHA-256:
`d659d7029bcee033663dd2177379a4116e3acd7c589ed4febbac529cea2b568d`.
Visual timing review used the decoded key beats and every-third-frame motion
strip. The review also links a fresh frame-64 beauty still demonstrating that
the collision cliff is already present during the approach.

**Impact approval is pending.** T325 explicitly requires Devin to review this
choreography before the full 1080p/64-sample render. The prior T320/T323 approvals
do not authorize the new final. There is no full-render mode in `draft.py`.

The robot follows the existing dive path, resampled by increasing arc distance
instead of slowing toward the endpoint. Every animated object's pose is sampled
at the same source time. Frame 106 exactly preserves T320's contact transforms.
One camera follows the original chase motion, then holds its contact position
and pans after the beetle; a small jolt happens only at the rock strike.

The beetle launches 126 world units in 18 frames, with both feet airborne. Its
shell reaches the original linked sandstone at frame 124. Backward movement
remains constant until the hit. The existing surface-contact solver stages the
rock against the airborne shell; mesh, UVs, material and scale remain original.
All 170 rigid fragments and 26 powder volumes start on the impact frame. The
beetle slides downward about 25 units and slumps with hanging arms and bowed head.
All creature movement uses the existing rigid hinges. The robot's glancing exit
clears the collision action; a trailing plume is briefly visible at screen right.

Rounds 01–03 are internal probes, not alternative review takes. Pixel inspection
of round 01 found robot occlusion at the smash. Round 03 cleared the action but
retained a raised guard at the endpoint; round 04 replaces that with a slump.

## Reproduce

From the repository root, using a fresh output directory for a changed take:

```bash
BLENDER=/home/devin/bin/blender-5.1.2-linux-x64/blender
SHOT=/home/devin/src/2026/videdit/work/kaiju_flight_unified_325/round_04
"$BLENDER" -t 6 -b --python-exit-code 1 \
  --python blender/kaiju_unified/build.py -- --output "$SHOT"
"$BLENDER" -t 6 -b "$SHOT/unified.blend" --python-exit-code 1 \
  --python blender/kaiju_unified/verify.py -- --directory "$SHOT" --negative-checks
"$BLENDER" -t 6 -b "$SHOT/unified.blend" --python-exit-code 1 \
  --python blender/kaiju_unified/pixel_contract.py -- --directory "$SHOT" --negative-checks
setsid -f /home/devin/src/2026/videdit/venv/bin/python blender/kaiju_unified/draft.py \
  --directory "$SHOT" > "$SHOT/pipeline.log" 2>&1 < /dev/null
```

Run rendering detached from the command harness, as above. Native per-frame EXRs
can resume under the identical render plan. Remove an incomplete frame before
resuming an interrupted write. RTX 3060 renders frames 100–164; GTX 1050 Ti renders
165–180. The draft uses eight Cycles samples, the pinned Blender 4.1.1
`kaiju_1960s` native-linear grade, and CRF18 H.264. No assembly of separate worlds,
inverse color transform, salvage trim or audio is involved.

## Verification

`scene_qa.json` checks increasing final-approach displacement, airborne feet,
ground clearance, launch distance, downward slide, static environment, camera
station and shell/rock contact timing. It includes post-commit negative controls
for braking, a grounded tap, late debris and camera drift, plus the actual
unfixed T320 dive failing the speed assertion. Copied action/slot references are
restored in memory; verification never saves changes to a scene.

`pixel_qa.json` uses rendered category masks with actual occlusion. It checks the
cliff is visible during the dive, the beetle/face remain readable, fragments are
absent before impact and visible on impact, and the robot clears the center of
the smash. A newly rendered missing-fragment control must fail the same onset
assertion. These masks supplement beauty-frame review; they do not prove that
the performance feels violent enough or that dust looks convincing.
The actual obstructed round-01 scene also fails the current rendered robot
occlusion assertion; its masks remain in that round's `pixel_masks/` directory.

`media_qa.json` checks exact duration/frame count/resolution, fully decodes the
MP4, compares every decoded picture against its graded source PNG, and hashes
the movie and every native/graded frame. The source scene is also hash-locked.
Comparing the encoded impact picture with the wrong approach picture fails the
same pixel assertion (19.705 mean absolute error), as intended.
Full final rendering and final media QA remain behind the impact approval gate.
