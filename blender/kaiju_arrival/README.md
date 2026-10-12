# Beetle-knight arrival — T311

A 108-frame / 24 fps / 4.5-second shot delivered at 1920×1080. The arrival opens
on an empty valley; the beetle leaps in from screen left, plants both feet at
frame 52, compresses into the landing, and settles into a guarded pose. The
tripod camera pans toward the beetle and zooms from 32 to 72 mm over frames
46–63. A brief impact recoil accompanies the powder and falling dirt.

Both creatures remain in the master sandstone scene, facing each other 650
units apart. The robot stays behind the arrival camera throughout all 108
frames. **SceneCamera** retains the approved beetle animation. Switch to
**Robot reverse | same tripod** for a starting robot composition at 50 mm;
named **Shot target** empties retain both subject marks. This reverse camera
is saved for future work, not a rendered robot-shot deliverable.

## Delivered files

`/home/devin/src/2026/videdit/work/kaiju_arrival_311_beetle_only/`

- `beetle_arrival_final.mp4`: 1080p24 H.264, CRF 16, silent.
- `beetle_arrival_final.blend`: master scene with final powder and saved cameras.
- `final_frames/`: all 108 graded lossless PNG frames.
- `final_exr/`: native scene-linear half-float source frames.
- `key_beats.jpg`: labeled six-beat contact sheet.
- `final_stills/frame_0001.png`: empty valley establishing.
- `final_stills/frame_0040.png`: airborne.
- `final_stills/frame_0052.png`: initial contact and powder onset.
- `final_stills/frame_0058.png`: powder burst during the fast zoom.
- `final_stills/frame_0063.png`: zoom end.
- `final_stills/frame_0086.png`: settled guard.
- `final_verification.json`, `final_media_verification.json`: scene and media QA.

Draft work was superseded by Devin's instruction to proceed directly to the
final render. Partial `preview_exr` and older draft stills are iteration
artifacts, not the delivered sequence. The earlier sibling `kaiju_arrival_311/`
contains superseded staging with a visible robot.

## Final dust

The final pass changes the effect itself: 44 individually displaced volumetric
lobes launch in uneven clusters from the actual foot-contact positions, with
coarse and fine density breakup. Their vertical paths are ballistic; density
falls rapidly after the impact and the volumes flatten against the ground.
360 angular particulate clumps add visible falling mass. This is deterministic
procedural volume animation, not a cached fluid simulation. The final volume
boundaries have four times the draft mesh resolution, smaller density features,
and four times finer ray-marching steps (0.5 versus 2.0; 512 max steps).

The practical reference is powder combined with separate solid debris, as
described by [Roger George Special Effects](https://rogergeorge.com/products/fullers-earth).
Uneven jets, clump sizes, low launch heights, and fast settling are the artistic
translation for this miniature-set shot; they are not a measured fluid model.
Final rendering uses 64 Cycles samples, adaptive threshold 0.04, and denoising.
There is no emissive blast, rising smoke column, or organic beetle deformation.

## Reproduce

Run from this repository root. Never write into the T307 source directory.

```bash
SHOT=/home/devin/src/2026/videdit/work/kaiju_arrival_311_beetle_only
BLENDER=/home/devin/bin/blender-5.1.2-linux-x64/blender
GRADE_BLENDER=/home/devin/bin/blender-4.1.1-linux-x64/blender

"$BLENDER" -b --python-exit-code 1 --python blender/kaiju_arrival/build.py -- \
  --source /home/devin/src/2026/videdit/work/kaiju_beetle_307/beetle_faceoff.blend \
  --output "$SHOT" --quality final

"$BLENDER" -b "$SHOT/beetle_arrival_final.blend" --python-exit-code 1 \
  --python blender/kaiju_arrival/render.py -- --output "$SHOT/final_exr" \
  --frames all --samples 64 --percent 100 --device 3060

"$GRADE_BLENDER" -b --python-exit-code 1 --python blender/kaiju_arrival/grade.py -- \
  --input "$SHOT/final_exr" --output "$SHOT/final_frames"

"$BLENDER" -b "$SHOT/beetle_arrival_final.blend" --python-exit-code 1 \
  --python blender/kaiju_arrival/verify.py -- --output "$SHOT/final_verification.json" \
  --negative-checks
/home/devin/src/2026/videdit/venv/bin/python blender/kaiju_arrival/package.py \
  --directory "$SHOT" --final
```

The renderer selects CUDA devices by name substring. Independent workers can
render disjoint comma-separated `--frames` lists into the same EXR directory.
To stop a superseded batch, terminate its process: an interrupt can cancel one
Blender render while leaving the Python frame loop running. Python packaging
requires Pillow, ffmpeg and ffprobe; the existing videdit venv provides Pillow.

No paid or newly downloaded landscape assets are used. T307 sandstone, ground,
overcast HDRI, robot and beetle are reused; new background pieces share the
existing sandstone mesh. Ground grit and all impact effects are authored by
the builder. The unrelated legacy village is removed from the derivative only.

## Film and verification

Native linear EXRs go through the SHA-pinned recovered `kaiju_1960s` compositor
in Blender 4.1.1, then AgX at exposure −0.8. This preserves T309's grain,
vignette, bloom and chromatic aberration. The inverse-AgX and −3-code-value
reconstruction trim belonged to the older 8-bit salvage path and are omitted.

The scene verifier measures clearance, contact, lens endpoints, framing,
opponent separation, robot exclusion, rigid construction, dust birth and
settling. Nine negative mutations reject missing leap height, floating contact,
a missing zoom, early/late/missing powder, the old visible robot placement,
buoyant powder that never falls, and dust that fails to dilute. Exact in-memory
copies are restored; mutated files are never saved. The unanimated T307 source
also fails the new shot-duration assertion.

Media QA counts decoded frames, checks resolution/rate/duration, fully decodes
the MP4, and re-hashes every original T307 artifact. Rendered-frame inspection
checks the dust silhouette and readable foot contact as well as the geometric
contracts. The source files remain untouched.

## T312: lower camera and natural foliage — preview choice gate

Outputs: `/home/devin/src/2026/videdit/work/kaiju_arrival_312_take2/`.
**Preview only. Devin must pick A, B, or C before final-quality rendering.**

`take2.py` opens the approved T311 final master and changes only the active
camera transform and world environment. It compares all noncamera object
transforms and animation curves across all 108 frames, including powder material
animation. The 32–72 mm lens curve is preserved exactly, including the original
last zoom key at frame 63. The new camera tracks the original target and impact
recoil, with a constant 3-unit target lift for B to retain horn clearance.
C opens with its target shifted 35 units right, easing back to the approved
target by frame 44. This keeps the waiting beetle fully outside C's wider opening
and finishes before the fast zoom. Actor and lens animation remain unchanged.

| Take | Camera position | Intent |
| --- | --- | --- |
| A — Low classic | (130, −340, 9) | Original horizontal station, lowered from 26 |
| B — Ground hero | (95, −325, 4) | Closer, almost ground level, steeper upward view |
| C — Low oblique | (180, −385, 7) | More oblique, farther back, more surrounding landscape |

The environment is [Old Quarry Gerlingen](https://polyhaven.com/a/old_quarry_gerlingen)
by Andreas Mischok, CC0, 4K HDR. Both lighting and camera rays see the natural
panorama; the old upper-sky-only branch is removed in these derivatives. World
strength is 0.3, azimuth 250 degrees. A vertical vector scale of 2 reduces the
photographed trees' angular height so foliage reads as distant behind the
miniature sandstone set. Geometry, lights, grade, dust, and actor animation are
unchanged. The downloaded HDRI's upstream MD5 and local SHA-256 are recorded or
checked; the HDRI remains outside Git.

Review `camera_choices.jpg` (rows A/B/C, columns frames 1/52/86), individual
`A/stills/frame_*.png` etc., and `take_A_timing.jpg` etc. for the extra beats.
These are 960×540, 16-sample previews through the exact pinned 4.1.1 compositor.
Native EXRs and saved scenes are retained per take. Iteration probes under A
are superseded; only `stills/` and the labeled sheets are review deliverables.

```bash
SHOT=/home/devin/src/2026/videdit/work/kaiju_arrival_312_take2
SOURCE=/home/devin/src/2026/videdit/work/kaiju_arrival_311_beetle_only/beetle_arrival_final.blend
BLENDER=/home/devin/bin/blender-5.1.2-linux-x64/blender
GRADE_BLENDER=/home/devin/bin/blender-4.1.1-linux-x64/blender

mkdir -p "$SHOT/assets"
curl -fL https://dl.polyhaven.org/file/ph-assets/HDRIs/hdr/4k/old_quarry_gerlingen_4k.hdr \
  -o "$SHOT/assets/old_quarry_gerlingen_4k.hdr"

for take in A B C; do
  "$BLENDER" -b --python-exit-code 1 --python blender/kaiju_arrival/take2.py -- \
    --source "$SOURCE" --hdri "$SHOT/assets/old_quarry_gerlingen_4k.hdr" \
    --output "$SHOT/$take" --take "$take"
  "$BLENDER" -b --python-exit-code 1 --python blender/kaiju_arrival/verify_take2.py -- \
    --source "$SOURCE" --take "$SHOT/$take/take_$take.blend" \
    --output "$SHOT/$take/locked_verification.json" --negative-checks
  "$BLENDER" -b "$SHOT/$take/take_$take.blend" --python-exit-code 1 \
    --python blender/kaiju_arrival/verify.py -- \
    --output "$SHOT/$take/verification.json" --negative-checks
  "$BLENDER" -b "$SHOT/$take/take_$take.blend" --python-exit-code 1 \
    --python blender/kaiju_arrival/render.py -- --output "$SHOT/$take/preview_exr" \
    --frames 1,40,51,52,58,63,86 --samples 16 --percent 50 --device 3060
  "$GRADE_BLENDER" -b --python-exit-code 1 --python blender/kaiju_arrival/grade.py -- \
    --input "$SHOT/$take/preview_exr" --output "$SHOT/$take/stills"
done
/home/devin/src/2026/videdit/venv/bin/python blender/kaiju_arrival/take2_review.py \
  --directory "$SHOT"
```

The saved-take verifier rejects the original T311 camera and sky-only world,
and rejects actor-scale and lens-curve mutations, restoring exact in-memory
copies after each mutation. It also rejects the unfixed wide C opening that
revealed a beetle sliver at the left edge. Existing T311 checks cover contact, dust birth and
settling, framing, and robot exclusion. Pixel inspection is still mandatory.
After a pick, use the existing final linear-EXR rendering, pinned grade, encoding,
full decode, and source-hash QA pipeline; do not interpret preview completion as
approval to start that stage.

## T313: revised left-third endpoint — composition review gate

Outputs: `/home/devin/src/2026/videdit/work/kaiju_arrival_313_take3/`.
**The current deliverable is just the revised frame-86 still. Camera motion
and final-sequence rendering await further direction.**

After reviewing initial B, Devin directed the endpoint to put the monster on
the left-third line, push closer, and tilt farther upward. He asked to see just
that end pose and work backwards to the camera move. Both 47-frame clip workers
were therefore stopped. Partial `clip_exr/` sequences remain work in progress,
not delivered clips. All twelve initial 960×540 / 16-sample graded stills remain
in `A/stills/` and `B/stills/`; `pixel_review.jpg` compares them.

The current image is `B_hold_left_third/stills/frame_0086.png`, rendered at
1920×1080 / 64 Cycles samples. `review.html` embeds it and the prior B hold for
comparison. The saved scene is `B_hold_left_third/hold_B_left_third.blend`.
Its camera is at (−18.6, 4.6, 0.7), 75.2 units from the landing mark: 12% closer
than B. Upward tilt is 31.5° instead of 29°. The projected silhouette is centered
at x=1/3, with 6.33% headroom and 2.32% below the feet. The original 72mm hold
lens and 170mm sensor are unchanged. All images use the existing SHA-pinned
Blender 4.1.1 film compositor and AgX, without the old salvage trim.

Initial variants retained for reference:

| Take | Tripod position | Landing distance | Tilt, frames 44–63 | Sensor | 36mm-sensor equivalent |
| --- | --- | --- | --- | --- | --- |
| A — Ground approach | (5, −35, 1) | 120.8 | 4° → 24° | 130 mm | 8.9–19.9 mm |
| B — At the feet | (−15, −5, 0.7) | 85.4 | 13° → 29° | 170 mm | 6.8–15.2 mm |

B was recommended and selected as the basis for the revised endpoint. The
initial A/B camera stations remain fixed; their horizontal pan ends at contact,
while the upward tilt continues through frame 63. The endpoint derivative has
a constant camera orientation and does not constitute a new approved move.

The wider sensors were authorized by pm-midi-1 on 2026-10-12. The old 36mm
sensor / 72mm endpoint has only about 16° of vertical field of view; framing
the 100.6-unit actor requires several hundred units of stand-off. That cannot
deliver the requested near-feet perspective. The wider sensors retain the exact
32–72mm curve, including its 2.25× focal change and every timing key. The optical
field of view changes; the fast push-in timing is preserved. The manifests
label this explicitly.

`take3.py` derives each initial preview from T312 B. It preserves noncamera
transforms and animation across 108 frames, the HDRI image/node graph/rotation/
strength, robot placement, and actor/dust timing. Legacy actions are retained
with fake users so Blender cannot discard them during another save/reload.
`verify_take3.py` compares saved scenes and checks a sub-150-unit station at
height ≤1, a ≥15° upward reveal during frames 44–63, a ≥20° upward hold, an empty
opening, and actor/horn clearance at frame 40 and every frame 44–108. Five
negative controls reject the old camera, old tilt, a distant low camera,
a visible waiting actor, and restoration of the narrow sensor. The opening
frustum check correctly handles the waiting actor behind the near plane.

`take3_hold.py` derives the revised endpoint from B. It freezes a copied camera
action and preserves the original action archive. It compares all 108 frames
of noncamera state, the lens curve, and the environment before and after
save/reload. Four negative controls reject the old centered composition,
old stand-off, old tilt, and a narrow-sensor crop. Exact in-memory values are
restored and mutations are never saved. `hold_verification.json` records the
placement, framing, source/scene hashes and negative-check evidence. Existing
`verify.py` additionally passed its nine animation/dust negative checks for
both initial candidates.

Pixel review of initial A/B at 52/58/63 confirms the dust remains a low contact
cloud; the burst may cover the soles but leaves the body and background clear.
No powder thinning, moved lobes, or camera pullback was needed. Both initial
frame-86 horns are fully visible. Direct inspection of the revised graded endpoint also confirms the horn and
both feet remain visible; no dust obscures the lens. `take3_results.json` records
this pixel review alongside the scene and source-hash verification.

Reproduce the current endpoint from the repository root:

```bash
SHOT=/home/devin/src/2026/videdit/work/kaiju_arrival_313_take3
BLENDER=/home/devin/bin/blender-5.1.2-linux-x64/blender
GRADE_BLENDER=/home/devin/bin/blender-4.1.1-linux-x64/blender

"$BLENDER" -b --python-exit-code 1 --python blender/kaiju_arrival/take3_hold.py -- \
  --source "$SHOT/B/take_B.blend" --output "$SHOT/B_hold_left_third" --negative-checks
"$BLENDER" -t 6 -b "$SHOT/B_hold_left_third/hold_B_left_third.blend" \
  --python-exit-code 1 --python blender/kaiju_arrival/render.py -- \
  --output "$SHOT/B_hold_left_third/hold_exr" --frames 86 --samples 64 --percent 100
"$GRADE_BLENDER" -t 6 -b --python-exit-code 1 --python blender/kaiju_arrival/grade.py -- \
  --input "$SHOT/B_hold_left_third/hold_exr" --output "$SHOT/B_hold_left_third/stills"
/home/devin/src/2026/videdit/venv/bin/python blender/kaiju_arrival/take3_hold_review.py --directory "$SHOT"
```

`take3_preview.py` and `take3_review.py` retain the original two-camera motion
package tooling, for use if that work is resumed. Run long renders in a
persistent terminal/PTY session; a background child of a short-lived tool shell
may be terminated even with nohup. The preview pipeline checks scene hashes,
encodes 24fps clips, and fully decodes and verifies media, but the paused T313
clips have not completed this stage. No final movie has been rendered.

## T314: endpoint distance iteration

Round 01: `/home/devin/src/2026/videdit/work/kaiju_arrival_314_hold/round_01/`.
`stills/frame_0086.png` is one graded 1920×1080 / 64-sample frame. The camera
is 5% closer than the T313 left-third endpoint (71.4279 units), with the same
31.5° upward tilt, height, lens and sensor. Bounding-box margins are 3.35%
above the horn and 2.19% below the feet; pixel inspection confirms no clipping.
Devin approved this endpoint as final on 2026-10-12.

Reuse the T313 reproduction commands with this round's directory, passing
`--closer-percent 5 --keep-tilt --negative-checks` to `take3_hold.py` and using
the prior `B_hold_left_third/hold_B_left_third.blend` as its source.
Each round uses a fresh output directory. The copied camera action is detached
while solving yaw so an already-keyed endpoint cannot reset the trial rotation.
`take314_results.json` records saved-scene locks, the source hash chain, media
hashes, margins and review. Mutation checks reject zero camera movement and
a 0.1° tilt change at their respective assertions, with exact file restoration.

The follow-up move is saved in `../move_01/arrival_move.blend`. Its tripod
position is fixed; the existing focal curve supplies the push-in. The horizontal
pan eases from the original B opening bearing during frames 20–52, while tilt
eases from 13° to 31.5° during frames 44–63. From frame 63 onward the quaternion
is copied exactly from the approved hold. `take314_move.py` verifies the saved
move against the approved source, including all actor/dust animation, lens
frames, HDRI, station, optics, opening tilt and settled pan. The old frozen
endpoint fails the opening-tilt assertion in a negative mutation check.

Only `move_01/stills/frame_0001.png` and `frame_0052.png` were rendered as graded
1080p / 64-sample checks. The opening is empty; contact shows the full horn,
both feet on the ground, and small low dust puffs. The approved frame 86 is
reused from round 01. Devin subsequently approved the keyframes and final
render, with the empty opening trimmed to a short breath before entry.

`first_visible.py` rejects guaranteed-empty frames using mesh bounds against
the camera frustum, then uses full-resolution Workbench silhouette/depth masks
to account for opaque occlusion. **First visible frame: 31**, with 2,499 solid
beetle pixels entering from the left. Frames 1–30 are empty (1.25 seconds at
24 fps). This measures the solid silhouette before film distortion/glare,
without treating volumetric dust domains as opaque boxes. Evidence is in
`move_01/visibility/visibility.json` and `mask_0031.png`.

Build the move with `take314_move.py --source <round_01 blend> --output <move_01>`
under Blender 5.1.2, then use the standard render/grade commands with
`--frames 1,52 --samples 64 --percent 100`. Run `first_visible.py --output
<move_01/visibility>` with the saved move loaded in Blender 5.1.2. These scripts
do not overwrite the approved source or retime the actor.

### Approved final trim and reproduction

Final output directory: `/home/devin/src/2026/videdit/work/kaiju_arrival_314_final/`.
The delivery uses source frames **27–108**, 82 frames / 3.416667 seconds at
24 fps. Frames 27–30 provide four empty frames (1/6 second). First visibility
is output frame 5, contact is output frame 26, and the camera settles at output
frame 37. Animation keys retain their original source frame numbers.

The approved move includes a partial airborne reveal during frames 31–50:
the head is above the image until frame 51. This is explicitly recorded rather
than silently changing the approved 13° opening / 44–63 tilt path to satisfy
T311's older full-body-at-40 contract. `verify.py --entry-reveal-through 50`
keeps all nine animation/dust negative checks, the strict endpoint margins,
and verifies actual mesh containment on **every** frame 51–108. The exception
cannot extend to contact. A displaced post-entry camera fails this new check.

```bash
python3 blender/kaiju_arrival/take314_final.py \
  --move /home/devin/src/2026/videdit/work/kaiju_arrival_314_hold/move_01 \
  --output /home/devin/src/2026/videdit/work/kaiju_arrival_314_final
```

The driver renders missing native EXRs at 1080p / 64 samples, reuses the exact
approved frame-52 and frame-86 EXRs, grades with the pinned Blender 4.1.1 film
compositor, and encodes CRF-16 H.264. The scene remains a complete 108-frame
animation archive; `render_plan.json` records the trimmed delivery range.
Two workers share the RTX 3060. For this delivery the spare GTX 1050 Ti also
renders the disjoint entry range 27–51 using `render.py --device 1050`; wait for
that worker to finish before resuming the driver, avoiding duplicate frames.

`package.py --start-frame 27 --end-frame 108 --final` checks decoded frame
count, resolution, rate, duration, full decode, original T307 artifact hashes
and every graded-frame hash. An off-by-one start fails its frame-count check.
The render driver rejects a changed scene hash before launching any render.
`native_frame_hashes.json` records the retained linear sources; the final
media report and rendered-pixel review accompany the movie.
