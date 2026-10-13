# T322 — revised beetle reaction staging gate

Current review: `/home/devin/src/2026/videdit/work/kaiju_reaction_322/round_05/review.html`.
The `low/` and `continuation/` directories each contain nine graded stills,
`early_frames.jpg`, `staging_beats.jpg`, `reaction.blend`, native EXRs and QA.
Early frames 1/4/8/12/16/20 show contact through the glancing pass and powered
pull-up. Standard beats 1/22/43/84 show contact, stagger, rock burst and settle.
The sheets retain each still's full 960×540 resolution, with individual links.

**T323: Devin approved BOTH round-05 cameras for motion and final rendering.**
The PM subsequently relayed approval to proceed through draft self-QA into both
finals overnight, waiving the human timing gate. Approved scenes remain unchanged.

Both T323 finals are complete and verified. Review both at
`/home/devin/src/2026/videdit/work/kaiju_reaction_322/review_final_323.html`.
Final MP4s are `final_low/reaction_final.mp4` and
`final_continuation/reaction_final.mp4` under that same work directory. Both are
84 frames / 3.5 seconds, 1920×1080 at 24 fps, 64 Cycles samples, native EXR
through the pinned grade and CRF16 H.264. The 540p timing drafts remain in each
round-05 camera directory. No assembly or audio was added.

`final_323_results.json` records both MP4 hashes, render plans, grade provenance,
scene and rendered-pixel checks, mutation-test evidence, and external artifact
paths. All 168 final decoded frames passed pixel comparison (maximum MAE
1.6323 low / 1.6484 continuation). Every native and graded frame hash was
rechecked at delivery. `final_323_contact_{low,continuation}.jpg` are contact
sheets taken from the delivered MP4s. Draft timing review used every third
graded frame plus the endpoint; final visual review used decoded beat sheets
and full-size impact frames. The higher camera makes the debris subtler;
the approved framing and performance are preserved.
Devin rejected the earlier invented rock stack and elastic upward rebound.
The round-03 draft process was terminated on that feedback; its partial native
frames are superseded and are not a review clip. No assembly is performed.
Rounds 01–04 are iteration/evidence inputs.

Both alternatives have the same 84-frame, 24 fps creature performance:

- A: ground-level 32 mm camera, 4.5 units above the miniature floor.
- B: exact T320 frame-106 camera position/orientation and 26 mm lens at frame 1;
  it then holds that station and pans after the retreating beetle. This is the
  higher dive/impact viewpoint.

The first frame preserves every creature/hatch/booster world transform from
the approved T320 frame 106. The master terrain-relief disk, native characters,
deployed hardware, world illumination and pinned grade are reused. The robot
continues forward while decelerating into the beetle's initial displacement,
glances laterally past its shoulder, then pitches into a climb. Exhaust length
increases by 50% during the powered pull-up; there is no immediate upward bounce.

The beetle whips its torso, flails its arms and takes two backward steps. Fixed
hip sockets and two-link leg solutions keep at least one supporting foot on
the floor. The pelvis drops between steps to keep the ankles within reach;
all armor stays rigid. At frame 39, its rear shell contacts an instance of
`model.011_Default OBJ.016_0.001` from the master. The collision asset shares
the original mesh, UVs and packed PBR materials, and retains world scale 9.
Only placement/heading change. Whole-shell surface intersection refines the
placement to a shallow impact rather than burying the suit in an uneven ledge.

170 fragments sample their birth positions on the actual original rock surface,
reuse its material, and bounce with damped gravity. 26 irregular powder volumes
fall and flatten along that surface. The beetle recoils slightly forward and
stays upright. Dust is procedural, not a fluid simulation.

Stills use 16 Cycles samples. Native EXRs render in Blender 5.1.2, then the
existing `kaiju_arrival/grade.py` applies the hash-pinned `kaiju_1960s` compositor
in Blender 4.1.1 at exposure −0.8. Original source files are never overwritten.

## Reproduction

Use a fresh output directory for a new candidate. From the repository root:

```bash
ROOT=/home/devin/src/2026/videdit/work/kaiju_reaction_322/round_05
BLENDER=/home/devin/bin/blender-5.1.2-linux-x64/blender
GRADE=/home/devin/bin/blender-4.1.1-linux-x64/blender
PYTHON=/home/devin/src/2026/videdit/venv/bin/python
for CAMERA in low continuation; do
  SHOT="$ROOT/$CAMERA"
  "$BLENDER" -t 4 -b --python-exit-code 1 --python blender/kaiju_reaction/build.py -- \
    --output "$SHOT" --camera "$CAMERA"
  "$BLENDER" -t 4 -b "$SHOT/reaction.blend" --python-exit-code 1 \
    --python blender/kaiju_reaction/verify.py -- --directory "$SHOT" --negative-checks
  "$BLENDER" -t 4 -b "$SHOT/reaction.blend" --python-exit-code 1 \
    --python blender/kaiju_arrival/render.py -- --output "$SHOT/still_exr" \
    --frames 1,4,8,12,16,20,22,43,84 --samples 16 --percent 50 --device 3060
  "$GRADE" -t 4 -b --python-exit-code 1 --python blender/kaiju_arrival/grade.py -- \
    --input "$SHOT/still_exr" --output "$SHOT/stills"
  "$BLENDER" -t 4 -b "$SHOT/reaction.blend" --python-exit-code 1 \
    --python blender/kaiju_reaction/pixel_contract.py -- --directory "$SHOT"
done
"$PYTHON" blender/kaiju_reaction/review_cameras.py --directory "$ROOT"
```

After approval and camera selection, `draft.py --directory SELECTED_DIRECTORY
--approval-note 'actual approval record'` can render an 8-sample 540p timing
draft on both GPUs. Run it detached. Its saved plan checks the scene hash before
resuming; remove an incomplete native frame after interruption. It grades,
encodes, fully decodes and compares every decoded frame with its graded PNG.
It does not render a final.

For each approved camera, after its draft passes media and visual timing QA:

```bash
"$PYTHON" blender/kaiju_reaction/final.py --source "$ROOT/low" \
  --directory /home/devin/src/2026/videdit/work/kaiju_reaction_322/final_low \
  --approval-note 'T323: PM relayed Devin approval for both finals; human timing gate waived'
```

Repeat with `continuation` and `final_continuation`. Run detached, serializing
cameras because each take uses both GPUs. The final runner renders native
1920×1080 EXRs at 64 samples, applies the same pinned Blender 4.1.1 grade,
encodes CRF16 H.264, and streams all 84 decoded frames through T320's pixel and
hash checks. It also reruns saved-scene negative controls and rendered category
masks. `final_render_plan.json` pins the approved source hash; existing plans
must match exactly to resume. Remove an interrupted incomplete EXR before
resuming. Outputs include `reaction_final.mp4`, `final_verification.json`,
native/graded frames, decoded beats, and `final_decoded_contact.jpg`.

## Verification boundaries

The saved-scene verifier checks contact continuity, fixed hip sockets, foot
clearance and lifts, torso motion, backward travel, robot exit, forward momentum,
the delayed climb, increased thrust, the original sandstone instance/scale,
the B camera's exact initial pose/lens, and shell/rock surface contact.
Cycles category masks check visible pixels for beetle, eye/horn silhouette,
stack, robot and fragments, including surface occlusion. Masks hide volumes;
the graded beauty stills are also inspected for dust and aesthetic quality.

Negative controls ran after their implementation commits: frozen stagger,
rescaled rock, old backward rebound, premature upward lift, unpowered climb and
wrong B camera pose each fail the intended assertion, then restore exact action
and transform copies. The actual rejected round-03 scene fails the original-rock
contract. Earlier controls rejected the real round-02 sliding hips and round-01
premature visible debris. Source scenes are not saved by verification.
