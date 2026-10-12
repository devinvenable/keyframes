# T309 — recovered kaiju_1960s grade applied to the 216-frame extension

The full T308 chain was applied per frame to the 216 lossless extension PNGs
(frames 2–217): inverse AgX using the Blender 5.1.2 OCIO config → scene-linear
EXR → recovered kaiju_1960s compositor in one Blender 4.1.1 process (profile
SHA256 `adf204f3…6a952c38`, verified before the run) → forward AgX → the
separately labeled reconstruction trim of −3 code values per RGB channel.
Driver: `apply_grade_sequence.py`. New files only; the ungraded finals were
not modified (input frame 2 SHA256 still `b919f226…5db0792c`).

## Outputs

Under `/home/devin/src/2026/videdit/work/liftoff_305/`:

- `cinematic_final_frames_graded/`: 216 graded 1920×1080 PNGs, same numbering.
- `kaiju_liftoff_final_graded.mp4`: 216 frames, 1080p24, CRF 16.
- `teaser2_with_liftoff_final_graded.mp4`: 652 frames, 1080p24, T306 join
  method (same filter graph as `render_job_306/package_final.py`; teaser
  segment from the same `teaser2.mp4` source, original audio fading over the
  final 0.25 s, extension silent).
- `graded_media_verification.json`: full audit (also committed here as
  `graded_309_results.json`).
- `graded_job_309/`: run log, plume QA plates and stats. Intermediate EXRs
  (~2.8 GB) were deleted after the run.

## Verification

- Frame 2 reproduces the T308 validation: YAVG **78.0366** full-run
  (**78.0372** in the single-frame validation) vs T308's **78.0371**; pixel
  MAE vs the probe's `extension_grade_trim.png` is 0.61/255 (max 8), entirely
  from the legacy NOISE grain texture, which re-randomizes per evaluation —
  the grain animates across the sequence, as film grain should.
- Negative control: the gate (|YAVG − 78.0371| < 0.2 on frame 2) rejects the
  ungraded source frame (YAVG 90.3242).
- Joined encode: 652 frames, 1080p24, clean `-v error` decode, duration
  27.1667 s. Extension encode: 216 frames, clean decode.
- Seam YAVG (ffmpeg signalstats on joined frames 436/437):
  teaser last **77.9460**, extension first **78.0581**, difference **0.112**.

## Plume caveat review (T308)

Peak-clipping frames were ranked by clipped-channel fraction over the
ungraded sequence; the maximum is frame 174 (0.118% of channel samples),
clustered over frames 171–183. A/B plates with 2× plume crops were built for
frames **120, 150, 174, 180** (`plume_ab.py`, plates and
`plume_ab_stats.json` in `graded_job_309/plume_qa/`) and visually inspected:

- No banding in the plume gradients on any inspected frame.
- No hue shift: bright-region (≥230) HSV hue mean moves ≈1/180 with
  unchanged spread; the flames stay white-core/warm-edge.
- The fog glow adds a soft halo around the plumes — consistent with the
  recovered 1960s look, not an artifact.
- The −3 trim leaves no clipped (255) samples in the graded plume crops and
  caused no visible highlight damage.

**No feathering or masking of the trim was needed.** Devin reviews the graded
join next session; if the glow halo reads too strong in motion, the chain can
be re-run with a reduced `glare_strength` without touching anything else.
