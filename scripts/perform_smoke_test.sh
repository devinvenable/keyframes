#!/usr/bin/env bash
# Headless smoke test for scripts/perform.sh.
#
# Runs the script's own monitor detection and ffmpeg capture command against
# a throwaway Xvfb display (never the real screen), records a few seconds,
# then asserts the mkv has exactly one video and one audio stream with a
# nonzero duration. Then runs perform.sh's main() end-to-end with stub apps
# (PERFORM_PYTHON/PERFORM_OUTDIR hooks) to verify lifecycle robustness:
# normal exit, stale-lock removal, live-lock refusal, SIGKILL of the script
# (babysitter must still finalize ffmpeg), and rapid double Ctrl+C.
# Requires: Xvfb, ffmpeg/ffprobe, a PulseAudio/PipeWire default source (for
# the `-f pulse -i default` leg).
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
    local lock pid
    if [[ -n $FFMPEG_PID ]] && kill -0 "$FFMPEG_PID" 2>/dev/null; then
        kill -INT "$FFMPEG_PID" 2>/dev/null || true
        wait "$FFMPEG_PID" 2>/dev/null || true
    fi
    # Leftovers from the main() lifecycle tests (only on a FAIL path).
    if [[ -n ${RUN_PID:-} ]] && kill -0 "$RUN_PID" 2>/dev/null; then
        kill -KILL -- "-$RUN_PID" 2>/dev/null || kill -KILL "$RUN_PID" 2>/dev/null || true
    fi
    for lock in "$TMPDIR"/*/.perform.lock; do
        [[ -e $lock ]] || continue
        pid=$(head -n1 "$lock" 2>/dev/null) || pid=""
        # Only kill actual ffmpeg processes: test 4a seeds a lock with this
        # script's own pid, so a blind kill here would shoot ourselves.
        if [[ $pid =~ ^[0-9]+$ && $(cat "/proc/$pid/comm" 2>/dev/null) == ffmpeg ]]; then
            kill -KILL "$pid" 2>/dev/null || true
        fi
    done
    if [[ -n ${DUMMY_FFMPEG:-} ]]; then
        kill "$DUMMY_FFMPEG" 2>/dev/null || true
    fi
    pkill -KILL -f "$TMPDIR/stub-python" 2>/dev/null || true
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

# 0b. detect_video_encoder: env-var override in both directions, invalid
#     value rejected, and the fallback path — a PATH shim makes the ffmpeg
#     NVENC probe fail, which must select libx264.
got=$(PERFORM_VIDEO_ENCODER=libx264 detect_video_encoder) ||
    fail "detect_video_encoder rejected PERFORM_VIDEO_ENCODER=libx264"
[[ $got == libx264 ]] || fail "override libx264: got '$got'"

got=$(PERFORM_VIDEO_ENCODER=h264_nvenc detect_video_encoder) ||
    fail "detect_video_encoder rejected PERFORM_VIDEO_ENCODER=h264_nvenc"
[[ $got == h264_nvenc ]] || fail "override h264_nvenc: got '$got'"

if got=$(PERFORM_VIDEO_ENCODER=mpeg1video detect_video_encoder 2>/dev/null); then
    fail "invalid PERFORM_VIDEO_ENCODER accepted (got '$got')"
fi

mkdir -p "$TMPDIR/fakebin"
printf '#!/usr/bin/env bash\nexit 1\n' > "$TMPDIR/fakebin/ffmpeg"
chmod +x "$TMPDIR/fakebin/ffmpeg"
got=$(PATH="$TMPDIR/fakebin:$PATH" detect_video_encoder) ||
    fail "detect_video_encoder errored when the NVENC probe failed"
[[ $got == libx264 ]] || fail "failed NVENC probe: expected libx264, got '$got'"

# Real-environment probe: use whichever encoder this box provides for the
# capture run below, so the smoke test exercises the production path.
encoder=$(detect_video_encoder) || fail "detect_video_encoder failed"
[[ $encoder == libx264 || $encoder == h264_nvenc ]] ||
    fail "unexpected encoder '$encoder'"
echo "detect_video_encoder: overrides + fallback OK (this box: $encoder)"

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
build_ffmpeg_cmd "$out" "$w" "$h" "$x" "$y" "$mode" "$system_src" "$encoder"
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

echo "PASS: ${w}x${h} capture ($encoder), 1 video + $audio_count audio, duration ${duration}s"

###############################################################################
# 4. main() lifecycle tests. perform.sh runs end-to-end with stub apps
#    (PERFORM_PYTHON) into an isolated outdir (PERFORM_OUTDIR), forced to
#    libx264 so the NVENC probe is skipped, in --audio usb mode.
###############################################################################

STUB="$TMPDIR/stub-python"
cat > "$STUB" <<'EOF'
#!/usr/bin/env bash
# Stand-in for ShowSync/Keyframes: keyframes exits after STUB_KEYFRAMES_SLEEP
# seconds (simulating Esc ending the take); everything else sleeps until killed.
case ${1:-} in
    *keyframes*) exec sleep "${STUB_KEYFRAMES_SLEEP:-300}" ;;
    *)           exec sleep 300 ;;
esac
EOF
chmod +x "$STUB"

RUN_PID=""
DUMMY_FFMPEG=""

# Launch perform.sh main in its own session (own process group, like a real
# terminal foreground job, so `kill -INT -- -$RUN_PID` simulates Ctrl+C).
# Args: OUTDIR [extra VAR=VALUE assignments...]. Sets RUN_PID.
#
# The python3 shim matters: background jobs of a non-interactive shell start
# with SIGINT ignored, and bash cannot trap a signal that was ignored at
# entry — perform.sh's Ctrl+C handling would silently never run. Resetting
# SIGINT to default before exec reproduces a real terminal foreground job.
launch_perform() {
    local outdir=$1
    shift
    setsid env "$@" PERFORM_PYTHON="$STUB" PERFORM_OUTDIR="$outdir" \
        PERFORM_VIDEO_ENCODER=libx264 \
        python3 -c 'import signal, os, sys
signal.signal(signal.SIGINT, signal.SIG_DFL)
os.execvp(sys.argv[1], sys.argv[1:])' \
        bash "$HERE/perform.sh" --audio usb >"$outdir/run.log" 2>&1 &
    RUN_PID=$!
}

# Poll a condition command every 0.1s, up to $1 tenths of a second.
wait_for() {
    local tries=$1 i
    shift
    for (( i = 0; i < tries; i++ )); do
        "$@" && return 0
        sleep 0.1
    done
    return 1
}

not_running() { ! kill -0 "$1" 2>/dev/null; }
file_gone()   { [[ ! -e $1 ]]; }
file_there()  { [[ -e $1 ]]; }

# A take is only good if ffmpeg finalized it: 1 video + 1 audio (usb mode)
# and a numeric nonzero container duration — an aborted ffmpeg (no mkv
# trailer) reports duration N/A.
assert_valid_mkv() {
    local outdir=$1 label=$2 file streams video_count audio_count duration
    file=$(compgen -G "$outdir/perform_*.mkv" | head -n1) ||
        fail "$label: no recording file in $outdir"
    [[ -s $file ]] || fail "$label: recording is empty"
    streams=$(ffprobe -v error -show_entries stream=codec_type -of csv=p=0 "$file") ||
        fail "$label: ffprobe cannot read $file"
    video_count=$(grep -c '^video$' <<<"$streams" || true)
    audio_count=$(grep -c '^audio$' <<<"$streams" || true)
    [[ $video_count == 1 ]] || fail "$label: expected 1 video stream, got $video_count"
    [[ $audio_count == 1 ]] || fail "$label: expected 1 audio stream, got $audio_count"
    duration=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$file")
    [[ $duration =~ ^[0-9]+(\.[0-9]+)?$ ]] ||
        fail "$label: non-numeric duration '$duration' — mkv trailer missing?"
    awk -v d="$duration" 'BEGIN { exit !(d+0 > 0) }' ||
        fail "$label: duration not > 0 (got '$duration')"
    echo "$label: valid mkv ($duration s)"
}

# 4a. Normal path (stub Keyframes exits after 4s ~ Esc) + stale-lock removal:
#     a pre-existing lock naming a live NON-ffmpeg pid (this test script)
#     must be removed with a note, not refused.
OUT_NORMAL="$TMPDIR/run_normal"
mkdir -p "$OUT_NORMAL"
echo $$ > "$OUT_NORMAL/.perform.lock"
launch_perform "$OUT_NORMAL" STUB_KEYFRAMES_SLEEP=4
wait_for 300 not_running "$RUN_PID" ||
    { cat "$OUT_NORMAL/run.log" >&2; fail "normal run did not exit within 30s"; }
wait "$RUN_PID" || { cat "$OUT_NORMAL/run.log" >&2; fail "normal run exited nonzero"; }
grep -q "removing stale capture lock" "$OUT_NORMAL/run.log" ||
    fail "stale lock was not reported/removed (run.log lacks the note)"
grep -q "Recording saved" "$OUT_NORMAL/run.log" ||
    { cat "$OUT_NORMAL/run.log" >&2; fail "normal run did not report a saved recording"; }
file_gone "$OUT_NORMAL/.perform.lock" || fail "normal run left the lock behind"
assert_valid_mkv "$OUT_NORMAL" "normal+stale-lock"

# 4b. SIGKILL the script mid-capture: no trap runs, so only the babysitter
#     can save the take — ffmpeg must be gone within ~5s, the mkv must be
#     finalized, and the lock cleared.
OUT_KILL="$TMPDIR/run_sigkill"
mkdir -p "$OUT_KILL"
launch_perform "$OUT_KILL"
wait_for 300 file_there "$OUT_KILL/.perform.lock" ||
    { cat "$OUT_KILL/run.log" >&2; fail "SIGKILL run: capture never started"; }
fpid=$(head -n1 "$OUT_KILL/.perform.lock")
sleep 2
kill -KILL "$RUN_PID"
wait "$RUN_PID" 2>/dev/null || true
wait_for 60 not_running "$fpid" ||
    { kill -KILL "$fpid" 2>/dev/null || true
      fail "orphaned ffmpeg (pid $fpid) survived >6s after SIGKILL of perform.sh"; }
wait_for 50 file_gone "$OUT_KILL/.perform.lock" ||
    fail "babysitter did not clear the lock after SIGKILL"
assert_valid_mkv "$OUT_KILL" "SIGKILL"
pkill -KILL -f "$STUB" 2>/dev/null || true   # stub apps orphaned by SIGKILL
RUN_PID=""

# 4c. Rapid double Ctrl+C (SIGINT to the whole foreground process group,
#     exactly what a terminal delivers): the second INT must be absorbed and
#     the take still finalized.
OUT_INT="$TMPDIR/run_doubleint"
mkdir -p "$OUT_INT"
launch_perform "$OUT_INT"
wait_for 300 file_there "$OUT_INT/.perform.lock" ||
    { cat "$OUT_INT/run.log" >&2; fail "double-INT run: capture never started"; }
sleep 2
kill -INT -- "-$RUN_PID"
sleep 0.3
kill -INT -- "-$RUN_PID" 2>/dev/null || true
wait_for 200 not_running "$RUN_PID" ||
    { cat "$OUT_INT/run.log" >&2; fail "double-INT run did not exit within 20s"; }
wait "$RUN_PID" 2>/dev/null || true
grep -q "Finalizing recording" "$OUT_INT/run.log" ||
    fail "double-INT run never printed the finalizing notice"
file_gone "$OUT_INT/.perform.lock" || fail "double-INT run left the lock behind"
# The direct discriminator: a second SIGINT reaching ffmpeg makes it log
# "Immediate exit requested" and abort without the mkv trailer. (ffprobe
# alone is too lenient — it can still read a trailer-less mkv.)
if grep -q "Immediate exit requested" "$OUT_INT"/perform_*.mkv.log; then
    fail "ffmpeg received a second SIGINT (Immediate exit requested in its log)"
fi
assert_valid_mkv "$OUT_INT" "double-SIGINT"
RUN_PID=""

# 4d. Live-lock refusal: a lock naming a LIVE ffmpeg pid must abort startup
#     before any recording begins.
OUT_LOCK="$TMPDIR/run_locked"
mkdir -p "$OUT_LOCK"
# -re keeps the dummy encoding in real time, so it stays alive for the test.
ffmpeg -hide_banner -loglevel error -re -f lavfi -i anullsrc=r=8000 -t 120 \
    -f null - </dev/null >/dev/null 2>&1 &
DUMMY_FFMPEG=$!
echo "$DUMMY_FFMPEG" > "$OUT_LOCK/.perform.lock"
launch_perform "$OUT_LOCK"
wait_for 100 not_running "$RUN_PID" ||
    { kill -KILL -- "-$RUN_PID" 2>/dev/null || true
      fail "perform.sh kept running despite a live capture lock"; }
if wait "$RUN_PID" 2>/dev/null; then
    fail "perform.sh exited 0 despite a live capture lock"
fi
grep -q "already running" "$OUT_LOCK/run.log" ||
    { cat "$OUT_LOCK/run.log" >&2; fail "live-lock refusal message missing"; }
if compgen -G "$OUT_LOCK/perform_*.mkv" >/dev/null; then
    fail "a recording was started despite a live capture lock"
fi
kill "$DUMMY_FFMPEG" 2>/dev/null || true
wait "$DUMMY_FFMPEG" 2>/dev/null || true
DUMMY_FFMPEG=""
RUN_PID=""
echo "live-lock refusal: OK"

echo "PASS: main() lifecycle — normal/stale-lock, SIGKILL babysitter, double-SIGINT, live-lock refusal"
