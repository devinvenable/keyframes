# Blender comparison grade

`apply_grade_video.py` applies the exact T309 recovered visual chain to Blender
renders. It is not the AI-video aging filter; for that treatment, use
`scripts/apply-aged-video.py`. The optional `--frames` argument makes a short
comparison clip from the beginning of a longer input.

The primary AI-video treatment is:

```bash
python3 scripts/apply-aged-video.py \
  --input /path/to/grid.mp4 \
  --output /path/to/grid_ffmpeg_aged_silent.mp4 \
  --reference-aged /path/to/insect_war_13_dogfight_5s_aged.mp4

python3 blender/kaiju_liftoff/mux_loudnorm.py \
  --video /path/to/grid_ffmpeg_aged_silent.mp4 \
  --audio /path/to/grid.mp4 \
  --output /path/to/grid_boosted_1960s.mp4 \
  --target-i -12 --target-tp -1
```

`apply-aged-video.py` copies the `GRADE` chain from
`scripts/generate-insect-war.py` exactly: monochrome, 1950s curve, 0.6 blur,
temporal uniform noise at strength 14, and a `PI/5.5` backward vignette. It
compares native saturation statistics with an actual insect-war `_aged.mp4`,
emits before/after still pairs, and performs a full decode.

```bash
python3 blender/kaiju_liftoff/apply_grade_video.py \
  --input /path/to/grid.mp4 \
  --output /path/to/grid_1960s_silent.mp4 \
  --frames 150 \
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
