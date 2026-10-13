# T317 — flying robot shoulder-camera preview

Review deliverables are in
`/home/devin/src/2026/videdit/work/kaiju_dive_317/round_03/`:

- `review.html` and `pose_keybeats.jpg`: A forward arms / B swept arms at
  frames 1, 64, and 96. Each source PNG is 960×540, 16 Cycles samples.
- `forward/dive_forward.blend`, `swept/dive_swept.blend`: complete 96-frame,
  24 fps draft choreography. Both open at the endpoint.
- Each pose has `preview_exr/`, graded `stills/`, source hashes in
  `manifest.json`, and `verification.json` with all 96 measured frames.

Round 03 is the still review stage. T319 advances both candidates to draft
motion in round 04 at Devin's request, without selecting a pose or changing
either scene. Final rendering requires his approval. Rounds 01–02 are
superseded internal framing probes.

The camera is parented to the robot near its back, with a fixed local position
and orientation. The opening sees upper sky; the robot pitches into a descending
flight path, ending before collision with the grounded beetle. The beetle raises
and twists its torso, turns its neck, shifts its pelvis, bends its legs and
raises its guard. The original solid pieces articulate at their existing joints;
there is no organic deformation. Hip translations compensate the pose changes
to keep both feet planted. Booster thrust remains on and flutters throughout.

The approved T313 master supplies the set, beetle, native ten-material robot
and lighting. T305's cinematic scene supplies the deployed boosters, hatches,
support rods, exhaust geometry and robot rig. The master robot's dorsal bay is
opened under the reused hatches; its native face material assignments remain.
The camera samples the upper part of the existing HDRI to avoid a ground-level
treeline in the high-sky opening; environment illumination remains unchanged.
A broad cool stage bounce travels with the robot to keep its back legible.

This close shoulder offset favors the near exhaust; the far plume is mostly
obscured by the foreground robot. This was explicitly called out to PM at the
pick handoff. The beetle's face, horn and raised guard are visible in the
endpoint, with some lower-body overlap by the robot. The middle beat shows its
full silhouette. Composition remains subject to Devin's review.

Native linear EXRs use the existing pinned `kaiju_1960s` compositor in Blender
4.1.1, then AgX at exposure −0.8. No inverse-AgX reconstruction or salvage trim.
Scene authoring and native rendering use Blender 5.1.2, matching the inherited
layered-action files and the T314 pipeline. Only the GTX 1050 Ti was used for
preview rendering; the RTX 3060 remained available to T316.

## Reproduction

Run from this repository root, using a fresh output directory for a new round:

```bash
SHOT=/home/devin/src/2026/videdit/work/kaiju_dive_317/round_03
BLENDER=/home/devin/bin/blender-5.1.2-linux-x64/blender
GRADE=/home/devin/bin/blender-4.1.1-linux-x64/blender
for POSE in forward swept; do
  "$BLENDER" -t 6 -b --python-exit-code 1 --python blender/kaiju_dive/build.py -- \
    --output "$SHOT/$POSE" --pose "$POSE"
  "$BLENDER" -t 6 -b "$SHOT/$POSE/dive_$POSE.blend" --python-exit-code 1 \
    --python blender/kaiju_dive/verify.py -- \
    --output "$SHOT/$POSE/verification.json" --negative-checks
  "$BLENDER" -t 6 -b "$SHOT/$POSE/dive_$POSE.blend" --python-exit-code 1 \
    --python blender/kaiju_arrival/render.py -- --output "$SHOT/$POSE/preview_exr" \
    --frames 1,64,96 --samples 16 --percent 50 --device 1050
  "$GRADE" -t 6 -b --python-exit-code 1 --python blender/kaiju_arrival/grade.py -- \
    --input "$SHOT/$POSE/preview_exr" --output "$SHOT/$POSE/stills"
done
/home/devin/src/2026/videdit/venv/bin/python blender/kaiju_dive/review.py --directory "$SHOT"
```

Verification checks flight descent, attached camera, continuous thrust, opposing
arm directions, foot contact and horizontal drift, visible endpoint bounds,
and nontrivial neck/waist articulation. After committing the implementation,
negative controls detached the camera and removed beetle waist/neck animation:
both failed on their intended assertions. Exact action and slot references were
restored in memory; the scenes were not overwritten by verification. Pixel
inspection remains necessary for occlusion and performance quality.

## T318 rear geometry audit

Both flagged silhouettes are **intentional and correctly posed**. Review the
fresh native renders and labeled close-ups at:

`/home/devin/src/2026/videdit/work/kaiju_dive_318/review.html`

The same directory contains `annotated_geometry.jpg`, both poses' fresh graded
`stills/frame_0064.png` and native `preview_exr/frame_0064.exr`, plus
`geometry_audit.json` with source SHA-256 hashes and measurements.

| Screen feature | Exact object | Finding |
| --- | --- | --- |
| Broad flat panel on screen-left | `Hatch R \| original armor` | Open dorsal bay armor door, attached to `Hatch R \| rear hinge`, deployed at −112° about local Z. |
| Thin stick on screen-right | `Hatch L \| original armor` | Opposite armor door viewed almost edge-on, attached to `Hatch L \| rear hinge`, deployed at +112° about local Z. Its edge bolts belong to the same hinge. |

L/R above are the **source object labels**, not screen directions. These doors
were authored for T305's booster deployment. They are present in the deployed
T305/T306 cinematic source at frame 217. The earlier native master instead has
a closed dorsal torso face: the dive removes that one quad before reusing the
hatch assembly. T305's older torso representation used two triangles there.

The audit opened both saved round-03 scenes and compared **all 58** booster and
hatch objects with T305: mesh coordinates/topology and parent names match
exactly. Rig-relative transforms match through **all 96 frames in both poses**;
the largest matrix-component difference is 0.000153 from floating-point world
transforms. Exhaust length flutter is intentional and excluded from the rigid
scale comparison; its local position, rotation and parent are checked.

All **1,822 native robot vertices and skin weights** match the approved T313
master. None lacks a positive weight on an existing bone. The native mesh uses
the imported robot rig, and no additional attached mesh exists outside that
mesh and the identified hardware. The remaining visible mesh inventory is
recorded in the JSON (beetle, ground, fog, rock/scatter set dressing).

Pixel verification inspected the six saved key beats and both fresh frame-64
renders. Camera-ray hits identify the broad door (3,387 pixels) and edge-on door
(565 pixels) inside the audit region in each pose. Their boundary overlays in
the labeled sheet align with the two flagged silhouettes. The adjacent short
horizontal projections are the inherited booster bridge/ram assembly; no other
loose or unposed rear geometry was found. No scene changes were necessary, so
the original round-03 blends remain the review scenes.

Fresh rendering used only CUDA GTX 1050 Ti, 960×540, 16 samples, followed by the
same pinned Blender 4.1.1 film grade. The 3060 was not selected. The existing
96-frame choreography verifier also passed for each saved scene. After the
audit implementation was committed, its in-memory negative control rotated
`Hatch R | rear hinge` by 0.1 radians: the deployed-transform assertion failed
in both poses. Restoring the exact copied Euler transform passed again; no
source file was saved by the audit.

Reproduce the comparison and labeled sheet from this repository root:

```bash
/home/devin/bin/blender-5.1.2-linux-x64/blender -t 6 -b --python-exit-code 1 \
  --python blender/kaiju_dive/audit_geometry.py -- \
  --output /home/devin/src/2026/videdit/work/kaiju_dive_318 --negative-checks
/home/devin/src/2026/videdit/venv/bin/python blender/kaiju_dive/review_geometry.py \
  --directory /home/devin/src/2026/videdit/work/kaiju_dive_318
```

For fresh stills, use the render/grade commands above with the round-03 saved
blends as inputs, the T318 directory as output, and `--frames 64`. Do not rebuild
or overwrite the source scenes merely to run this audit.

## T319 round 04 — both poses in motion

Output directory:
`/home/devin/src/2026/videdit/work/kaiju_dive_317/round_04/`

- `dive_forward_draft.mp4`: A, arms extended forward.
- `dive_swept_draft.mp4`: B, arms swept at the sides.
- `review.html`: both clips with playback controls and the pending choices.
- `render_plan.json`: exact input paths/hashes, resolution, samples and device.
- `media_verification.json`: clip hashes, full decode results, ffprobe frame
  counts/timing, grading provenance and all graded-frame hashes.
- Each pose directory retains native EXRs, graded PNGs, render/grade logs and
  full 96-frame choreography verification.

Both clips cover frames 1–96 at 24 fps (four seconds), 960×540, 16 Cycles samples,
H.264 CRF 18, yuv420p. They use the unchanged round-03 blends and the same
Blender 4.1.1 `kaiju_1960s` grade as the stills. Rendering selects only the GTX
1050 Ti. The deployed hatches, chase framing, endpoint and dominant near plume
are preserved. Review choices remain arm pose A/B, open/closed hatches in
flight, endpoint framing and one/both plumes; these are drafts, not finals.

Run the resumable orchestrator in a managed terminal session (or a persistent
detached process), from this repository root:

```bash
/home/devin/src/2026/videdit/venv/bin/python blender/kaiju_dive/draft_motion.py \
  --source /home/devin/src/2026/videdit/work/kaiju_dive_317/round_03 \
  --output /home/devin/src/2026/videdit/work/kaiju_dive_317/round_04
```

The script verifies each saved scene, renders missing native frames, grades all
frames, checks PNG sizes, encodes each clip and fully decodes it with FFmpeg's
error-exit flag. It requires exactly 96 decoded frames at 24 fps, four seconds
and 960×540. Input scene hashes must remain unchanged. Resuming requires the
same render plan; if a render was interrupted while writing a frame, remove
that incomplete output before resuming. Large media stays in the work directory,
outside Git; the script and verification summary are versioned here.

Motion review exposes an existing straight terrain boundary entering against
the sky around frame 24. It was not visible in the earlier 1/64/96 still gate.
The unchanged scenes retain it for this comparison; it is a review concern
before final rendering. Decoded beat sheets include frames 1, 24, 48, 64, 80
and 96 so this transition can be inspected alongside the approach and brace.

QA also exercised a temporary 95-frame encode using an in-memory copy of the
committed packaging implementation. The actual decoded count was 95 and the
96-frame assertion rejected it; the source script and delivered clip were
untouched. Both existing scene negative controls (detached camera and frozen
beetle reaction) also failed on their intended assertions and then restored
their exact in-memory state, without saving the source scenes.
