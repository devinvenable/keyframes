# Clock Divider performance clips (task 166)

24 silent visual excerpts from `small for clipping.blend`, exported September
25, 2026 for Keyframes. These are selections from the remaining workspace
footage, not a continuous reconstruction. They repeat at the cut; no claim of
seamless motion or musical synchronization is intended.

## Source and preserved workspace

- Workspace: `/home/devin/src/2026/videdit/work/small for clipping.blend`.
- Its single movie strip points to
  `/home/devin/src/2026/midi/songs/clock_divider_missing_on_the_one.mp4`, with
  `frame_start=1`, `frame_offset_start=1977`, final range `[1978, 10102)`,
  and scene render range `2006–10125` at `30000/1001` fps.
- The referenced MP4 has deliberately been trimmed to 1978 frames / 66.005s,
  so it cannot supply the workspace's remaining frames.
- Devin explicitly confirmed using the full source from
  `/home/devin/src/2026/midi/songs/demo_with_video.zip`, member
  `clock_divider_missing_on_the_one.mp4`, for the saved workspace range.
  That archived source is 1280×720, 10101 frames, approximately 337.07s.
  Selections start at 67s and finish before the archived source ends.
- Full-source SHA-256:
  `9e5fa86b67db6562bbd4d573b56054900264b4fad6d53704739833a7a37c32b6`.
- The visible Blender process was never driven, reloaded, saved, or modified.
  Inspection used an autosave copy and then the named saved blend in separate
  `--background --factory-startup --disable-autoexec` processes. The blendermod
  server on port 6814 actually belongs to a different headless scene, so it was
  not used to export this material.

## Installed media

GIFs are installed beside the existing collection in
`/home/devin/src/2026/midi/keyframes/images/`. Silent H.264 MP4 excerpts are kept
in `/home/devin/src/2026/midi/recordings/keyframes-clips-166/`.

GIFs use lowercase hyphenated names, 480×270 pixels, 15 fps (GIF centisecond
rounding alternates 60/70ms delays), an optimized 256-color palette, and infinite
repeat. They have no audio. MP4 excerpts preserve source resolution and frame
rate, use CRF 18, and omit audio. Runtime media stays outside git, consistent
with the repository's ignored media directories; this directory records the
selection and verification results.

`selection.json` contains exact source start times and requested durations.
`validation.json` records frame counts, sizes, hashes, and measured decoding
cost. `preview-1.jpg` through `preview-3.jpg` show first/middle/last frames for
clips 1–8, 9–16, and 17–24 respectively.

## Reproduction

Extract the archive member into a **different** temporary path; do not replace
the deliberately trimmed MP4. For each entry in `selection.json`, export with:

```sh
ffmpeg -ss START -i ARCHIVED_SOURCE -t DURATION -map 0:v:0 -an \
  -c:v libx264 -preset fast -crf 18 -pix_fmt yuv420p -movflags +faststart NAME.mp4
ffmpeg -i NAME.mp4 -filter_complex \
  'fps=15,scale=480:270:flags=lanczos,split[a][b];[a]palettegen=max_colors=256:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=3:diff_mode=rectangle' \
  -an -loop 0 NAME.gif
```

Use `-n` to prevent accidental overwrites, and modest thread counts on the
performance machine. The originals and all pre-existing media remain intact.

## Verification

- Existing `test_gif_support.py` and `test_mapping.py`: **30 passed**.
- Every MP4 contains one video stream and no audio stream.
- Every GIF decoded fully at 480×270 with multiple distinct frames and expected
  duration, and was exercised through Keyframes `VideoPlayer` for more than
  three clip lengths without finishing or freezing.
- Every GIF generated a thumbnail through Keyframes' actual thumbnail code.
- No application code or new test suite was added; negative testing of new tests
  is therefore not applicable.

Installed GIFs total **61.47 MiB**, with a maximum of **4.86 MiB** each. Silent MP4s total **39.11 MiB**.

New clips occupy MIDI notes **72–95**. All 36 existing manifest assignments (notes 36–71) were preserved. Mapping snapshots are stored alongside the MP4s as `mapping-before.json` and `mapping-after.json`. Restart Keyframes if it was already open so it rescans the folder; the new clips then appear in its Tab grid.

During export, 16 older files were independently removed from the live media folder. Installation preserved all old manifest entries and explicitly appended the new notes instead of occupying those older slots. Keyframes will prune entries for missing files on its next normal launch; the 24 new assignments remain 72–95. No removed media was restored or overwritten.

Every installed file was hash-checked against the validated export. The installed mapping was checked through Keyframes `reconcile_mapping` without writing its result, and all 24 new entries were loaded through `make_media_entry`, opened as looping video players, and decoded their first frame.

Measured decode-plus-scale time in the dummy-display audit was 0.99–1.91 ms/frame at 480×270; this is a decoder check, not a fullscreen live-performance benchmark.

| MIDI note | Filename stem (both `.gif` and `.mp4`) | Source start (s) | GIF duration (s) | GIF MiB |
|---:|---|---:|---:|---:|
| 72 | clock-divider-01-circuit-static | 67.00 | 5.00 | 2.55 |
| 73 | clock-divider-02-tape-machine | 89.50 | 3.00 | 2.33 |
| 74 | clock-divider-03-submerged-figures | 93.30 | 3.47 | 0.65 |
| 75 | clock-divider-04-laser-haze | 97.10 | 3.47 | 0.62 |
| 76 | clock-divider-05-neon-performer | 111.25 | 4.00 | 3.16 |
| 77 | clock-divider-06-red-mask | 120.10 | 3.80 | 2.14 |
| 78 | clock-divider-07-blue-mannequins | 129.25 | 4.54 | 3.15 |
| 79 | clock-divider-08-smoke-tower | 135.00 | 3.27 | 3.44 |
| 80 | clock-divider-09-choir-portal | 139.00 | 3.74 | 0.70 |
| 81 | clock-divider-10-static-dancers | 145.00 | 5.00 | 4.50 |
| 82 | clock-divider-11-striped-gateway | 156.30 | 3.40 | 2.56 |
| 83 | clock-divider-12-light-vortex | 160.75 | 3.54 | 2.52 |
| 84 | clock-divider-13-magenta-dancer | 165.25 | 1.80 | 2.03 |
| 85 | clock-divider-14-vintage-faces | 181.20 | 2.00 | 0.99 |
| 86 | clock-divider-15-cloud-warp | 193.00 | 6.00 | 4.15 |
| 87 | clock-divider-16-cube-portal | 215.25 | 1.47 | 1.34 |
| 88 | clock-divider-17-rotating-gallery | 229.00 | 3.47 | 4.25 |
| 89 | clock-divider-18-solar-drummer | 237.75 | 2.27 | 1.63 |
| 90 | clock-divider-19-green-beams | 247.00 | 5.00 | 1.01 |
| 91 | clock-divider-20-light-corridor | 265.00 | 6.00 | 2.70 |
| 92 | clock-divider-21-street-kaleidoscope | 274.00 | 5.00 | 4.58 |
| 93 | clock-divider-22-color-orbits | 311.00 | 8.00 | 3.86 |
| 94 | clock-divider-23-grid-hand | 321.00 | 6.00 | 4.86 |
| 95 | clock-divider-24-negative-grid | 329.00 | 2.47 | 1.74 |
