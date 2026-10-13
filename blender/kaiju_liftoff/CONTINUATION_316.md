# T316: two-second ascent with a locked camera

Devin approved the short continuation via pm-midi-1 on 2026-10-12: append
48 frames (218–265), hold the camera at its frame-217 pose, keep the natural
ascent, and cut while the robot is still departing. The full-exit experiment
was rejected; its preview evidence remains in `liftoff_316/exit_hold/`.

Approved output directory:
`/home/devin/src/2026/videdit/work/liftoff_316/fixed_camera/`.
Original footage remains in the sibling `liftoff_305/` directory.

## Motion and continuity

`continue_ascent.py` defaults to the approved 48-frame version. It freezes
existing Bezier handles before appending keys, preserving all scene-object
world matrices exactly across frames 1–217. The lift re-eases from the
photographed last step (0.0944 units/frame) to 2.3 units/frame over 16 frames.
The camera remains at its existing endpoint throughout. The six plume
objects continue their original flutter formula; all other scene assets,
lighting and pose are retained. `--full-exit` reproduces the rejected long
preview only; do not use it for the final.

The old clip has **216 distinct frames (2–217)**, since frame 1 duplicated
the teaser endpoint. Appending 48 gives **264 frames / 11 seconds**. The
teaser join has **700 frames / 29.166667 seconds**, all at 1920×1080, 24 fps.

## Native rendering and grade

Blender **5.1.2** renders native RGB float32 EXRs with the approved source's
Cycles settings (4096 maximum samples, adaptive threshold .01, volume step
1, 1024 maximum volume steps, OPTIX RTX 3060). Blender **4.1.1** runs the
pinned recovered `kaiju_1960s` compositor. No inverse-AgX reconstruction is
used for the new final frames. `grade_continuation.py --native-exr` defaults
to zero trim; this continuation explicitly opts into `--trim-code-values 3`
to match the already approved footage.

That continuity adjustment was measured, not assumed: native f218 without
trim has YAVG 109.623 against approved f217's 106.950. Applying −3 per RGB
code value gives 107.056 (difference .106); frame-to-frame RGB MAE is .926
and the static left background MAE is .751. The EXR retains HDR values up
to 41.095. This is a match to T309's existing pixels, not EXR reconstruction
repair. It should not be copied to unrelated native renders.

## Execution and verification

The directory's `job/` contains a self-contained copy of the render, grade,
packaging and verification scripts. `run_continuation_final.py` records its
approval note, candidate hash and current phase in `job_status.json`.
Render progress and errors are in `final_job.log`. The render resumes by
skipping already completed EXRs; a partial grading or packaging stage
requires fresh output directories. Use an explicit new process session
(`subprocess.Popen(..., start_new_session=True)`) for a detached launch.

`package_continuation.py` copies approved graded PNGs without changing them,
appends the new graded PNGs, encodes both clips, then verifies frame counts,
1080p24, duration, clean decode, source/output hashes, native EXR HDR data,
source rendering quality, grade provenance, and seam luminance.

`verify_continuation_pixels.py` checks the photographed climb, recession,
visible exhaust and subpixel pillar registration. Preview results show a
229.7-pixel rise after two seconds, 39.9% of the starting body area, and
less than .07 pixels of measured static-background displacement. Negative
controls reject the original frozen endpoint and the superseded drifting
camera on their intended assertions. The superseded full-exit test also
rejects a frame with robot/plumes still present.

## Final delivery — verified

- `fixed_camera/kaiju_liftoff_final_graded_continued.mp4`: 264 frames,
  11.000000 seconds, 1920×1080 at 24 fps.
- `fixed_camera/teaser2_with_liftoff_final_graded_continued.mp4`: 700 frames,
  29.166667 seconds, 1920×1080 at 24 fps.
- Full decode passed on both files. All 216 approved graded frames were copied
  byte-identically; all 48 new float32 EXRs passed HDR/shape/finite-value checks.
- Encoded seam YAVG: 107.06 → 107.10 (difference .04). Encoded images also
  pass the climb and fixed-camera contracts: 229.29 pixels of ascent and
  less than .07 pixels of background displacement.
- Final graded contact sheet and decoded final frame were visually inspected:
  the robot remains visible and departing at the cut, the pillars stay fixed,
  and the two warm plumes retain smooth highlights.
- Summary and output SHA256 hashes: `continuation_316_final_results.json`.
  Exhaustive per-frame hashes: output directory `final_verification.json`.
