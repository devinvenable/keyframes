#!/usr/bin/env bash
# Smoke test for scripts/mixdown.sh, in perform_smoke_test.sh style.
#
# Builds synthetic take fixtures with ffmpeg lavfi (matching perform.sh's
# recording layout: stream 0 h264, stream 1 aac title=mixer, stream 2 aac
# title=system) and asserts:
#   - the default mixdown yields 1 copied video + 1 aac audio, duration > 0
#   - per-track gains reach the RIGHT track (silencing the only audible
#     track must silence the output; a swapped mapping fails this)
#   - single-audio-track takes are handled gracefully
#   - a video-only file, a bad gain value, an existing output without -y,
#     and a missing input all fail
#
# Usage: scripts/mixdown_smoke_test.sh

set -euo pipefail

HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
MIXDOWN="$HERE/mixdown.sh"

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' INT TERM EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }

command -v ffmpeg  >/dev/null || fail "ffmpeg not installed"
command -v ffprobe >/dev/null || fail "ffprobe not installed"

# Build a 2s take fixture: VIDEO + audio track 1 (title=mixer) + audio
# track 2 (title=system). Args: OUT MIXER_LAVFI SYSTEM_LAVFI
make_take() {
    ffmpeg -hide_banner -loglevel error \
        -f lavfi -i "testsrc2=size=320x240:rate=30" \
        -f lavfi -i "$2" -f lavfi -i "$3" \
        -t 2 -map 0:v -map 1:a -map 2:a \
        -c:v libx264 -preset ultrafast -pix_fmt yuv420p -c:a aac \
        -metadata:s:a:0 title=mixer -metadata:s:a:1 title=system \
        "$1"
}

# Echo the mean_volume (dB) of a file's audio, e.g. "-91.0". volumedetect
# reports over the decoded samples; near -91 dB is digital silence.
mean_volume() {
    ffmpeg -hide_banner -i "$1" -map 0:a:0 -af volumedetect -f null - 2>&1 |
        sed -n 's/.*mean_volume: \(-\{0,1\}[0-9.]*\) dB.*/\1/p'
}

louder_than() { awk -v v="$1" -v t="$2" 'BEGIN { exit !(v > t) }'; }

# Assert OUT has 1 h264 video + 1 aac audio and a duration close to 2s.
# The video BITSTREAM md5 must match the input's: it survives the
# mkv->mp4 remux under -c:v copy but no re-encode can reproduce it.
assert_mixdown_shape() {
    local out=$1 in=$2 label=$3 streams vc ac dur pin pout
    [[ -s $out ]] || fail "$label: no output written"
    streams=$(ffprobe -v error -show_entries stream=codec_type,codec_name \
        -of csv=p=0 "$out")
    vc=$(grep -c '^h264,video$' <<<"$streams" || true)
    ac=$(grep -c '^aac,audio$' <<<"$streams" || true)
    [[ $vc == 1 ]] || fail "$label: expected 1 h264 video stream, got: $streams"
    [[ $ac == 1 ]] || fail "$label: expected 1 aac audio stream, got: $streams"
    dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$out")
    awk -v d="$dur" 'BEGIN { exit !(d >= 1.5 && d <= 3.0) }' ||
        fail "$label: duration '$dur' not ~2s"
    pin=$(ffmpeg -v error -i "$in" -map 0:v:0 -c copy -f md5 - </dev/null)
    pout=$(ffmpeg -v error -i "$out" -map 0:v:0 -c copy -f md5 - </dev/null)
    [[ -n $pin && $pin == "$pout" ]] ||
        fail "$label: video bitstream changed ($pin -> $pout) — video was re-encoded"
    echo "$label: OK (1 h264 copy + 1 aac, ${dur}s)"
}

# 1. Default mixdown of a both-tracks take.
TAKE="$TMPDIR/take.mkv"
make_take "$TAKE" "sine=frequency=440:sample_rate=48000" \
                  "sine=frequency=880:sample_rate=48000"
"$MIXDOWN" "$TAKE" >/dev/null || fail "default mixdown exited nonzero"
assert_mixdown_shape "$TMPDIR/take_final.mp4" "$TAKE" "default mixdown"
vol=$(mean_volume "$TMPDIR/take_final.mp4")
louder_than "$vol" -40 || fail "default mixdown is near-silent (mean_volume $vol dB)"

# 2. Gain routing: in a take where only the MIXER track has signal,
#    --mixer-gain 0 must silence the output while the default stays loud.
#    A mixdown that swaps the gains (or picks tracks by luck) fails here.
TAKE_M="$TMPDIR/take_mixeronly.mkv"
make_take "$TAKE_M" "sine=frequency=440:sample_rate=48000" \
                    "anullsrc=sample_rate=48000:channel_layout=stereo"
"$MIXDOWN" "$TAKE_M" >/dev/null || fail "mixer-only mixdown exited nonzero"
vol=$(mean_volume "$TMPDIR/take_mixeronly_final.mp4")
louder_than "$vol" -40 || fail "mixer-only default mix is silent (mean_volume $vol dB)"
"$MIXDOWN" --mixer-gain 0 -o "$TMPDIR/muted_mixer.mp4" "$TAKE_M" >/dev/null ||
    fail "--mixer-gain 0 run exited nonzero"
vol=$(mean_volume "$TMPDIR/muted_mixer.mp4")
louder_than "$vol" -70 && fail "--mixer-gain 0 did not silence the mixer track (mean_volume $vol dB)"

#    Same discriminator on the system side.
TAKE_S="$TMPDIR/take_systemonly.mkv"
make_take "$TAKE_S" "anullsrc=sample_rate=48000:channel_layout=stereo" \
                    "sine=frequency=880:sample_rate=48000"
"$MIXDOWN" --system-gain 0 -o "$TMPDIR/muted_system.mp4" "$TAKE_S" >/dev/null ||
    fail "--system-gain 0 run exited nonzero"
vol=$(mean_volume "$TMPDIR/muted_system.mp4")
louder_than "$vol" -70 && fail "--system-gain 0 did not silence the system track (mean_volume $vol dB)"
"$MIXDOWN" --system-gain -6dB -o "$TMPDIR/attenuated.mp4" "$TAKE_S" >/dev/null ||
    fail "dB gain syntax rejected"
echo "gain routing: OK (per-track mute lands on the right track, dB accepted)"

# 3. Single-audio-track take (usb-only recording) is handled gracefully.
SINGLE="$TMPDIR/single.mkv"
ffmpeg -hide_banner -loglevel error \
    -f lavfi -i "testsrc2=size=320x240:rate=30" \
    -f lavfi -i "sine=frequency=440:sample_rate=48000" \
    -t 2 -map 0:v -map 1:a \
    -c:v libx264 -preset ultrafast -pix_fmt yuv420p -c:a aac \
    -metadata:s:a:0 title=mixer "$SINGLE"
"$MIXDOWN" "$SINGLE" >/dev/null || fail "single-track mixdown exited nonzero"
assert_mixdown_shape "$TMPDIR/single_final.mp4" "$SINGLE" "single-track"

# 4. --loudnorm path completes and still yields the right shape.
"$MIXDOWN" --loudnorm -o "$TMPDIR/loudnorm.mp4" "$TAKE" >/dev/null ||
    fail "--loudnorm run exited nonzero"
assert_mixdown_shape "$TMPDIR/loudnorm.mp4" "$TAKE" "loudnorm"

# 5. Failure paths.
VIDONLY="$TMPDIR/videoonly.mkv"
ffmpeg -hide_banner -loglevel error -f lavfi -i "testsrc2=size=320x240:rate=30" \
    -t 1 -c:v libx264 -preset ultrafast -pix_fmt yuv420p "$VIDONLY"
"$MIXDOWN" "$VIDONLY" >/dev/null 2>&1 && fail "a video-only file was accepted"
"$MIXDOWN" --mixer-gain 'foo;volume' "$TAKE" >/dev/null 2>&1 &&
    fail "a non-numeric gain was accepted"
"$MIXDOWN" "$TMPDIR/no_such_take.mkv" >/dev/null 2>&1 && fail "a missing input was accepted"
"$MIXDOWN" "$TAKE" >/dev/null 2>&1 && fail "an existing output was overwritten without -y"
"$MIXDOWN" -y "$TAKE" >/dev/null || fail "-y refused to overwrite"
echo "failure paths: OK (no-audio, bad gain, missing input, no-clobber)"

echo "PASS: mixdown.sh — default mix, gain routing, single-track, loudnorm, failure paths"
