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

## T313: at the feet, with an upward reveal — preview choice gate

Outputs: `/home/devin/src/2026/videdit/work/kaiju_arrival_313_take3/`.
**Preview only; final rendering remains gated on Devin's camera pick.**

Start with `review.html`, which embeds both clips and all twelve graded stills.
`camera_choices.jpg` compares the opening, contact and hold. Per-take timing
sheets show frames 1/40/52/58/63/86. The two MP4s contain every source frame
40–86 at 24 fps (47 frames / 1.958 seconds), at 480×270 / 4 Cycles samples.
Stills are 960×540 / 16 samples. All pass through the existing SHA-pinned
Blender 4.1.1 film compositor and AgX, without the old salvage trim.

| Take | Tripod position | Landing distance | Tilt, frames 44–63 | Sensor | 36mm-sensor equivalent |
| --- | --- | --- | --- | --- | --- |
| A — Ground approach | (5, −35, 1) | 120.8 | 4° → 24° | 130 mm | 8.9–19.9 mm |
| B — At the feet | (−15, −5, 0.7) | 85.4 | 13° → 29° | 170 mm | 6.8–15.2 mm |

**Recommended: B** for the strongest near-feet perspective. A has a less
extreme station and gives the airborne beat more breathing room. Both camera
positions remain fixed; a smooth horizontal pan ends at contact, while the
upward tilt continues until frame 63 and remains fixed through the hold.

The sensor change is deliberate, authorized by pm-midi-1 on 2026-10-12. The
old 36mm sensor / 72mm endpoint has only about 16° of vertical field of view;
framing the 100.6-unit actor with that optical setup requires several hundred
units of stand-off. It cannot deliver the requested near-feet perspective.
The wider sensors retain the exact original 32–72mm curve, including the 2.25×
focal change and every timing key. Thus the optical field of view changes,
while the fast push-in timing is preserved. The manifest labels this explicitly.

`take3.py` derives each preview from the saved T312 B scene. It preserves all
noncamera evaluated transforms and animation curves across 108 frames, the
HDRI node graph/image/rotation/strength, robot placement and visibility, and
actor and dust timing. Unused legacy actions are retained with fake users so
Blender cannot discard them on this additional save/reload. The T312 source
and original T311 master hashes are checked by the review packager.

`verify_take3.py` checks the saved derivative against T312 B, verifies a
sub-150-unit station at height ≤1, a ≥15° upward reveal during frames 44–63,
a ≥20° upward hold, an empty opening, and actor/horn clearance at frame 40
and every frame 44–108. Its opening frustum check also handles the waiting
actor behind the close camera's near plane. Negative controls reject the
unfixed T312 B camera and tilt, an opening aimed at the waiting actor, and
restoration of the original narrow sensor. Exact in-memory values are restored;
mutated scenes are never saved. Existing `verify.py` checks contact, dust birth
and settling, rigid geometry, opponent separation and robot exclusion.

The scene checks do not replace rendered-pixel review at 52/58/63/86. The dust
remains unchanged in these candidates: no thinning, no moved lobes, no camera
pullback to escape a volume. Both tripod stations sit outside the contact
cloud; the visible powder may cover the soles during the burst but should
leave the body and background readable.

```bash
SHOT=/home/devin/src/2026/videdit/work/kaiju_arrival_313_take3
SOURCE=/home/devin/src/2026/videdit/work/kaiju_arrival_312_take2/B/take_B.blend
BLENDER=/home/devin/bin/blender-5.1.2-linux-x64/blender
PYTHON=/home/devin/src/2026/videdit/venv/bin/python

for take in A B; do
  "$BLENDER" -b --python-exit-code 1 --python blender/kaiju_arrival/take3.py -- \
    --source "$SOURCE" --output "$SHOT/$take" --take "$take"
  "$BLENDER" -b --python-exit-code 1 --python blender/kaiju_arrival/verify_take3.py -- \
    --source "$SOURCE" --take "$SHOT/$take/take_$take.blend" \
    --output "$SHOT/$take/locked_verification.json" --negative-checks
  "$BLENDER" -b "$SHOT/$take/take_$take.blend" --python-exit-code 1 \
    --python blender/kaiju_arrival/verify.py -- \
    --output "$SHOT/$take/animation_verification.json" --negative-checks
done

# Detached workers avoid the terminal render-timeout failure from T312.
nohup "$PYTHON" -u blender/kaiju_arrival/take3_preview.py --directory "$SHOT" \
  > "$SHOT/preview.log" 2>&1 < /dev/null &
# Run after both workers finish successfully:
"$PYTHON" blender/kaiju_arrival/take3_review.py --directory "$SHOT"
```

The preview renderer uses bounded subprocesses, checks the scene hash before
and after rendering, decodes each MP4 fully and checks its dimensions, frame
count, frame rate and duration. It does not start any final-quality render.
