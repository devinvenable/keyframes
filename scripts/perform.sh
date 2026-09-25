#!/usr/bin/env bash
# perform.sh — one-command performance capture.
#
# Records the performance monitor (screen video + audio) and launches
# ShowSync and Keyframes. Recording stops cleanly when Keyframes exits (Esc)
# or on Ctrl+C.
#
# Usage: scripts/perform.sh [--audio usb|system|both] [--headless] [showsync args...]
#   --audio usb     record only the Pulse default source (mixer USB feed)
#   --audio system  record only the default sink monitor (system audio,
#                   i.e. the ShowSync backing tracks)
#   --audio both    record BOTH as two separate audio tracks (default) so
#                   takes can be rebalanced later
#   --headless      run ShowSync without the editor window (engine + projector
#                   only); skips the --editor-screen placement logic. Combine
#                   with --autostart [SECONDS] for a fully clickless take.
#   Remaining arguments are passed through to ShowSync (setlist path, etc.).
#
# Video : the first landscape monitor (same pick as Keyframes fullscreen).
# Editor: the ShowSync editor opens on a different monitor (via
#         --editor-screen) so it stays clickable under fullscreen Keyframes;
#         pass your own --editor-screen to override.
# Audio : the PipeWire/Pulse default source and/or default sink monitor —
#         re-route with `pactl set-default-source` / `set-default-sink`
#         instead of editing this script.
# Output: recordings/perform_YYYYmmdd_HHMMSS.mkv
#
# Only one capture at a time: recordings/.perform.lock holds the pid of the
# running ffmpeg; a second perform.sh refuses to start while it is alive
# (stop it with `kill -INT <pid>` — that finalizes the recording). ffmpeg
# runs in its own session with a babysitter process, so the recording is
# finalized even if this script is SIGKILLed or the terminal closes.
#
# Test hooks (used by scripts/perform_smoke_test.sh):
#   PERFORM_OUTDIR         override the recordings/ output directory
#   PERFORM_PYTHON         override the python used for ShowSync/Keyframes
#   PERFORM_VIDEO_ENCODER  skip the NVENC probe (libx264|h264_nvenc)

set -euo pipefail

REPO_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)

usage() {
    sed -n '2,32p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

# Parse `xrandr --listmonitors` and echo "WIDTH HEIGHT XOFF YOFF" for the
# first landscape (width > height) monitor, falling back to the first
# monitor listed. Mirrors choose_landscape_display() in keyframes/main.py.
detect_capture_region() {
    local line geom w h x y first=""
    while IFS= read -r line; do
        # " 0: +*DP-1 1920/480x1080/270+1080+0  DP-1"
        geom=$(awk '{print $3}' <<<"$line")
        if [[ $geom =~ ^([0-9]+)/[0-9]+x([0-9]+)/[0-9]+\+(-?[0-9]+)\+(-?[0-9]+)$ ]]; then
            w=${BASH_REMATCH[1]} h=${BASH_REMATCH[2]}
            x=${BASH_REMATCH[3]} y=${BASH_REMATCH[4]}
            [[ -z $first ]] && first="$w $h $x $y"
            if (( w > h )); then
                echo "$w $h $x $y"
                return 0
            fi
        fi
    done < <(xrandr --listmonitors | tail -n +2)
    if [[ -n $first ]]; then
        echo "$first"
        return 0
    fi
    return 1
}

# Read `xrandr --listmonitors` body (already stripped of the header line) on
# stdin and echo the NAME of a monitor other than the capture one, which is
# identified by its +X+Y offset (args: CAP_X CAP_Y). Prefers another
# landscape monitor, falls back to any other; returns 1 when the capture
# monitor is the only one connected. The name matches Qt's QScreen.name(),
# so it can be passed straight to ShowSync --editor-screen.
pick_editor_screen() {
    local cap_x=$1 cap_y=$2 line name geom w h x y fallback=""
    while IFS= read -r line; do
        geom=$(awk '{print $3}' <<<"$line")
        name=$(awk '{print $NF}' <<<"$line")
        if [[ $geom =~ ^([0-9]+)/[0-9]+x([0-9]+)/[0-9]+\+(-?[0-9]+)\+(-?[0-9]+)$ ]]; then
            w=${BASH_REMATCH[1]} h=${BASH_REMATCH[2]}
            x=${BASH_REMATCH[3]} y=${BASH_REMATCH[4]}
            (( x == cap_x && y == cap_y )) && continue
            if (( w > h )); then
                echo "$name"
                return 0
            fi
            [[ -z $fallback ]] && fallback=$name
        fi
    done
    if [[ -n $fallback ]]; then
        echo "$fallback"
        return 0
    fi
    return 1
}

# Warn (do not abort) when the Pulse default source is probably not the
# mixer feed — e.g. a webcam mic or a monitor-of-sink loopback.
check_default_source() {
    local src
    src=$(pactl get-default-source 2>/dev/null) || {
        echo "WARNING: could not query the Pulse default source (pactl failed)." >&2
        return 0
    }
    echo "Mixer audio source: $src"
    case $src in
        *.monitor|*[Ww]ebcam*|*[Cc]amera*|*[Cc]am_*)
            echo "WARNING: default source '$src' looks like a webcam/monitor source," >&2
            echo "         not the mixer feed. Fix with: pactl set-default-source <name>" >&2
            ;;
    esac
}

# Echo the monitor source of the default sink (system audio / ShowSync
# backing tracks). Fails if pactl can't resolve it.
system_audio_source() {
    local sink
    sink=$(pactl get-default-sink 2>/dev/null) || return 1
    [[ -n $sink ]] || return 1
    echo "$sink.monitor"
}

# Echo the video encoder to use: h264_nvenc when the GPU can actually open
# an encode session, else libx264. A listed encoder is not enough — NVENC
# can still fail at runtime (sessions exhausted, driver mismatch), so probe
# with a real 3-frame null encode. Honors PERFORM_VIDEO_ENCODER=libx264|
# h264_nvenc to skip the probe (used by the smoke test's fallback check).
detect_video_encoder() {
    case ${PERFORM_VIDEO_ENCODER:-} in
        libx264|h264_nvenc)
            echo "$PERFORM_VIDEO_ENCODER"
            return 0
            ;;
        "") ;;
        *)
            echo "ERROR: PERFORM_VIDEO_ENCODER must be libx264 or h264_nvenc" \
                 "(got '$PERFORM_VIDEO_ENCODER')" >&2
            return 1
            ;;
    esac
    if ffmpeg -hide_banner -loglevel error \
            -f lavfi -i color=c=black:s=256x256:r=30 -frames:v 3 \
            -c:v h264_nvenc -f null - </dev/null >/dev/null 2>&1; then
        echo h264_nvenc
    else
        echo libx264
    fi
}

# Refuse to stack captures. The lock file holds the pid of the ffmpeg
# started by the previous perform.sh; if that pid is still a live ffmpeg
# (comm check guards against pid reuse) we refuse to start instead of
# killing it — never silently end a take that may still be wanted. A lock
# whose pid is dead or no longer an ffmpeg is stale and removed.
check_capture_lock() {
    local lock=$1 pid="" comm=""
    [[ -e $lock ]] || return 0
    pid=$(head -n1 "$lock" 2>/dev/null) || pid=""
    if [[ $pid =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
        comm=$(cat "/proc/$pid/comm" 2>/dev/null) || comm=""
        if [[ $comm == ffmpeg ]]; then
            echo "ERROR: another perform.sh capture is already running (ffmpeg pid $pid)." >&2
            echo "       Stop it first with: kill -INT $pid   (this finalizes that recording)" >&2
            echo "       Lock file: $lock" >&2
            return 1
        fi
    fi
    echo "NOTE: removing stale capture lock $lock (pid '${pid}' is not a live ffmpeg)."
    rm -f "$lock"
}

# Start a watchdog in its own session that outlives this script. When the
# script dies by ANY path — including SIGKILL, where no trap runs — it
# SIGINTs ffmpeg so the recording is finalized, escalates to SIGKILL only
# if ffmpeg hangs, and clears the lock (only if the lock still names our
# ffmpeg, so it never deletes a newer session's lock). Sets BABYSITTER_PID.
start_babysitter() {
    local script_pid=$1 fpid=$2 lock=$3
    # shellcheck disable=SC2016  # single quotes intended: $1..$3 are bash -c args
    setsid bash -c '
        script_pid=$1 fpid=$2 lock=$3
        while kill -0 "$script_pid" 2>/dev/null; do sleep 1; done
        if kill -0 "$fpid" 2>/dev/null; then
            kill -INT "$fpid" 2>/dev/null
            for _ in $(seq 100); do
                kill -0 "$fpid" 2>/dev/null || break
                sleep 0.1
            done
            kill -0 "$fpid" 2>/dev/null && kill -KILL "$fpid" 2>/dev/null
        fi
        [[ $(head -n1 "$lock" 2>/dev/null) == "$fpid" ]] && rm -f "$lock"
        exit 0
    ' babysitter "$script_pid" "$fpid" "$lock" </dev/null >/dev/null 2>&1 &
    BABYSITTER_PID=$!
}

# Fill the global FFMPEG_ARGS array with the capture command:
#   build_ffmpeg_cmd OUT W H X Y MODE [SYSTEM_SOURCE] [ENCODER]
# MODE is usb|system|both; SYSTEM_SOURCE is the sink monitor name (required
# for system/both); ENCODER is libx264 (default) or h264_nvenc. Audio
# tracks stay separate (titled "mixer"/"system") so takes can be rebalanced
# afterwards. Kept as a function so the smoke test runs the exact same
# invocation (scripts/perform_smoke_test.sh).
# NOTE: no -nostdin — with it, ffmpeg 7.1 catches but never acts on
# SIGINT/SIGTERM and the recording needs SIGKILL (losing the trailer).
# Callers must redirect stdin from /dev/null instead.
build_ffmpeg_cmd() {
    local out=$1 w=$2 h=$3 x=$4 y=$5 mode=$6 system_src=${7:-} encoder=${8:-libx264}
    FFMPEG_ARGS=(
        ffmpeg -hide_banner -loglevel warning
        -f x11grab -framerate 30 -video_size "${w}x${h}" -i "$DISPLAY+$x,$y"
    )
    case $mode in
        usb)
            FFMPEG_ARGS+=(-f pulse -i default
                          -map 0:v -map 1:a
                          -metadata:s:a:0 title=mixer)
            ;;
        system)
            FFMPEG_ARGS+=(-f pulse -i "$system_src"
                          -map 0:v -map 1:a
                          -metadata:s:a:0 title=system)
            ;;
        both)
            FFMPEG_ARGS+=(-f pulse -i default
                          -f pulse -i "$system_src"
                          -map 0:v -map 1:a -map 2:a
                          -metadata:s:a:0 title=mixer
                          -metadata:s:a:1 title=system)
            ;;
        *)
            echo "ERROR: unknown audio mode '$mode'" >&2
            return 1
            ;;
    esac
    case $encoder in
        h264_nvenc)
            # GPU encode keeps the CPU free for Keyframes/ShowSync during a
            # live take: low-latency tune, VBR with a CRF-like quality target.
            FFMPEG_ARGS+=(-c:v h264_nvenc -preset p4 -tune ll
                          -rc vbr -cq 23 -b:v 0 -pix_fmt yuv420p)
            ;;
        libx264)
            FFMPEG_ARGS+=(-c:v libx264 -preset veryfast -crf 23 -pix_fmt yuv420p)
            ;;
        *)
            echo "ERROR: unknown video encoder '$encoder'" >&2
            return 1
            ;;
    esac
    FFMPEG_ARGS+=(
        -c:a aac
        "$out"
    )
}

main() {
    local audio_mode="both" headless=0 showsync_args=()
    while (( $# )); do
        case $1 in
            --headless)
                headless=1
                showsync_args+=(--headless)
                shift
                ;;
            --audio)
                [[ -n ${2:-} ]] || { echo "ERROR: --audio needs usb|system|both" >&2; exit 1; }
                audio_mode=$2
                shift 2
                ;;
            --audio=*)
                audio_mode=${1#--audio=}
                shift
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                showsync_args+=("$1")
                shift
                ;;
        esac
    done
    case $audio_mode in usb|system|both) ;; *)
        echo "ERROR: --audio must be usb, system or both (got '$audio_mode')" >&2
        exit 1
    esac

    command -v ffmpeg >/dev/null || { echo "ERROR: ffmpeg not found" >&2; exit 1; }
    command -v xrandr >/dev/null || { echo "ERROR: xrandr not found" >&2; exit 1; }
    command -v setsid >/dev/null || { echo "ERROR: setsid not found (util-linux)" >&2; exit 1; }
    [[ -n ${DISPLAY:-} ]] || { echo "ERROR: DISPLAY is not set" >&2; exit 1; }

    local python=${PERFORM_PYTHON:-"$REPO_ROOT/venv/bin/python"}
    [[ -x $python ]] || python=$(command -v python3)

    local region w h x y
    region=$(detect_capture_region) || {
        echo "ERROR: could not detect a monitor via xrandr --listmonitors" >&2
        exit 1
    }
    read -r w h x y <<<"$region"
    echo "Capture region: ${w}x${h}+${x}+${y} on $DISPLAY"

    # Keep the ShowSync editor off the capture monitor, where fullscreen
    # always-on-top Keyframes would cover it. Respect an explicit
    # --editor-screen in the pass-through args.
    local editor_screen=""
    if (( headless )); then
        echo "Editor screen: none (headless — projector only)"
    elif [[ " ${showsync_args[*]-} " == *" --editor-screen"* ]]; then
        echo "Editor screen: set by caller"
    elif editor_screen=$(xrandr --listmonitors | tail -n +2 |
                         pick_editor_screen "$x" "$y"); then
        echo "Editor screen: $editor_screen"
        showsync_args+=(--editor-screen "$editor_screen")
    else
        echo "NOTE: only one monitor — the ShowSync editor will open under fullscreen"
        echo "      Keyframes. Start the set via keyboard/MIDI, or press F11 in"
        echo "      Keyframes to drop it out of fullscreen first."
    fi

    # Hands-free start: the KeyStep's hardware Play/Stop drive the set.
    if [[ " ${showsync_args[*]-} " != *" --midi-transport"* ]]; then
        showsync_args+=(--midi-transport)
    fi

    local system_src=""
    if [[ $audio_mode != system ]]; then
        check_default_source
    fi
    if [[ $audio_mode != usb ]]; then
        if system_src=$(system_audio_source); then
            echo "System audio source: $system_src"
        elif [[ $audio_mode == system ]]; then
            echo "ERROR: could not resolve the default sink monitor (pactl failed)" >&2
            exit 1
        else
            echo "WARNING: could not resolve the default sink monitor —" >&2
            echo "         recording the mixer track only." >&2
            audio_mode="usb"
        fi
    fi

    local outdir=${PERFORM_OUTDIR:-"$REPO_ROOT/recordings"}
    mkdir -p "$outdir"
    # Everything cleanup() touches must be global, NOT local: the EXIT trap
    # fires after main() has returned (normal Esc path), when locals are
    # already gone and `set -u` would abort cleanup mid-shutdown.
    lockfile="$outdir/.perform.lock"
    out="$outdir/perform_$(date +%Y%m%d_%H%M%S).mkv"
    ffmpeg_pid="" showsync_pid="" keyframes_pid="" BABYSITTER_PID=""

    cleanup() {
        # Absorb repeat Ctrl+C (and TERM/HUP) while finalizing: a second
        # SIGINT reaching ffmpeg aborts without writing the mkv trailer.
        trap '' INT TERM HUP
        trap - EXIT
        # Never let a failing echo/ffprobe (e.g. EIO after the terminal
        # closed on SIGHUP) abort cleanup before ffmpeg is finalized.
        set +e
        if [[ -n $ffmpeg_pid ]] && kill -0 "$ffmpeg_pid" 2>/dev/null; then
            echo ""
            echo "Finalizing recording — please wait (Ctrl+C is ignored until it is saved)..."
        fi
        local pid
        # Stop the apps first (child PIDs only — never pkill by name).
        for pid in "$keyframes_pid" "$showsync_pid"; do
            if [[ -n $pid ]] && kill -0 "$pid" 2>/dev/null; then
                kill -TERM "$pid" 2>/dev/null || true
            fi
        done
        # SIGINT lets ffmpeg finalize the file; escalate only if it hangs.
        if [[ -n $ffmpeg_pid ]] && kill -0 "$ffmpeg_pid" 2>/dev/null; then
            kill -INT "$ffmpeg_pid" 2>/dev/null || true
            local waited=0
            while kill -0 "$ffmpeg_pid" 2>/dev/null && (( waited < 100 )); do
                sleep 0.1
                (( ++waited ))
            done
            if kill -0 "$ffmpeg_pid" 2>/dev/null; then
                echo "WARNING: ffmpeg did not stop after 10s; killing it —" >&2
                echo "         the recording may be unplayable." >&2
                kill -KILL "$ffmpeg_pid" 2>/dev/null || true
            fi
            wait "$ffmpeg_pid" 2>/dev/null || true
        fi
        for pid in "$keyframes_pid" "$showsync_pid"; do
            if [[ -n $pid ]]; then
                wait "$pid" 2>/dev/null || true
            fi
        done
        # Release the lock only if it still names our ffmpeg — never delete
        # a newer session's lock. The babysitter has nothing left to do.
        if [[ -n $ffmpeg_pid && $(head -n1 "$lockfile" 2>/dev/null) == "$ffmpeg_pid" ]]; then
            rm -f "$lockfile"
        fi
        if [[ -n $BABYSITTER_PID ]]; then
            kill "$BABYSITTER_PID" 2>/dev/null
        fi
        if [[ -f $out ]]; then
            local dur=""
            if command -v ffprobe >/dev/null; then
                dur=$(ffprobe -v error -show_entries format=duration \
                    -of csv=p=0 "$out" 2>/dev/null) || true
            fi
            echo ""
            echo "Recording saved: $out"
            [[ -n $dur ]] && echo "Duration: ${dur%.*}s"
        else
            echo "WARNING: no recording was written to $out" >&2
        fi
    }
    # HUP included: closing the terminal must still finalize the file.
    trap cleanup INT TERM HUP EXIT

    local encoder
    encoder=$(detect_video_encoder) || exit 1
    if [[ $encoder == h264_nvenc ]]; then
        echo "Video encoder: h264_nvenc (GPU)"
    else
        echo "Video encoder: libx264 (CPU — NVENC unavailable)"
    fi

    check_capture_lock "$lockfile" || exit 1

    echo "Recording to: $out (audio: $audio_mode)"
    build_ffmpeg_cmd "$out" "$w" "$h" "$x" "$y" "$audio_mode" "$system_src" "$encoder"
    # setsid: ffmpeg gets its own session/process group, so a terminal
    # Ctrl+C (delivered to the foreground group) never reaches it raw —
    # cleanup's single SIGINT is the only stop signal it ever sees — and a
    # terminal close (SIGHUP) cannot kill it mid-write.
    setsid "${FFMPEG_ARGS[@]}" </dev/null 2>"$out.log" &
    ffmpeg_pid=$!
    echo "$ffmpeg_pid" > "$lockfile"
    start_babysitter "$$" "$ffmpeg_pid" "$lockfile"

    # Give ffmpeg a moment to open its inputs; abort early if it died.
    sleep 1
    if ! kill -0 "$ffmpeg_pid" 2>/dev/null; then
        wait "$ffmpeg_pid" || true
        rm -f "$lockfile"
        ffmpeg_pid=""
        echo "ERROR: ffmpeg failed to start — see $out.log" >&2
        tail -n 5 "$out.log" >&2 || true
        exit 1
    fi

    echo "Starting ShowSync..."
    "$python" "$REPO_ROOT/showsync/main.py" ${showsync_args[@]+"${showsync_args[@]}"} &
    showsync_pid=$!

    echo "Starting Keyframes (Esc in Keyframes ends the take)..."
    "$python" "$REPO_ROOT/keyframes/main.py" &
    keyframes_pid=$!

    # Wait for Keyframes to exit (Esc) — Ctrl+C lands in the trap instead.
    wait "$keyframes_pid" || true
    keyframes_pid=""
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
    main "$@"
fi
