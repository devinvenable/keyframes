# Independent T306 resume QA

Verified by codex-midi-265 on 2026-10-11, against the existing cinematic scene.
No camera, source code, render settings or running job were changed. The final
render was launched by codex-midi-263, who retains ownership per pm-midi-1.

- All 108 inherited preview PNGs decode and have dimensions 633×356.
- The 55 reused frames (2–110, step 2) have identical hashes to the approved
  T305 sequence. All 53 later frames appear in the v4 render logs and postdate
  the candidate scene. Candidate and baseline hashes match camera QA.
- Re-encoding and media audit passed: 108 frames at 12 fps for the extension;
  652 frames at 24 fps for the joined preview. Both videos decode successfully.
- Camera QA rerun passed: zero matrix difference across 441 samples through
  frame 111; all 217 non-camera animation frames unchanged. All four negative
  controls failed on their intended assertions, including the unfixed camera.
- Overnight preflight passed, including original-asset integrity checks.

Per-frame hashes and resume evidence are recorded in
`/home/devin/src/2026/videdit/work/liftoff_305/preview_resume_verification.json`.
The same directory contains the refreshed camera and media verification JSON.

At handoff, `midi-liftoff-306.service` is running and job phase is `RENDERING`.
This is not final-media completion. Completion requires
`final_media_verification.json` with `status: PASS`: 216 extension / 652 joined
frames, both 1920×1080 at 24 fps, clean decoding, and source-quality settings
(4096 sample cap, 0.01 adaptive threshold, original volume settings).
