#!/usr/bin/env bash
# perform.sh — one-command performance capture.
#
# Records the performance monitor (screen video + audio) and launches
# ShowSync and Keyframes. Recording stops cleanly when Keyframes exits (Esc)
# or on Ctrl+C.
#
# Usage: scripts/perform.sh [--audio usb|system|both] [showsync args...]
#   --audio usb     record only the Pulse default source (mixer USB feed)
#   --audio system  record only the default sink monitor (system audio,
#                   i.e. the ShowSync backing tracks)
#   --audio both    record BOTH as two separate audio tracks (default) so
#                   takes can be rebalanced later
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

set -euo pipefail

REPO_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)

usage() {
    sed -n '2,23p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
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

# Fill the global FFMPEG_ARGS array with the capture command:
#   build_ffmpeg_cmd OUT W H X Y MODE [SYSTEM_SOURCE]
# MODE is usb|system|both; SYSTEM_SOURCE is the sink monitor name (required
# for system/both). Audio tracks stay separate (titled "mixer"/"system") so
# takes can be rebalanced afterwards. Kept as a function so the smoke test
# runs the exact same invocation (scripts/perform_smoke_test.sh).
# NOTE: no -nostdin — with it, ffmpeg 7.1 catches but never acts on
# SIGINT/SIGTERM and the recording needs SIGKILL (losing the trailer).
# Callers must redirect stdin from /dev/null instead.
build_ffmpeg_cmd() {
    local out=$1 w=$2 h=$3 x=$4 y=$5 mode=$6 system_src=${7:-}
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
    FFMPEG_ARGS+=(
        -c:v libx264 -preset veryfast -crf 23 -pix_fmt yuv420p
        -c:a aac
        "$out"
    )
}

main() {
    local audio_mode="both" showsync_args=()
    while (( $# )); do
        case $1 in
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
    [[ -n ${DISPLAY:-} ]] || { echo "ERROR: DISPLAY is not set" >&2; exit 1; }

    local python="$REPO_ROOT/venv/bin/python"
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
    if [[ " ${showsync_args[*]-} " == *" --editor-screen"* ]]; then
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

    local outdir="$REPO_ROOT/recordings"
    mkdir -p "$outdir"
    local out
    out="$outdir/perform_$(date +%Y%m%d_%H%M%S).mkv"

    local ffmpeg_pid="" showsync_pid="" keyframes_pid=""

    cleanup() {
        trap - INT TERM EXIT
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
    trap cleanup INT TERM EXIT

    echo "Recording to: $out (audio: $audio_mode)"
    build_ffmpeg_cmd "$out" "$w" "$h" "$x" "$y" "$audio_mode" "$system_src"
    "${FFMPEG_ARGS[@]}" </dev/null 2>"$out.log" &
    ffmpeg_pid=$!

    # Give ffmpeg a moment to open its inputs; abort early if it died.
    sleep 1
    if ! kill -0 "$ffmpeg_pid" 2>/dev/null; then
        wait "$ffmpeg_pid" || true
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
