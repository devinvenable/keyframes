# T175: live capture inputs need a shared clock

Measured 2026-09-26 with Ubuntu FFmpeg 7.1.1, NVIDIA NVENC, X11,
pygame 2.6.1 / SDL 2.28.4. The remaining capture failure reproduces without
ShowSync, Qt, or ShowSync's elevated threads. Removing CPU niceness and
increasing queues (T170) did not solve it.

`perform.sh` now applies `-isync 0` to **each** Pulse input (requires
FFmpeg 5.1 or newer). x11grab and Pulse's default `wallclock=1` use the
same clock, but FFmpeg otherwise independently rebases each input to zero.
Inputs open sequentially, so that loses their relative start offsets.
Aligning the inputs removes the repeating video stalls in these measurements.
The exact scheduler blocking mechanism was not instrumented; this is a
controlled command comparison, not a claim based on X-server profiling.

FFmpeg documents the intended live-input use of `-isync` in its
[option implementation](https://ffmpeg.org/pipermail/ffmpeg-devel/2022-July/298894.html).
FFmpeg 7.1's [scheduler](https://ffmpeg.org/doxygen/7.1/ffmpeg__sched_8c_source.html)
uses output timestamps to throttle input sources with a 100 ms tolerance.

## Isolation measurements

Each short run rendered a looping silent 1920x1080, 30fps test pattern through
Keyframes' actual `set_display_mode` and `VideoPlayer`, flipping at 60Hz.
Capture was the production region `:0+1080,0`, 1920x1080, x11grab 30fps,
queue 64, NVENC p4/ll/VBR/cq23, AAC audio with queues 4096. No full
`perform.sh` take or priority changes were used. Real-display access was
specifically authorized for T175; routine tests use Xvfb.

All variants are relative to the original command, not cumulative. FPS is
`(packet_count - 1) / (last_sorted_pts - first_sorted_pts)`, using the
production `capture_health_stats` function; no CFR/fps filter adds frames.

| Configuration | Frames | Effective fps | Gaps >100ms | Max gap |
|---|---:|---:|---:|---:|
| Keyframes only, video-only, default bypass=1 | 300 | 30.0 | 0 | 34ms |
| Same, explicit compositor bypass=2 | 300 | 30.0 | 0 | 34ms |
| Keyframes + default webcam + system monitor | 83 | 8.3 | 23 | 500ms |
| Keyframes + Behringer mixer + system monitor | 116 | 11.8 | 32 | 400ms |
| Same, fragment_size=3840 on both audio inputs | 156 | 15.6 | 32 | 300ms |
| Same, max_interleave_delta=0 | 237 | 23.7 | 9 | 200ms |
| Same, NVENC delay=0 | 133 | 13.2 | 44 | 200ms |
| Behringer only (one audio input) | 298 | 29.8 | 0 | 100ms |
| Both audio inputs, use_wallclock_as_timestamps=1 | 118 | 11.9 | 30 | 367ms |
| Both audio inputs, copyts + start_at_zero | 127 | 12.8 | 36 | 367ms |
| Both audio inputs, **isync=0 on each** | 295 | 29.5 | 1 | 167ms |
| Fixed, **30s with Keyframes + actual headless ShowSync Qt projector** | 892 | 29.7 | 1 | 233ms |

Keyframes rendered about 59–62fps throughout. The ShowSync run played
`neon_undertow_trimmed.wav` plus the generated test video. Its log confirmed
both clock and callback threads remained SCHED_OTHER. The fixed runs' single
gap was at startup, while FFmpeg opened/probed the inputs; ongoing capture
stalls disappeared. Final live-take verification remains Devin's step.

## Two-minute synchronization check

On private Xvfb `:175` at 640x360, ffplay presented a 130s test source:
black frames with a 200ms white flash every five seconds, plus a simultaneous
200ms 1kHz tone. SDL audio went to a temporary 48kHz stereo Pulse null sink,
`midi_175_sync`. Both recorder audio inputs independently opened that sink's
monitor. This gives two observations of the **same known sound**, allowing
alignment to be checked despite different stream start times.

Source generation:

```bash
ffmpeg -f lavfi \
  -i 'color=black:s=640x360:r=30,drawbox=color=white:t=fill:enable=lt(mod(t\,5)\,0.2)' \
  -f lavfi -i 'aevalsrc=0.5*sin(2*PI*1000*t)*lt(mod(t\,5)\,0.2):s=48000' \
  -t 130 -c:v libx264 -preset ultrafast -c:a pcm_s16le source.mkv
```

The capture used `build_ffmpeg_cmd` in `both` mode with the monitor as both
source arguments, NVENC, and output duration 120s. No other recorder settings
were changed. Results:

- 3,596 video frames, **30.0fps**, one startup gap of 166ms.
- Stream starts: video **0.000s**, mixer **0.189s**, system **0.259s**.
- All 24 tone onsets: audio tracks within **5ms** of one another throughout.
- Tone leads flash by **16–54ms**, bounded throughout the run; this check
  includes ffplay's presentation latency and one-frame video quantization.
- After `mixdown.sh`: all 24 onsets remain at the same times, tone leads
  flash by **20–53ms**; first-versus-last three-event median drift is <50ms.

Analysis decoded video without frame duplication (`-fps_mode passthrough`),
area-averaged frames to one grayscale pixel, and matched rising white edges
(threshold 150) to ffprobe frame PTS. Each audio stream was decoded to mono
48kHz float PCM; rising tone edges used RMS >0.05 in 5ms windows, adding that
stream's start PTS. Events were matched to the nearest flash. Merely checking
stream start times or frame counts would not establish synchronization.

This demonstrates timestamp preservation and absence of drift in the tested
shared-source setup. It does not calibrate the physical USB mixer's hardware
latency against the sound card or establish long-term hardware clock drift.
Evidence files/logs from this session are in `/tmp/midi-175/` (`sync.mkv`,
`sync_final.mp4`, `full-isync.mkv`, and the named matrix variants).

## Regression coverage

`perform_smoke_test.sh` now checks >=27fps on its real eight-second Xvfb
capture with two Pulse inputs, in addition to stream shape and shutdown
behavior. It passed at 28.1fps, including one 533ms input-opening gap.
With the committed implementation backed up and only `-isync 0` removed,
the same live capture section failed its rate assertion at **8.6fps**,
67 frames, 20 gaps, max500ms. Restore used the exact backup.

`mixdown.sh` pads each audio stream to the common origin with
`aresample=async=1:first_pts=0` before `amix`, which combines sample streams.
It retains gain routing, optional normalization, and video stream copying.
The new mixdown fixtures use 200ms tones starting at 0.25s and 0.85s, in
both track orders. They assert silence before/between tones and signal at
both original positions. Both pass. Removing the padding from the committed
implementation fails the leading-silence assertion; restoration used an
exact backup. Existing mixdown and recorder lifecycle smoke checks pass.
