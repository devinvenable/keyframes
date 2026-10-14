# Full-video capture grade

`apply_grade_video.py` applies the exact T309 recovered visual chain to every
frame of an arbitrary constant-frame-rate video. It writes a silent H.264
master so the slow Blender grade is performed once. Source media is read-only;
all frames, reports and videos are new files.

```bash
python3 blender/kaiju_liftoff/apply_grade_video.py \
  --input /path/to/grid.mp4 \
  --output /path/to/grid_1960s_silent.mp4 \
  --cleanup

python3 blender/kaiju_liftoff/mux_loudnorm.py \
  --video /path/to/grid_1960s_silent.mp4 \
  --audio /path/to/grid.mp4 \
  --output /path/to/grid_boosted_1960s.mp4 \
  --target-i -12 --target-tp -1
```

The first command follows the pinned inverse-AgX → Blender 4.1.1
`kaiju_1960s` compositor → forward-AgX → RGB −3 trim chain. Its work directory
is resumable and retained unless `--cleanup` is supplied. It emits two exact
before/after frame pairs and a visual QA JSON beside the silent master.

The second command measures the entire audio program, feeds those measurements
to a second EBU R128 loudnorm pass, stream-copies the already graded video, and
fully decodes and re-measures the result. To audition a louder target, re-run
only this command with (for example) `--target-i -10` and a different output
name.
