# T317 — flying robot shoulder-camera preview

Review deliverables are in
`/home/devin/src/2026/videdit/work/kaiju_dive_317/round_03/`:

- `review.html` and `pose_keybeats.jpg`: A forward arms / B swept arms at
  frames 1, 64, and 96. Each source PNG is 960×540, 16 Cycles samples.
- `forward/dive_forward.blend`, `swept/dive_swept.blend`: complete 96-frame,
  24 fps draft choreography. Both open at the endpoint.
- Each pose has `preview_exr/`, graded `stills/`, source hashes in
  `manifest.json`, and `verification.json` with all 96 measured frames.

**Still review stage only.** Devin's pose and endpoint directions precede the
draft clip. Final rendering requires his approval. No movie or final-quality
sequence has been rendered. Rounds 01–02 are superseded internal framing probes.

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
