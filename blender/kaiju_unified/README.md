# T328 — solid-rock slide and close fly-with camera

Current review candidate:
`/home/devin/src/2026/videdit/work/kaiju_flight_unified_325/round_05/`.

`review.html` presents the 540p / eight-sample contact-through-settle draft,
`impact_draft.mp4`, decoded beat stills and a three-frame motion strip. Full
1080p/64 rendering remains pending Devin's approval; this task only delivers
the revised impact excerpt.

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
