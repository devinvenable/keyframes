# T325 — unified flight and impact, choreography gate

Review candidate:
`/home/devin/src/2026/videdit/work/kaiju_flight_unified_325/round_04/`.

The complete `unified.blend` contains one 192-frame / eight-second timeline at
24 fps. All original terrain and the collision sandstone instance exist from
frame 1. `impact_draft.mp4` is a 960×540 excerpt, frames 100–180, rendered from
that scene. `review.html` presents the clip and eight decoded key stills;
`impact_beats.jpg` is the full-resolution contact sheet.

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

`media_qa.json` checks exact duration/frame count/resolution, fully decodes the
MP4, compares every decoded picture against its graded source PNG, and hashes
the movie and every native/graded frame. The source scene is also hash-locked.
Full final rendering and final media QA remain behind the impact approval gate.
