# T308 — matched frame and recovered teaser post-processing

The April 25 scene **does not reproduce the teaser brightness by itself**.
At the matched endpoint it measures **91.0185 YAVG**, versus **78.0660** in
the footage. The camera/pose check passes: **1.175 px RMS at 960×540** over
160 RANSAC inliers spanning 617×339 pixels (2.35 px at native resolution).
This independently validates reuse of the existing camera and pose fit on
the older scene; no new camera optimization was necessary.

The historical **kaiju_1960s compositor is recovered from source and session
evidence**. It accounts for most of the difference. Applying it to the actual
extension frame 2 gives **80.6100 YAVG**. A separately labeled reconstruction
trim of **−3 code values per RGB channel** gives **78.0371**, with RGB mean
absolute error **2.793/255** against the teaser endpoint. This is a close
brightness/appearance match, not a recovered pixel-exact export or pose.

**Recommendation:** review the post-only candidate before processing the
216-frame extension. Keep the recovered compositor and empirical trim distinct.
No full extension grading, replacement encode, or sequence re-render was run.

## Review artifacts

All generated artifacts are under:

`/home/devin/src/2026/videdit/work/liftoff_305/probe_apr25/`

- `ab_source.png`: teaser endpoint versus April 25 source-quality probe.
- `ab_grade.png`: teaser, raw probe, recovered compositor on the probe PNG.
- `ab_extension.png`: teaser, recovered compositor on extension frame 2,
  and recovered compositor plus the reconstructed trim.
- `matched_source_quality.png` / `matched_apr25.blend`: original probe.
- `extension_grade.png` / `extension_grade_trim.png`: proposed seam looks.
- `analysis.json`: hashes, image alignment, RGB errors, and both luma conventions.
- `grade_inventory_41.json`: native Blender 4.1 compositor/VSE inventory.
- `negative_verification.json`: assertion failures for deliberately wrong inputs.

The small numeric result is also committed as `probe_apr25_results.json`.
Source blends and footage were read only. The original April 25 blend SHA256
remained `4406e085fa45fcbffbdd72d2583d8f25dc087d958ea4c6997c7db586d7ce8ebf`.

## Measurements

| Frame / processing | ffmpeg YAVG | RGB MAE vs teaser |
| --- | ---: | ---: |
| Teaser endpoint | 78.0660 | 0 |
| April 25 raw, source-quality | 91.0185 | 15.069 |
| April 25, historical compositor rendered in Blender 4.1.1 | 81.1999 | 4.265 |
| April 25 PNG, inverse AgX → historical compositor → AgX | 81.2226 | 4.272 |
| Actual extension frame 2, same post-only chain | 80.6100 | 3.663 |
| Extension frame 2, chain + reconstructed RGB −3 trim | 78.0371 | 2.793 |
| Canon I48 recipe, tested verbatim | 108.1040 | 35.329 |
| Source `kaiju_progress.mkv`, near-tail frame | 78.1288 | 3.375 |
| Probe through inverse/forward color transforms, compositor bypassed | 91.3689 | 15.474 |

YAVG above uses the task's `ffmpeg -vf signalstats,metadata=print` convention.
Explicit BT.709 limited-range conversion gives teaser **77.8209**, raw probe
**90.7788**, recovered extension **80.3793**, trimmed extension **77.8130**.
Thus the near-zero mean seam difference survives a common matrix/range.
RGB errors use decoded RGB directly, without registration or pixel warping.
The MKV tail sample is adjacent content, not asserted to be the exact teaser frame.

The ungraded source-quality probe used Blender 5.1.2, RTX 3060 OptiX,
1920×1080, 4096 maximum samples, adaptive threshold 0.01, original volume
settings and AgX/None, exposure 0, gamma 1. Runtime: **90.24 seconds**.
Native April 25 depth of field was retained (focus 40, f/2.8); the extension
uses focus 100, f/5.6, so residual sharpness differences remain possible.
The additional historical-chain frame used Blender 4.1.1 and the documented
historical **64 samples**, taking 27.39 seconds after kernel initialization.

## Provenance: a batch render, not a viewport capture

Recovered session records, retrievable with `axon canon get`:

- `engram:chunk:777738`: explicitly states full resolution, 1920×1080,
  64 samples, writing to `voxel-shorts/renders/kaiju_full/`.
- `engram:chunk:777739`: launches `scripts/render_scene.py` on the Kaiju YAML.
- `engram:chunk:777740`: reports a 601-frame background render.
- `engram:chunk:777741`: commits camera revision `80979c7`.
- `engram:chunk:777743`: user asks to combine progress shots into a temporary MKV.
- `engram:chunk:777744`: records the encoding command:

```sh
ffmpeg -y -framerate 24 \
  -i /home/devin/src/2026/voxel-shorts/renders/kaiju_full/frame_%04d.png \
  -c:v libx264 -pix_fmt yuv420p /tmp/kaiju_progress.mkv
```

`~/Videos/kaiju_progress.mkv` is 1920×1080/24 fps, H.264 High, YUV420p,
limited range, with `Lavc61.19.101 libx264` / `Lavf61.7.100` tags. Its small
2.3 MB size does not establish screen capture. Historical PNG sequences remain
in `voxel-shorts/renders/kaiju_full/` and `kaiju_final_review/`.
The record proves the progress-video workflow; it does not cryptographically
identify the archived `/tmp` output with the later `~/Videos` copy.

`teaser2.mp4` has date tag `2026/04/25 18:51:10` and encoder
`Lavf60.16.100`. The surviving May `teaser.blend` Source edit contains
`kaiju_progress.mkv`, frames 158–451, with no strip modifiers, unit color
multiply/saturation, and compositing disabled. The MKV already carries the
dark look. The surviving May Graded scene is a later image-sequence grade;
its presence is not evidence that the April teaser used that later tree.

Native Blender 4.1 inspection confirms `use_nodes=False`, no compositor tree,
and no VSE strips in both `kaiju_assembled.blend` and
`kaiju_mountain_valley.blend`; the `kaiju_scene` variants also have compositing
disabled. `small for clipping.blend` edits unrelated MIDI footage.
The suggested `apr19/` directories were absent at the checked project, Videos,
and home locations. Inspection with Blender 5.1 misleadingly reports the
deprecated `use_nodes` field as true even when there is no tree; use the 4.1
inventory for this property.

## Recovered chain and the residual reconstruction

Historical implementation:
`/home/devin/src/2026/voxel-shorts/scripts/post_process_profiles.py`.
Its SHA256 is
`adf204f3cc23499a93616a5c8abc2ac73e9f106663fcf2b9c2d899f0a6952c38`,
identical to the file in April 24 commit `9521629`.
Camera commit `80979c7` contains the matching YAML parameters.
`render_scene.py` calls `apply_profile` **after** `assemble`, before rendering;
an assembled scene snapshot alone is therefore insufficient to recover the look.

In scene-linear space, before AgX:

1. Fog Glow: HIGH quality, threshold 0.8, size 8, strength 0.35 → mix −0.3.
2. Ellipse mask 0.92×0.84 → relative Gaussian blur 28%×28% → invert →
   MULTIPLY with the image at factor 0.25. Preserve the actual inversion;
   do not reinterpret it from the source's misleading center/edge comment.
3. Legacy NOISE texture (noise_scale 0.85, intensity 1, contrast 1.35),
   OVERLAY at factor 0.05.
4. Lens distortion 0, dispersion **0.018**.
5. AgX display transform, look None, exposure 0, gamma 1, then encode.

The source code and historical render record recover this chain. They do not
explain the remaining 2.54 luma units on the current extension. Rock shading,
pose, ring reflections, camera DOF, render version, and sample history prevent a
pixel-exact comparison. The historical-chain render and post-only result agree
within **0.023 YAVG**, supporting the practical PNG-processing route here.

For already-rendered extension PNGs, the tested route is:
**inverse Blender 5.1 AgX → scene-linear EXR → recovered Blender 4.1 compositor
→ AgX → optional RGB trim**. Applying the linear compositor directly to a
display PNG would use the wrong color space.

The optional trim is explicitly **reconstructed from this seam**, not found
in a historical script:

```text
lutrgb=r='max(val-3,0)':g='max(val-3,0)':b='max(val-3,0)'
```

Inverse AgX roundtrip error on extension frame 2 is 0.031 average and 0.243
maximum RGB code values. It cannot restore clipped radiance or remove prior
denoising/quantization. Particularly bright ignition/plume frames still need
review before applying this to the whole extension. Only the join frame was
graded in this task. The fitted trim can also clip near-black values.

I48 is ruled out: its grayscale conversion and backward vignette produce a
brighter, monochrome result (108.104 YAVG), unlike the teaser.

## Cost and verification

The measured post-only route takes about 2 seconds for inverse AgX plus
3 seconds for compositing per 1080p frame: roughly **18 minutes for 216 frames**,
budget **20–30 minutes including process startup, I/O and encoding**. This is
an extrapolation from single-frame probes. A reused Blender process could reduce
startup overhead. No geometry/camera/booster port is needed for this route.
The previous full-quality 216-frame job took about **6 hours 21 minutes**.

If choosing a true April-scene re-render instead, port/rebuild the final camera
action, corrected robot pose and hatch geometry, lift/booster/exhaust/dust rig,
rebased ring transforms and material timing, then validate the elevated camera
against that scene's fog boundary. The negative raw April probe provides no
brightness justification for that scene transplant.

The controls reject a 20-preview-pixel camera shift at the alignment assertion
(20.79 px RMS), and reject the rendered compositor-bypass image at the
2× RGB-improvement assertion. Controls ran after implementation commits, in
separate fixture directories; originals and implementation files were not
mutated. Logs are in `negative_camera/` and `negative_grade/`.

Reproduction tools in this directory:

- `probe_apr25.py`: one original-scene probe, optional historical-profile render.
- `inspect_grade.py`: read-only compositor/VSE inventory.
- `inverse_agx_probe.py`: one-PNG inverse view transform; needs OpenCV, NumPy,
  and PyOpenColorIO (probe used 2.6.0).
- `grade_probe.py`: original compositor on one EXR, run in Blender 4.1.1;
  `--bypass` supplies the negative control.
- `analyze_probe.py`: alignment, luma, RGB errors, comparison plates and controls.

Run the scripts with `--help` (Blender scripts take arguments after `--`).
Use `--factory-startup` for isolated Blender compositor runs. PyOpenColorIO was
installed only into `probe_apr25/python_deps`, not the system environment.
