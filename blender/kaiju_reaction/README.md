# T322 — beetle reaction preview

Review artifacts: `/home/devin/src/2026/videdit/work/kaiju_reaction_322/round_03/`.
`review.html` contains four graded staging stills and, after the draft pipeline
finishes, `reaction_draft.mp4`. This is an 84-frame, 24 fps draft. Final rendering
requires Devin's approval of the staging and timing. No assembly is performed.

The first frame preserves every creature/hatch/booster world transform from
the approved T320 frame 106. The master scene, terrain-relief disk, native
characters, deployed hardware, world illumination and pinned grade are reused.
The new 32 mm camera is 4.5 units above the miniature floor. The robot is large
and partly cropped at the opening contact, then rebounds upward out of frame.

The beetle whips its torso, throws its arms outward and takes two backward steps.
Two-link leg solutions keep the hip sockets fixed and the supporting foot on
the ground; the pelvis drops between steps to keep the ankles within reach.
All armor remains rigid. The right rear shell loads a new nearby sandstone
stack over frames 36–41, with the peak impact and burst at frame 39. The stack
wobbles, 170 stone fragments launch and bounce with
damped gravity, and 26 irregular powder volumes fall and flatten. The beetle
recoils forward slightly and stays upright. Dust is procedural, not a fluid sim.

The staging stills are frames 1, 22, 43 and 84 at 960×540 / 16 Cycles samples.
The motion draft uses the same scene at 960×540 / 8 samples. Native EXRs render
in Blender 5.1.2, then the existing `kaiju_arrival/grade.py` uses Blender 4.1.1
and the hash-pinned `kaiju_1960s` compositor at exposure −0.8. Originals are
never overwritten. Rounds 01–02 are internal iteration/negative-control inputs.

## Reproduction

Use a fresh output directory for a new scene candidate. From the repository root:

```bash
SHOT=/home/devin/src/2026/videdit/work/kaiju_reaction_322/round_03
BLENDER=/home/devin/bin/blender-5.1.2-linux-x64/blender
GRADE=/home/devin/bin/blender-4.1.1-linux-x64/blender
PYTHON=/home/devin/src/2026/videdit/venv/bin/python

"$BLENDER" -t 6 -b --python-exit-code 1 --python blender/kaiju_reaction/build.py -- --output "$SHOT"
"$BLENDER" -t 4 -b "$SHOT/reaction.blend" --python-exit-code 1 \
  --python blender/kaiju_reaction/verify.py -- --directory "$SHOT" --negative-checks
"$BLENDER" -t 6 -b "$SHOT/reaction.blend" --python-exit-code 1 \
  --python blender/kaiju_arrival/render.py -- --output "$SHOT/still_exr" \
  --frames 1,22,43,84 --samples 16 --percent 50 --device 3060
"$GRADE" -t 6 -b --python-exit-code 1 --python blender/kaiju_arrival/grade.py -- \
  --input "$SHOT/still_exr" --output "$SHOT/stills"
"$BLENDER" -t 4 -b "$SHOT/reaction.blend" --python-exit-code 1 \
  --python blender/kaiju_reaction/pixel_contract.py -- --directory "$SHOT"
"$PYTHON" blender/kaiju_reaction/package.py --directory "$SHOT"
"$PYTHON" blender/kaiju_reaction/draft.py --directory "$SHOT"
```

Run the draft pipeline detached, as with T319/T320. Its saved render plan checks
the scene hash before resuming. Both GPUs render disjoint ranges. Remove an
incomplete native frame after interruption before resuming. The pipeline grades,
encodes H.264, checks resolution/count/rate, and fully decodes the resulting clip.
Every decoded frame is also compared with its graded PNG, and ten decoded beats
are retained for visual review.

## Verification boundaries

The saved-scene verifier checks contact continuity, foot clearance, two lifts,
fixed hip sockets, torso articulation, backward travel, robot exit and a mesh
surface intersection between shell and rock at the impact beat. Cycles category
masks check visible pixels for beetle, face, stack, robot and stone fragments,
including surface occlusion. Masks hide volumes: the actual graded beauty
stills and decoded motion must also be reviewed for dust and aesthetic quality.

Negative controls run after the implementation commits. Freezing the root action
fails `No backward stagger`. The actual round-02 sliding-hip scene fails
`Hip socket translates at 2`. The actual round-01 rendered masks fail
`Debris visible before rock impact`. Neither original scene is modified by QA.
