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
# Also checks Keyframes-only launch, USB default, audio overrides, and
# rejection of ShowSync arguments before capture starts.
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
    if [[ -n ${SHOWSYNC_RUN_PID:-} ]] && kill -0 "$SHOWSYNC_RUN_PID" 2>/dev/null; then
        kill -TERM "$SHOWSYNC_RUN_PID" 2>/dev/null || true
    fi
    if [[ -n ${NULL_SINK_MODULE:-} ]]; then
        pactl unload-module "$NULL_SINK_MODULE" 2>/dev/null || true
    fi
    pkill -KILL -f "$TMPDIR/stub-python" 2>/dev/null || true
    if [[ -n $XVFB_PID ]]; then
        kill "$XVFB_PID" 2>/dev/null || true
    fi
    rm -rf "$TMPDIR"
}
trap cleanup INT TERM EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }

# ShowSync-only arguments must fail before display/device checks or capture.
for args in '--headless' '--editor-screen HDMI-0' '--midi-transport' 'set list.json'; do
    if env -u DISPLAY bash "$HERE/keyframes-take.sh" "$args" >"$TMPDIR/args.log" 2>&1; then
        fail "Keyframes-only accepted ShowSync argument: $args"
    fi
    grep -q 'ERROR: --keyframes-only does not accept ShowSync arguments:' "$TMPDIR/args.log" ||
        fail "Keyframes-only did not reject ShowSync argument before startup: $args"
done
echo "Keyframes-only: ShowSync arguments rejected before capture"

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

# 0c. --mixer-source plumbing: build_ffmpeg_cmd must feed the named source
#     to the mixer pulse input (usb and both modes) and keep the Pulse
#     default when unset. DISPLAY may be unset before Xvfb starts.
DISPLAY=${DISPLAY:-:0} build_ffmpeg_cmd out.mkv 100 100 0 0 both sink.monitor libx264 my_usb_mixer
[[ " ${FFMPEG_ARGS[*]} " == *" -f pulse -thread_queue_size 4096 -isync 0 -i my_usb_mixer "* ]] ||
    fail "both mode ignored the mixer source (args: ${FFMPEG_ARGS[*]})"
[[ " ${FFMPEG_ARGS[*]} " == *" -f pulse -thread_queue_size 4096 -isync 0 -i sink.monitor "* ]] ||
    fail "both mode lost the system source (args: ${FFMPEG_ARGS[*]})"
DISPLAY=${DISPLAY:-:0} build_ffmpeg_cmd out.mkv 100 100 0 0 usb "" libx264 my_usb_mixer
[[ " ${FFMPEG_ARGS[*]} " == *" -f pulse -thread_queue_size 4096 -isync 0 -i my_usb_mixer "* ]] ||
    fail "usb mode ignored the mixer source (args: ${FFMPEG_ARGS[*]})"
DISPLAY=${DISPLAY:-:0} build_ffmpeg_cmd out.mkv 100 100 0 0 usb "" libx264
[[ " ${FFMPEG_ARGS[*]} " == *" -f pulse -thread_queue_size 4096 -isync 0 -i default "* ]] ||
    fail "usb mode without a mixer source must record the Pulse default"

# Every input needs its own -thread_queue_size: a full default-size (8
# packet) queue on ANY input blocks the muxer and makes x11grab drop
# frames at the source (T170: takes recorded at ~13fps effective).
DISPLAY=${DISPLAY:-:0} build_ffmpeg_cmd out.mkv 100 100 0 0 both sink.monitor libx264
tqs_count=$(printf '%s\n' "${FFMPEG_ARGS[@]}" | grep -cx -- '-thread_queue_size') || tqs_count=0
input_count=$(printf '%s\n' "${FFMPEG_ARGS[@]}" | grep -cx -- '-i') || input_count=0
[[ $input_count == 3 ]] || fail "both mode: expected 3 inputs, got $input_count"
[[ $tqs_count == "$input_count" ]] ||
    fail "expected -thread_queue_size on all $input_count inputs, found $tqs_count"

# 0d. check_mixer_source: a known name passes, a typo aborts (it would
#     record silence for the whole take), and a broken pactl only warns.
mkdir -p "$TMPDIR/fakepactl"
printf '#!/usr/bin/env bash\nprintf "1\\tgood_source\\tmodule\\n2\\tother_source\\tmodule\\n"\n' \
    > "$TMPDIR/fakepactl/pactl"
chmod +x "$TMPDIR/fakepactl/pactl"
PATH="$TMPDIR/fakepactl:$PATH" check_mixer_source good_source >/dev/null ||
    fail "check_mixer_source rejected a listed source"
if PATH="$TMPDIR/fakepactl:$PATH" check_mixer_source no_such_source >/dev/null 2>&1; then
    fail "check_mixer_source accepted an unknown source"
fi
printf '#!/usr/bin/env bash\nexit 1\n' > "$TMPDIR/fakepactl/pactl"
PATH="$TMPDIR/fakepactl:$PATH" check_mixer_source anything >/dev/null 2>&1 ||
    fail "check_mixer_source must not abort when pactl itself fails"
echo "mixer-source: build_ffmpeg_cmd + check_mixer_source OK"

# 0e. detect_mixer_source + resolve_mixer_source: the config-file default
#     path (Behringer pattern). Fake pactl lists a webcam, a sink monitor
#     whose name would match the pattern, and the Behringer line-in.
cat > "$TMPDIR/fakepactl/pactl" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' \
    $'1\talsa_input.usb-C922_Pro_Stream_Webcam-02.analog-stereo\tmodule' \
    $'2\talsa_output.usb-Burr-Brown_from_TI_USB_Audio_CODEC-00.analog-stereo.monitor\tmodule' \
    $'3\talsa_input.usb-Burr-Brown_from_TI_USB_Audio_CODEC-00.analog-stereo-input\tmodule'
EOF
chmod +x "$TMPDIR/fakepactl/pactl"

got=$(PATH="$TMPDIR/fakepactl:$PATH" detect_mixer_source 'Burr-Brown|USB_Audio_CODEC') ||
    fail "detect_mixer_source found no Behringer in the fake source list"
[[ $got == alsa_input.usb-Burr-Brown_from_TI_USB_Audio_CODEC-00.analog-stereo-input ]] ||
    fail "detect_mixer_source picked '$got' (must skip .monitor and the webcam)"
if got=$(PATH="$TMPDIR/fakepactl:$PATH" detect_mixer_source 'No_Such_Device'); then
    fail "detect_mixer_source matched a nonexistent pattern (got '$got')"
fi

# The shipped conf must resolve to the Behringer against the fake list.
got=$(PATH="$TMPDIR/fakepactl:$PATH" resolve_mixer_source "$HERE/perform.conf") ||
    fail "resolve_mixer_source failed on the shipped perform.conf"
[[ $got == alsa_input.usb-Burr-Brown_from_TI_USB_Audio_CODEC-00.analog-stereo-input ]] ||
    fail "shipped perform.conf resolved to '$got', not the Behringer line-in"

# Device absent (pattern matches nothing): must echo NOTHING (fall back to
# the Pulse default) and warn, never abort — mixer unplugged is recordable.
printf '#!/usr/bin/env bash\nprintf "1\\tsome_other_source\\tmodule\\n"\n' \
    > "$TMPDIR/fakepactl/pactl"
got=$(PATH="$TMPDIR/fakepactl:$PATH" resolve_mixer_source "$HERE/perform.conf" 2>"$TMPDIR/resolve.err") ||
    fail "resolve_mixer_source aborted when the pattern matched nothing"
[[ -z $got ]] || fail "absent device must fall back to default, got '$got'"
grep -q "falling back to the Pulse default" "$TMPDIR/resolve.err" ||
    fail "absent-device fallback did not warn"

# Exact MIXER_SOURCE in the conf: present -> chosen; absent -> fallback.
printf 'MIXER_SOURCE=some_other_source\n' > "$TMPDIR/exact.conf"
got=$(PATH="$TMPDIR/fakepactl:$PATH" resolve_mixer_source "$TMPDIR/exact.conf") ||
    fail "resolve_mixer_source failed on an exact MIXER_SOURCE conf"
[[ $got == some_other_source ]] || fail "exact MIXER_SOURCE ignored (got '$got')"
printf 'MIXER_SOURCE=unplugged_device\n' > "$TMPDIR/exact.conf"
got=$(PATH="$TMPDIR/fakepactl:$PATH" resolve_mixer_source "$TMPDIR/exact.conf" 2>/dev/null) ||
    fail "resolve_mixer_source aborted on an absent MIXER_SOURCE"
[[ -z $got ]] || fail "absent MIXER_SOURCE must fall back to default, got '$got'"

# No conf file at all: silently defer to the Pulse default source.
got=$(resolve_mixer_source "$TMPDIR/no_such.conf" 2>&1) ||
    fail "resolve_mixer_source failed with no conf file"
[[ -z $got ]] || fail "missing conf must yield the Pulse default, got '$got'"
echo "mixer-source: detect/resolve via perform.conf OK"

# 0f. capture_health_stats / report_capture_health against synthetic
#     fixtures with KNOWN timing: a clean constant-30fps clip must read
#     ~30fps with zero gaps and no warning; a clip with frames 30..89
#     dropped (pts passthrough keeps the original clock, leaving one ~2s
#     hole) must be flagged — this is the reference shape of the T170
#     droppy takes (perform_20260925_200909.mkv: 13fps effective).
CLEAN_MKV="$TMPDIR/health_clean.mkv"
DROPPY_MKV="$TMPDIR/health_droppy.mkv"
ffmpeg -hide_banner -loglevel error -f lavfi -i testsrc=r=30:s=64x64:d=2 \
    -c:v libx264 -preset ultrafast "$CLEAN_MKV" </dev/null ||
    fail "could not build the clean health fixture"
ffmpeg -hide_banner -loglevel error -f lavfi -i testsrc=r=30:s=64x64:d=4 \
    -vf "select='lt(n,30)+gte(n,90)'" -fps_mode passthrough \
    -c:v libx264 -preset ultrafast "$DROPPY_MKV" </dev/null ||
    fail "could not build the droppy health fixture"

stats=$(capture_health_stats "$CLEAN_MKV") ||
    fail "capture_health_stats failed on the clean fixture"
IFS=$'\t' read -r frames efps gaps maxgap <<<"$stats"
[[ $frames == 60 ]] || fail "clean fixture: expected 60 frames, got $frames"
[[ $gaps == 0 ]] || fail "clean fixture: expected 0 gaps >100ms, got $gaps"
awk -v e="$efps" 'BEGIN { exit !(e >= 28 && e <= 32) }' ||
    fail "clean fixture: effective fps $efps not ~30"

stats=$(capture_health_stats "$DROPPY_MKV") ||
    fail "capture_health_stats failed on the droppy fixture"
IFS=$'\t' read -r frames efps gaps maxgap <<<"$stats"
[[ $frames == 60 ]] || fail "droppy fixture: expected 60 kept frames, got $frames"
[[ $gaps == 1 ]] || fail "droppy fixture: expected exactly 1 gap >100ms, got $gaps"
awk -v g="$maxgap" 'BEGIN { exit !(g >= 1900 && g <= 2200) }' ||
    fail "droppy fixture: max gap ${maxgap}ms not ~2000ms"
awk -v e="$efps" 'BEGIN { exit !(e < 20) }' ||
    fail "droppy fixture: effective fps $efps should be well under nominal"

report=$(report_capture_health "$CLEAN_MKV")
grep -q "Capture health: 60 frames" <<<"$report" ||
    fail "clean fixture report missing the health line: $report"
grep -q "WARNING" <<<"$report" &&
    fail "clean fixture report must not warn: $report"
report=$(report_capture_health "$DROPPY_MKV")
grep -q "WARNING: capture dropped frames" <<<"$report" ||
    fail "droppy fixture report did not warn: $report"
report=$(report_capture_health "$TMPDIR/no_such_file.mkv") ||
    fail "report_capture_health must not fail on an unreadable file"
grep -q "Capture health: unavailable" <<<"$report" ||
    fail "unreadable file must report health as unavailable: $report"
echo "capture health: clean/droppy/unreadable fixtures OK"

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

# 2. Record ~8 seconds in --audio both mode using the exact command
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
sleep 8
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

# Exercise the live multi-input path, not just synthetic health fixtures:
# a valid MKV can still have the T175 repeating capture stalls.
stats=$(capture_health_stats "$out") || fail "live capture health unavailable"
IFS=$'\t' read -r frames efps gaps maxgap <<<"$stats"
awk -v e="$efps" 'BEGIN { exit !(e >= 27) }' ||
    fail "live $mode capture: ${efps}fps <27 ($frames frames, $gaps gaps, max ${maxgap}ms)"
echo "Live capture health: ${efps}fps, $gaps gaps >100ms, max ${maxgap}ms"

echo "PASS: ${w}x${h} capture ($encoder), 1 video + $audio_count audio, duration ${duration}s"

###############################################################################
# 3m. Marker timing, end to end with the REAL ShowSync: two distinct tones
#     play through a private null sink while ffmpeg records that sink's
#     monitor (the exact perform.sh capture command). The sidecar's
#     song_start t_rec values must land on the audible tone onsets in the
#     recording within 150ms (the beat-snapping budget is ~100ms; the
#     margin absorbs silencedetect's window). This is the only check that
#     ties the whole chain together: rec_epoch stamping, the env handoff,
#     and ShowSync's position-poll boundary math against real audio.
###############################################################################

MARKER_PYTHON=${PERFORM_PYTHON:-"$REPO_ROOT/venv/bin/python"}
SHOWSYNC_RUN_PID=""
NULL_SINK_MODULE=""
if [[ -x $MARKER_PYTHON ]] && "$MARKER_PYTHON" -c 'import PySide6, sounddevice' \
        2>/dev/null && pactl info >/dev/null 2>&1; then
    NULL_SINK_MODULE=$(pactl load-module module-null-sink sink_name=perform_marker_test \
        sink_properties=device.description=perform_marker_test) ||
        fail "marker timing: could not load a null sink"
    # A silent 2s lead-in makes tone A rise out of RECORDED silence (the
    # playback stream opens only ~0.25s before the first song — too little
    # for silencedetect). Tone A is 1.2s of 440Hz at 120bpm, bar-quantized
    # to a 2s boundary, so tone B (880Hz, with a tempo ramp to exercise
    # serialization) becomes audible exactly 2.0s after tone A.
    ffmpeg -hide_banner -loglevel error -f lavfi \
        -i "anullsrc=r=44100:cl=stereo:d=2" "$TMPDIR/marker_lead.wav" </dev/null ||
        fail "marker timing: could not build the lead-in"
    ffmpeg -hide_banner -loglevel error -f lavfi -i "sine=frequency=440:duration=1.2" \
        -af volume=0.8 "$TMPDIR/marker_song1.wav" </dev/null ||
        fail "marker timing: could not build tone 1"
    ffmpeg -hide_banner -loglevel error -f lavfi -i "sine=frequency=880:duration=2" \
        -af volume=0.8 "$TMPDIR/marker_song2.wav" </dev/null ||
        fail "marker timing: could not build tone 2"
    cat > "$TMPDIR/marker_set.yaml" <<EOF
title: "Marker timing"
audio_root: .
songs:
  - name: "Lead-in"
    file: marker_lead.wav
    bpm: 120
  - name: "Tone A"
    file: marker_song1.wav
    bpm: 120
  - name: "Tone B"
    file: marker_song2.wav
    bpm: 120
    tempo:
      - at: 1
        bpm: 140
        ramp: 0.5
EOF
    out="$TMPDIR/marker_take.mkv"
    markers="${out%.mkv}.markers"
    build_ffmpeg_cmd "$out" "$w" "$h" "$x" "$y" system perform_marker_test.monitor "$encoder"
    rec_epoch=$(date +%s.%N)
    "${FFMPEG_ARGS[@]}" </dev/null 2>"$out.log" &
    FFMPEG_PID=$!
    sleep 1
    kill -0 "$FFMPEG_PID" 2>/dev/null ||
        { cat "$out.log" >&2; fail "marker timing: capture ffmpeg died"; }
    marker_append recording_start "\"video\":$(json_str "$out"),\"mode\":\"showsync\",\"audio\":\"system\",\"set_file\":$(json_str "$TMPDIR/marker_set.yaml")" "$rec_epoch"
    # PIPEWIRE_NODE targets the null sink through PortAudio's ALSA->pipewire
    # route (PULSE_SINK covers a pulse-backend PortAudio); nothing reaches
    # the real speakers. XDG_CONFIG_HOME keeps this run's QSettings
    # (last-setlist memory, window placement) out of the user's real config.
    PIPEWIRE_NODE=perform_marker_test PULSE_SINK=perform_marker_test \
        XDG_CONFIG_HOME="$TMPDIR/xdg" \
        SHOWSYNC_MARKERS="$markers" SHOWSYNC_MARKERS_EPOCH="$rec_epoch" \
        "$MARKER_PYTHON" "$REPO_ROOT/showsync/main.py" "$TMPDIR/marker_set.yaml" \
        --headless --autostart 0 >"$TMPDIR/marker_showsync.log" 2>&1 &
    SHOWSYNC_RUN_PID=$!
    # The 4s set plus startup should finish well inside 60s; the projector
    # window opens on the Xvfb display, never the real screen.
    for _ in {1..600}; do
        kill -0 "$SHOWSYNC_RUN_PID" 2>/dev/null || break
        sleep 0.1
    done
    if kill -0 "$SHOWSYNC_RUN_PID" 2>/dev/null; then
        kill -TERM "$SHOWSYNC_RUN_PID" 2>/dev/null || true
        cat "$TMPDIR/marker_showsync.log" >&2
        fail "marker timing: ShowSync did not finish its 4s set in 60s"
    fi
    wait "$SHOWSYNC_RUN_PID" ||
        { cat "$TMPDIR/marker_showsync.log" >&2
          fail "marker timing: ShowSync exited nonzero"; }
    SHOWSYNC_RUN_PID=""
    sleep 0.5   # let the monitor capture drain past the final tone
    marker_append recording_stop
    kill -INT "$FFMPEG_PID"
    for _ in {1..100}; do
        kill -0 "$FFMPEG_PID" 2>/dev/null || break
        sleep 0.1
    done
    kill -0 "$FFMPEG_PID" 2>/dev/null && fail "marker timing: ffmpeg hung on SIGINT"
    wait "$FFMPEG_PID" 2>/dev/null || true
    FFMPEG_PID=""
    pactl unload-module "$NULL_SINK_MODULE" 2>/dev/null || true
    NULL_SINK_MODULE=""

    # Audible onsets: each tone rises out of silence, so silencedetect's
    # silence_end timestamps are the ground truth the markers must match.
    onsets=$(ffmpeg -hide_banner -i "$out" -map 0:a:0 \
                 -af silencedetect=n=-40dB:d=0.3 -f null - </dev/null 2>&1 |
             sed -n 's/.*silence_end: \([0-9.]*\).*/\1/p')
    [[ -n $onsets ]] || fail "marker timing: no tone onsets found in the recording"
    python3 - "$markers" <<EOF || fail "marker timing: markers do not match the audio"
import json, sys
records = [json.loads(line) for line in open(sys.argv[1])]
events = [r['event'] for r in records]
onsets = [float(v) for v in """$onsets""".split()]
assert events[0] == 'recording_start', events
assert 'set_start' in events and 'set_end' in events, events
assert events[-1] == 'recording_stop', events
starts = [r for r in records if r['event'] == 'song_start']
assert [s['name'] for s in starts] == ['Lead-in', 'Tone A', 'Tone B'], starts
assert starts[2]['tempo'] == [{'at': 1, 'bpm': 140, 'ramp': 0.5}], starts[2]
gap = starts[2]['t_rec'] - starts[1]['t_rec']
assert abs(gap - 2.0) < 0.05, f'song gap {gap:.3f}s, expected 2.0s (bar-quantized)'
# The first two onsets are the tones; stream teardown can add a final blip.
assert len(onsets) >= 2, f'expected 2 tone onsets, silencedetect found {onsets}'
deltas = [m['t_rec'] - onset for m, onset in zip(starts[1:], onsets[:2])]
print(f'marker-vs-audio deltas: {[f"{d*1000:+.0f}ms" for d in deltas]}')
assert all(abs(d) <= 0.15 for d in deltas), f'marker/audio offsets too large: {deltas}'
EOF
    echo "marker timing: song_start markers match audible onsets (<=150ms)"
else
    echo "NOTE: marker timing skipped (needs $MARKER_PYTHON with PySide6+sounddevice and pactl)"
fi

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
# The cleanup-time midi_log_to_mid.py conversion is also intercepted (it runs
# under the same PERFORM_PYTHON): produce the output file, and keep it out of
# apps.log so the app-launch assertions stay exact.
case ${1:-} in
    *midi_log_to_mid*)
        printf 'convert %s -> %s\n' "$2" "$3" >> "$PERFORM_OUTDIR/convert.log"
        echo stub-mid > "$3"
        exit 0
        ;;
esac
printf '%s\n' "$*" >> "$PERFORM_OUTDIR/apps.log"
if [[ -n ${SHOWSYNC_MARKERS:-} ]]; then
    printf 'SHOWSYNC_MARKERS=%s SHOWSYNC_MARKERS_EPOCH=%s\n' \
        "$SHOWSYNC_MARKERS" "${SHOWSYNC_MARKERS_EPOCH:-}" >> "$PERFORM_OUTDIR/env.log"
fi
case ${1:-} in
    *keyframes*)
        # Like real Keyframes with KEYFRAMES_MIDI_LOG set: a log_open
        # reference line at open, then per-event appends.
        if [[ -n ${KEYFRAMES_MIDI_LOG:-} ]]; then
            printf 'KEYFRAMES_MIDI_LOG=%s\n' "$KEYFRAMES_MIDI_LOG" \
                >> "$PERFORM_OUTDIR/env.log"
            epoch=$(date +%s.%N)
            printf '{"event": "log_open", "epoch": %s, "monotonic": 1.0}\n' \
                "$epoch" >> "$KEYFRAMES_MIDI_LOG"
            printf '{"epoch": %s, "monotonic": 1.5, "port": "stub", "type": "note_on", "channel": 0, "note": 40, "velocity": 100, "mapped": true}\n' \
                "$epoch" >> "$KEYFRAMES_MIDI_LOG"
        fi
        exec sleep "${STUB_KEYFRAMES_SLEEP:-300}"
        ;;
    *)           exec sleep 300 ;;
esac
EOF
chmod +x "$STUB"

RUN_PID=""
DUMMY_FFMPEG=""
PERFORM_ENTRY="$HERE/perform.sh"
PERFORM_ARGS=(--audio usb)

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
        PERFORM_VIDEO_ENCODER=libx264 PERFORM_CONF="$TMPDIR/lifecycle-no.conf" \
        python3 -c 'import signal, os, sys
signal.signal(signal.SIGINT, signal.SIG_DFL)
os.execvp(sys.argv[1], sys.argv[1:])' \
        bash "$PERFORM_ENTRY" "${PERFORM_ARGS[@]}" >"$outdir/run.log" 2>&1 &
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

# A take is only good if ffmpeg finalized it: 1 video + expected audio count
# and a numeric nonzero container duration — an aborted ffmpeg (no mkv
# trailer) reports duration N/A.
assert_valid_mkv() {
    local outdir=$1 label=$2 file streams video_count audio_count duration
    local expected_audio=${3:-1}
    file=$(compgen -G "$outdir/perform_*.mkv" | head -n1) ||
        fail "$label: no recording file in $outdir"
    [[ -s $file ]] || fail "$label: recording is empty"
    streams=$(ffprobe -v error -show_entries stream=codec_type -of csv=p=0 "$file") ||
        fail "$label: ffprobe cannot read $file"
    video_count=$(grep -c '^video$' <<<"$streams" || true)
    audio_count=$(grep -c '^audio$' <<<"$streams" || true)
    [[ $video_count == 1 ]] || fail "$label: expected 1 video stream, got $video_count"
    [[ $audio_count == "$expected_audio" ]] ||
        fail "$label: expected $expected_audio audio stream(s), got $audio_count"
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
grep -q "Capture health: [0-9]* frames" "$OUT_NORMAL/run.log" ||
    { cat "$OUT_NORMAL/run.log" >&2; fail "normal run summary lacks the capture-health line"; }
file_gone "$OUT_NORMAL/.perform.lock" || fail "normal run left the lock behind"
assert_valid_mkv "$OUT_NORMAL" "normal+stale-lock"
grep -q '/showsync/main.py .*--midi-transport' "$OUT_NORMAL/apps.log" ||
    fail "normal mode did not launch ShowSync with MIDI transport"

# 4a-markers. Every take gets a <take>.markers sidecar: recording_start
#     (with video path, mode, set file) and recording_stop, valid JSON
#     Lines with increasing t_rec — and ShowSync must have been launched
#     with SHOWSYNC_MARKERS pointing at that same sidecar plus a numeric
#     recording epoch, so its song markers share the take's t_rec timeline.
markers_file=$(compgen -G "$OUT_NORMAL/perform_*.markers" | head -n1) ||
    fail "markers: no .markers sidecar in $OUT_NORMAL"
grep -q "Take markers: .*\.markers" "$OUT_NORMAL/run.log" ||
    fail "markers: summary lacks the Take markers line"
python3 - "$markers_file" <<'EOF' || fail "markers: sidecar content invalid"
import json, sys
records = [json.loads(line) for line in open(sys.argv[1])]
events = [r['event'] for r in records]
assert events[0] == 'recording_start', events
assert events[-1] == 'recording_stop', events
start, stop = records[0], records[-1]
assert start['mode'] == 'showsync' and start['audio'] == 'usb', start
assert start['video'].endswith('.mkv'), start
assert abs(start['t_rec']) < 0.2, start
assert stop['t_rec'] > start['t_rec'], (start, stop)
assert all(isinstance(r['epoch'], float) for r in records)
EOF
grep -q "SHOWSYNC_MARKERS=$markers_file SHOWSYNC_MARKERS_EPOCH=[0-9]" \
    "$OUT_NORMAL/env.log" ||
    fail "markers: ShowSync was not given the sidecar + epoch env (env.log: $(cat "$OUT_NORMAL/env.log" 2>/dev/null))"
echo "take markers: sidecar + ShowSync env OK"

# 4a-midilog. Every take gets a <take>.midi.jsonl sidecar: Keyframes is
#     launched with KEYFRAMES_MIDI_LOG naming it, it opens with a log_open
#     reference line (epoch + monotonic) followed by events, and cleanup
#     derives <take>.mid from it via midi_log_to_mid.py --t0 <rec epoch>.
midi_log_file=$(compgen -G "$OUT_NORMAL/perform_*.midi.jsonl" | head -n1) ||
    fail "midilog: no .midi.jsonl sidecar in $OUT_NORMAL"
grep -q "KEYFRAMES_MIDI_LOG=$midi_log_file" "$OUT_NORMAL/env.log" ||
    fail "midilog: Keyframes was not given KEYFRAMES_MIDI_LOG (env.log: $(cat "$OUT_NORMAL/env.log" 2>/dev/null))"
python3 - "$midi_log_file" <<'EOF' || fail "midilog: sidecar content invalid"
import json, sys
records = [json.loads(line) for line in open(sys.argv[1])]
ref = records[0]
assert ref['event'] == 'log_open', ref
assert isinstance(ref['epoch'], float) and isinstance(ref['monotonic'], float), ref
events = records[1:]
assert len(events) >= 1, records
assert any(r.get('type') == 'note_on' for r in events), events
for r in events:
    assert isinstance(r['epoch'], float) and 'port' in r and 'type' in r, r
EOF
grep -q "MIDI log: .*\.midi\.jsonl" "$OUT_NORMAL/run.log" ||
    fail "midilog: summary lacks the MIDI log line"
mid_file=$(compgen -G "$OUT_NORMAL/perform_*.mid" | head -n1) ||
    fail "midilog: no .mid derived from the sidecar"
[[ -s $mid_file ]] || fail "midilog: derived .mid is empty"
grep -q "MIDI file: .*\.mid" "$OUT_NORMAL/run.log" ||
    fail "midilog: summary lacks the MIDI file line"
grep -Eq "convert $midi_log_file -> .*\.mid" "$OUT_NORMAL/convert.log" ||
    fail "midilog: converter was not invoked on the sidecar"
compgen -G "$OUT_NORMAL/*.mid.log" >/dev/null &&
    fail "midilog: successful conversion left its log behind"
echo "midi log: sidecar + env + .mid derivative OK"

# 4a-post. The shareable post-take outputs must exist by default with the
#          expected streams (usb mode: mp4 = 1 video + 1 aac audio; mp3 =
#          1 mp3 audio, no video) and be reported with paths in the log.
share=$(compgen -G "$OUT_NORMAL/perform_*_share.mp4" | head -n1) ||
    fail "post: no _share.mp4 produced (run.log: $(cat "$OUT_NORMAL/run.log"))"
[[ -s $share ]] || fail "post: _share.mp4 is empty"
streams=$(ffprobe -v error -show_entries stream=codec_type,codec_name -of csv=p=0 "$share") ||
    fail "post: ffprobe cannot read $share"
grep -qx 'h264,video' <<<"$streams" || fail "post: _share.mp4 video is not h264: $streams"
[[ $(grep -cx 'aac,audio' <<<"$streams") == 1 ]] ||
    fail "post: _share.mp4 must carry 1 aac audio stream (usb mode): $streams"
mp3=$(compgen -G "$OUT_NORMAL/perform_*.mp3" | head -n1) || fail "post: no .mp3 produced"
[[ -s $mp3 ]] || fail "post: .mp3 is empty"
streams=$(ffprobe -v error -show_entries stream=codec_type,codec_name -of csv=p=0 "$mp3") ||
    fail "post: ffprobe cannot read $mp3"
[[ $(grep -cx 'mp3.*,audio' <<<"$streams" || true) == 1 && $(grep -c ',video$' <<<"$streams" || true) == 0 ]] ||
    fail "post: .mp3 must be exactly one mp3 audio stream: $streams"
grep -q "Share MP4: .*_share\.mp4" "$OUT_NORMAL/run.log" ||
    fail "post: summary lacks the Share MP4 line"
grep -q "Mixer MP3: .*\.mp3" "$OUT_NORMAL/run.log" ||
    fail "post: summary lacks the Mixer MP3 line"
compgen -G "$OUT_NORMAL/*_share.mp4.log" >/dev/null &&
    fail "post: successful share encode left its log behind"
echo "post-take outputs: _share.mp4 + .mp3 streams and summary lines OK"

# 4a-keyframes. The wrapper must launch only Keyframes and finalize capture
# when it exits (Esc), using USB by default. Explicit audio works before or
# after --keyframes-only, in either --audio syntax. Keep postprocessing on
# for the default wrapper case to verify its full one-command output path.
for audio in usb both system; do
    OUT_KEYFRAMES="$TMPDIR/run_keyframes_$audio"
    mkdir -p "$OUT_KEYFRAMES"
    expected_audio=1
    case $audio in
        usb)
            PERFORM_ENTRY="$HERE/keyframes-take.sh"
            PERFORM_ARGS=()
            ;;
        both)
            PERFORM_ENTRY="$HERE/perform.sh"
            PERFORM_ARGS=(--audio both --keyframes-only --no-postprocess)
            # There may be no sink monitor on a minimal test machine.
            if system_audio_source >/dev/null; then expected_audio=2; fi
            ;;
        system)
            system_audio_source >/dev/null || continue
            PERFORM_ENTRY="$HERE/keyframes-take.sh"
            PERFORM_ARGS=(--audio=system --no-postprocess)
            ;;
    esac
    launch_perform "$OUT_KEYFRAMES" STUB_KEYFRAMES_SLEEP=3
    wait_for 300 not_running "$RUN_PID" ||
        { cat "$OUT_KEYFRAMES/run.log" >&2; fail "Keyframes-only $audio run did not finish"; }
    wait "$RUN_PID" ||
        { cat "$OUT_KEYFRAMES/run.log" >&2; fail "Keyframes-only $audio run exited nonzero"; }
    RUN_PID=""
    [[ $(cat "$OUT_KEYFRAMES/apps.log") == "$REPO_ROOT/keyframes/main.py" ]] ||
        fail "Keyframes-only $audio launched unexpected apps/arguments: $(cat "$OUT_KEYFRAMES/apps.log")"
    if grep -Eq 'Editor screen:|ShowSync editor|Starting ShowSync' "$OUT_KEYFRAMES/run.log"; then
        fail "Keyframes-only $audio still ran ShowSync startup/placement logic"
    fi
    recorded_audio=$audio
    [[ $audio == both && $expected_audio == 1 ]] && recorded_audio=usb
    grep -q "(audio: $recorded_audio)" "$OUT_KEYFRAMES/run.log" ||
        fail "Keyframes-only did not select expected audio: $recorded_audio"
    file_gone "$OUT_KEYFRAMES/.perform.lock" || fail "Keyframes-only left the capture lock"
    assert_valid_mkv "$OUT_KEYFRAMES" "Keyframes-only $audio" "$expected_audio"
    # Markers exist without ShowSync too: recording start/stop only, and no
    # marker env leaks to Keyframes (nothing would consume it).
    markers_file=$(compgen -G "$OUT_KEYFRAMES/perform_*.markers" | head -n1) ||
        fail "Keyframes-only $audio: no .markers sidecar"
    grep -q '"event":"recording_start".*"mode":"keyframes-only"' "$markers_file" ||
        fail "Keyframes-only $audio: sidecar lacks a keyframes-only recording_start"
    grep -q '"event":"recording_stop"' "$markers_file" ||
        fail "Keyframes-only $audio: sidecar lacks recording_stop"
    grep -q 'SHOWSYNC_MARKERS' "$OUT_KEYFRAMES/env.log" 2>/dev/null &&
        fail "Keyframes-only $audio exported SHOWSYNC_MARKERS to its apps"
    # The MIDI event log IS wanted here: direct-MIDI takes are exactly
    # where the sidecar matters most.
    grep -q "KEYFRAMES_MIDI_LOG=.*\.midi\.jsonl" "$OUT_KEYFRAMES/env.log" ||
        fail "Keyframes-only $audio: Keyframes was not given KEYFRAMES_MIDI_LOG"
    grep -q 'Capture health: [0-9]* frames' "$OUT_KEYFRAMES/run.log" ||
        fail "Keyframes-only summary lacks capture health"
    if [[ $audio == usb ]]; then
        grep -q 'Share MP4: .*_share\.mp4' "$OUT_KEYFRAMES/run.log" ||
            fail "Keyframes-only did not produce the share MP4"
        grep -q 'Mixer MP3: .*\.mp3' "$OUT_KEYFRAMES/run.log" ||
            fail "Keyframes-only did not produce the mixer MP3"
    fi
done
PERFORM_ENTRY="$HERE/perform.sh"
PERFORM_ARGS=(--audio usb)
echo "Keyframes-only: wrapper, launch isolation, default/explicit audio and postprocessing OK"

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

# 4e. Post-processing opt-out: PERFORM_NO_POSTPROCESS=1 must skip both
#     derivatives (and say so) while the master take is still produced.
OUT_NOPOST="$TMPDIR/run_nopost"
mkdir -p "$OUT_NOPOST"
launch_perform "$OUT_NOPOST" STUB_KEYFRAMES_SLEEP=3 PERFORM_NO_POSTPROCESS=1
wait_for 300 not_running "$RUN_PID" ||
    { cat "$OUT_NOPOST/run.log" >&2; fail "no-postprocess run did not exit within 30s"; }
wait "$RUN_PID" || { cat "$OUT_NOPOST/run.log" >&2; fail "no-postprocess run exited nonzero"; }
RUN_PID=""
assert_valid_mkv "$OUT_NOPOST" "no-postprocess"
compgen -G "$OUT_NOPOST/*_share.mp4" >/dev/null &&
    fail "PERFORM_NO_POSTPROCESS=1 still produced a _share.mp4"
compgen -G "$OUT_NOPOST/*.mp3" >/dev/null &&
    fail "PERFORM_NO_POSTPROCESS=1 still produced an .mp3"
grep -q "Post-processing skipped" "$OUT_NOPOST/run.log" ||
    fail "no-postprocess run did not report the skip"
echo "post-processing opt-out: OK"

# 4f. Post-processing failure must never harm the master: a fake ffmpeg
#     that leaves a partial output and exits 1 stands in for a post-encode
#     crash. The master mkv must remain valid, both warnings must print,
#     the partial derivatives must be deleted, and the run still exits 0.
FAILING_FFMPEG="$TMPDIR/failing-ffmpeg"
cat > "$FAILING_FFMPEG" <<'EOF'
#!/usr/bin/env bash
# Simulate a post-process crash that leaves a partial output file behind.
for last; do :; done
touch "$last"
exit 1
EOF
chmod +x "$FAILING_FFMPEG"
OUT_POSTFAIL="$TMPDIR/run_postfail"
mkdir -p "$OUT_POSTFAIL"
launch_perform "$OUT_POSTFAIL" STUB_KEYFRAMES_SLEEP=3 \
    PERFORM_POSTPROCESS_FFMPEG="$FAILING_FFMPEG"
wait_for 300 not_running "$RUN_PID" ||
    { cat "$OUT_POSTFAIL/run.log" >&2; fail "post-fail run did not exit within 30s"; }
wait "$RUN_PID" || { cat "$OUT_POSTFAIL/run.log" >&2; fail "post-fail run exited nonzero"; }
RUN_PID=""
assert_valid_mkv "$OUT_POSTFAIL" "post-fail (master survives)"
grep -q "WARNING: share mp4 failed" "$OUT_POSTFAIL/run.log" ||
    { cat "$OUT_POSTFAIL/run.log" >&2; fail "post-fail run lacks the share mp4 warning"; }
grep -q "WARNING: mixer mp3 failed" "$OUT_POSTFAIL/run.log" ||
    fail "post-fail run lacks the mixer mp3 warning"
compgen -G "$OUT_POSTFAIL/*_share.mp4" >/dev/null &&
    fail "failed post-processing left a partial _share.mp4 behind"
compgen -G "$OUT_POSTFAIL/*.mp3" >/dev/null &&
    fail "failed post-processing left a partial .mp3 behind"
grep -q "Capture health: [0-9]* frames" "$OUT_POSTFAIL/run.log" ||
    fail "post-fail run lost the capture-health line"
echo "post-processing failure: master survives, warnings printed, partials removed"

echo "PASS: main() lifecycle — normal/stale-lock + post outputs, SIGKILL babysitter, double-SIGINT, live-lock refusal, postprocess opt-out + failure"
