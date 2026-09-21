# T98: cropped first attacks, not MP3 decoding

Verified 2026-09-20 against the supplied `songs/` files and retr0 music assets.

## Diagnosis

The supplied files are different trims, not a WAV/MP3 encoding pair:

| File | Decoded frames at 48 kHz | Before | After |
| --- | ---: | --- | --- |
| cold_ignition_trimmed.wav | 3,115,901 | 120.002821 BPM, 0.495356 s | unchanged |
| cold_ignition_trimmed.mp3 | 2,731,105 | inconclusive | unchanged |
| cold_ignition_trimmed_dv.mp3 | 2,755,476 | inconclusive | 120.001093 BPM, 0 s |

All decoder frame counts equal their declared lengths. Sequential Decoder output
matches independent FFmpeg decoding to about 1.9e-7 RMS for both MP3s. Exporting
that decoded audio to float WAV preserves both original rejections. A fresh
libmp3lame VBR quality-2 encode of the supplied WAV already fits before this fix:
120.002397 BPM, offset 0.495190 s. No MP3 seek, padding, or duration bug was found.
The opening four seconds of the DV trim correlate at 0.9925 with the supplied WAV
starting approximately 7.5088 seconds into it.

Tracing `_fit` identified two separate checks:

- `trimmed.mp3`: weighted support 0.347311 is below 0.35. This remains inconclusive,
  as agreed with the PM; no support threshold was changed.
- `trimmed_dv.mp3`: weighted support 0.368089 passes, as do section consistency,
  residual, and beat coverage checks. The fitted first pulse is -0.015070 s.
  The old negative-boundary tolerance is 0.025 beat (12.5 ms at 120 BPM), so this
  otherwise accepted grid is rejected solely at the final boundary check.

A cut into the first attack is a normal file-trimming workflow. The fix allows
one MIDI clock tick (1/24 beat; about 20.8 ms at 120 BPM) of negative first-pulse
uncertainty and clamps that offset to zero. Larger negative boundaries still
reject. Rhythm acceptance, onset extraction, decoder behavior, and keyframes
are unchanged. Experimental onset-localization alternatives did not justify a
broader change.

## Regression verification

`tests/fixtures/cropped-beat.wav` and `.mp3` contain the same original 16-second,
120 BPM signal cut 15 ms into its first kick. Regenerate with
`python3 scripts/make_cropped_beat_fixtures.py` from `showsync/` (requires FFmpeg).
The checked-in pair needs no encoder at test time. Both now fit within 0.01 BPM
of 120 and each other, with offset zero. A second test checks both sides of the
one-tick cutoff at three tempos.

After committing the implementation, restored only the old boundary expression
from a uniquely matched target and ran both new tests: **2 assertion failures,
exit 1**. Restored the exact file from a temporary copy. After merging current
`origin/main` (including T97), ran:

```
QT_QPA_PLATFORM=offscreen OPENBLAS_NUM_THREADS=1 python3 -m pytest -q
```

Result: **251 passed, 4 skipped in 16.99 s, exit 0**.

## retr0 music sweep

Ran `estimate_grid` on all 46 unique filenames from `BG_MUSIC_CHANNELS` in
`/home/devin/src/2026/retr0/src/sound_manager.py`, loading each full file from
`assets/sounds/`. Baseline: 9 fits. Fixed: 10 fits. Only `david_three.mp3` changes;
all nine existing fit values are identical. This is a count of estimator results,
not independent musical validation of every returned tempo.

| File | Before | After BPM | After offset (s) |
| --- | --- | ---: | ---: |
| cold_ignition.mp3 | fit | 120.001880 | 2.085361 |
| crt_sunrise.mp3 | fit | 180.041775 | 4.244579 |
| david_10.mp3 | fit | 140.000216 | 5.494332 |
| david_12.mp3 | fit | 120.002608 | 0.626935 |
| david_13.mp3 | fit | 129.997472 | 15.022497 |
| david_seven.mp3 | fit | 127.999741 | 24.429383 |
| david_three.mp3 | inconclusive | 120.001629 | 0.000000 |
| gravity_well.mp3 | fit | 169.996817 | 2.285983 |
| neon_undertow.mp3 | fit | 112.003245 | 1.891905 |
| solder_burn.mp3 | fit | 200.000429 | 4.097186 |

The following 36 remain inconclusive before and after:

`ambient1.mp3`, `ambient2.mp3`, `ambient3.mp3`, `ambient4.mp3`, `arcade_afterglow.mp3`, `asteroid_waltz.mp3`, `aurora_drift.mp3`, `background.mp3`, `coin_slot_blues.mp3`, `dark_slow.mp3`, `david_11.mp3`, `david_9.mp3`, `david_eight.mp3`, `david_five.mp3`, `david_four.mp3`, `david_six.mp3`, `david_slow.mp3`, `david_two.mp3`, `dead_channel.mp3`, `dv_ambient_3.mp3`, `glass_cockpit.mp3`, `industry.mp3`, `ion_tail.mp3`, `jamzz17_normalized.mp3`, `low_orbit_lullaby.mp3`, `midnight_vector.mp3`, `nebula_static.mp3`, `panel_glow.mp3`, `phosphor_trail.mp3`, `quarter_muncher.mp3`, `starbase_diner.mp3`, `tally_march.mp3`, `thruster_hymn.mp3`, `tin_rocket.mp3`, `vector_storm.mp3`, `warp_lag.mp3`.
