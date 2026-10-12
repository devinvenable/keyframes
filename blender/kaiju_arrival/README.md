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
copies after each mutation. Existing T311 checks cover contact, dust birth and
settling, framing, and robot exclusion. Pixel inspection is still mandatory.
After a pick, use the existing final linear-EXR rendering, pinned grade, encoding,
full decode, and source-hash QA pipeline; do not interpret preview completion as
approval to start that stage.
