#!/usr/bin/env bash
# Headless smoke test for scripts/perform.sh.
#
# Runs the script's own monitor detection and ffmpeg capture command against
# a throwaway Xvfb display (never the real screen), records a few seconds,
# then asserts the mkv has exactly one video and one audio stream with a
# nonzero duration. Requires: Xvfb, ffmpeg/ffprobe, a PulseAudio/PipeWire
# default source (for the `-f pulse -i default` leg).
#
# Usage: scripts/perform_smoke_test.sh

set -euo pipefail

HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=scripts/perform.sh
source "$HERE/perform.sh"

XVFB_DISPLAY=":99"
XVFB_PID=""
FFMPEG_PID=""
TMPDIR=$(mktemp -d)

cleanup() {
    trap - INT TERM EXIT
    if [[ -n $FFMPEG_PID ]] && kill -0 "$FFMPEG_PID" 2>/dev/null; then
        kill -INT "$FFMPEG_PID" 2>/dev/null || true
        wait "$FFMPEG_PID" 2>/dev/null || true
    fi
    if [[ -n $XVFB_PID ]]; then
        kill "$XVFB_PID" 2>/dev/null || true
    fi
    rm -rf "$TMPDIR"
}
trap cleanup INT TERM EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }

# 0. pick_editor_screen unit checks against canned xrandr --listmonitors
#    bodies (no display needed). Capture monitor is DP-1 at +1080+0.
THREE_MONITORS=' 0: +DP-3 1080/300x1920/530+0+0  DP-3
 1: +*DP-1 1920/480x1080/270+1080+0  DP-1
 2: +HDMI-0 1920/480x1080/270+3000+0  HDMI-0'
TWO_MONITORS=' 0: +DP-3 1080/300x1920/530+0+0  DP-3
 1: +*DP-1 1920/480x1080/270+1080+0  DP-1'
ONE_MONITOR=' 0: +*DP-1 1920/480x1080/270+1080+0  DP-1'

got=$(pick_editor_screen 1080 0 <<<"$THREE_MONITORS") ||
    fail "pick_editor_screen found nothing with 3 monitors"
[[ $got == HDMI-0 ]] || fail "3 monitors: expected HDMI-0 (other landscape), got '$got'"

got=$(pick_editor_screen 1080 0 <<<"$TWO_MONITORS") ||
    fail "pick_editor_screen found nothing with 2 monitors"
[[ $got == DP-3 ]] || fail "2 monitors: expected DP-3 (portrait fallback), got '$got'"

if got=$(pick_editor_screen 1080 0 <<<"$ONE_MONITOR"); then
    fail "1 monitor: expected failure, got '$got'"
fi
echo "pick_editor_screen: 3/2/1-monitor cases OK"

command -v Xvfb >/dev/null || fail "Xvfb not installed"

Xvfb "$XVFB_DISPLAY" -screen 0 1920x1080x24 &
XVFB_PID=$!
sleep 1
kill -0 "$XVFB_PID" 2>/dev/null || fail "Xvfb did not start (display $XVFB_DISPLAY busy?)"

export DISPLAY=$XVFB_DISPLAY

# 1. Monitor detection must find the Xvfb screen as a landscape region.
region=$(detect_capture_region) || fail "detect_capture_region found no monitor"
read -r w h x y <<<"$region"
echo "Detected region: ${w}x${h}+${x}+${y}"
[[ $w == 1920 && $h == 1080 ]] || fail "expected 1920x1080, got ${w}x${h}"

# 2. Record ~4 seconds in --audio both mode using the exact command
#    perform.sh runs (falls back to usb mode if no sink monitor exists).
mode="both" system_src=""
if system_src=$(system_audio_source); then
    expected_audio=2
else
    echo "NOTE: no default sink monitor here — testing usb mode only"
    mode="usb" expected_audio=1
fi
out="$TMPDIR/smoke.mkv"
build_ffmpeg_cmd "$out" "$w" "$h" "$x" "$y" "$mode" "$system_src"
"${FFMPEG_ARGS[@]}" </dev/null 2>"$out.log" &
FFMPEG_PID=$!
sleep 4
kill -0 "$FFMPEG_PID" 2>/dev/null || { cat "$out.log" >&2; fail "ffmpeg exited early"; }
kill -INT "$FFMPEG_PID"
# Graceful SIGINT must finish quickly; a hang here means the -nostdin
# regression is back (ffmpeg 7.1 ignores INT/TERM when -nostdin is set).
for _ in {1..100}; do
    kill -0 "$FFMPEG_PID" 2>/dev/null || break
    sleep 0.1
done
kill -0 "$FFMPEG_PID" 2>/dev/null && fail "ffmpeg did not exit within 10s of SIGINT"
wait "$FFMPEG_PID" 2>/dev/null || true
FFMPEG_PID=""

# 3. Probe the result: 1 video + $expected_audio audio streams, duration > 0.
[[ -s $out ]] || { cat "$out.log" >&2; fail "no output file written"; }
streams=$(ffprobe -v error -show_entries stream=codec_type -of csv=p=0 "$out")
video_count=$(grep -c '^video$' <<<"$streams" || true)
audio_count=$(grep -c '^audio$' <<<"$streams" || true)
[[ $video_count == 1 ]] || fail "expected 1 video stream, got $video_count"
[[ $audio_count == "$expected_audio" ]] \
    || fail "expected $expected_audio audio stream(s), got $audio_count"
duration=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$out")
[[ $duration =~ ^[0-9]+(\.[0-9]+)?$ ]] || fail "non-numeric duration '$duration'"
awk -v d="$duration" 'BEGIN { exit !(d+0 > 0) }' || fail "duration not > 0 (got '$duration')"

echo "PASS: ${w}x${h} capture, 1 video + $audio_count audio, duration ${duration}s"
