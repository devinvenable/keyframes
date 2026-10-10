#!/usr/bin/env bash
# live.sh — one-command LIVE performance launcher (no capture).
#
# Launches ShowSync (backing tracks + MIDI clock out) and Keyframes
# (KeyStep-triggered visuals, the always-on-top reveal layer under the
# ShowSync projector) on the REAL display for an actual show. Unlike
# scripts/perform.sh there is no ffmpeg, no recording lock, no take
# sidecars: audio goes to the house through ShowSync's output device and
# the Behringer stays input-only (the KeyStep reaches Keyframes through it).
#
# Usage: scripts/live.sh [options] [showsync args...] setlist.yaml
#   --bank NAME       Keyframes media bank (default: default)
#   --headless        run ShowSync without the editor window (projector
#                     only). Pair with --autostart [SECONDS] or rely on the
#                     default --midi-transport (KeyStep Play starts the set).
#                     NOTE: headless has no Skip/Restart controls — see the
#                     recovery notes in docs/live-show-runbook.md.
#   --no-restart      disable the crash supervisor (a crashed app stays down)
#   Remaining arguments pass through to ShowSync (setlist path, --autostart,
#   --clock-offset, --editor-screen, --midi-transport, --audio-device, ...).
#
# Behavior:
#   * --midi-transport is added for ShowSync unless the caller passed it:
#     the KeyStep's hardware Play/Stop drive the set hands-free (restored
#     working config per decision D17; supersedes the brief D15 removal).
#   * Startup order: ShowSync first (clock master; audio + MIDI open and the
#     editor, if any, appears), then fullscreen Keyframes, which pins itself
#     above normal windows. The projector raises itself over Keyframes for
#     video songs and hides after — deterministic stacking, no IPC.
#   * On Linux with a second monitor, the ShowSync editor is placed there
#     automatically (same pick as perform.sh) so it stays reachable under
#     fullscreen Keyframes. On macOS pass --editor-screen INDEX yourself if
#     the automatic Qt placement puts it on the projector.
#   * Mid-set recovery: if either app EXITS NONZERO (crash) it is restarted
#     (up to 3 times per app) while the other keeps running — ShowSync's
#     audio never stops for a Keyframes crash. Clean exits end the show:
#     Esc in Keyframes, Esc in the projector, set completion (--headless),
#     closing the ShowSync editor, or Ctrl+C here.
#   * Per-song MIDI .mid playback (decision D11) is a setlist concern:
#     ShowSync plays songs with or without `midi:` entries — nothing here
#     depends on it.
#
# Platform: target is macOS (Mac mini) with Linux for development. The
# script is bash-3.2 clean (macOS stock bash) and all platform-specific
# logic lives in the small `case $(uname -s)` block below.
#
# Test hooks (used by scripts/live_smoke_test.sh):
#   LIVE_PYTHON         override the python used for ShowSync/Keyframes
#   LIVE_UNAME          override the platform probe (Linux|Darwin)
#   LIVE_SETTLE_SECONDS seconds to let ShowSync open devices before
#                       Keyframes starts (default 2)
#   LIVE_RESTART_LIMIT  crash restarts allowed per app (default 3)
#   LIVE_KEYFRAMES_ARGS extra args for keyframes/main.py, word-split

set -euo pipefail

REPO_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)

SETTLE_SECONDS=${LIVE_SETTLE_SECONDS:-2}
RESTART_LIMIT=${LIVE_RESTART_LIMIT:-3}

usage() {
    sed -n '2,/^$/p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

# ---------------------------------------------------------------------------
# Platform differences — ALL of them live here.
#
# PLATFORM        Linux | Darwin (uname -s; LIVE_UNAME overrides for tests)
# pick_editor_screen_auto
#   Linux : parse `xrandr --listmonitors` for a monitor other than the first
#           landscape one (the one fullscreen Keyframes will take — mirrors
#           choose_landscape_display() in keyframes/main.py). Echoes the
#           xrandr name, which matches Qt's QScreen.name().
#   Darwin: no xrandr and Qt screen names are not predictable — echo nothing
#           and let ShowSync use its remembered screen; pass --editor-screen
#           INDEX explicitly to override.
# ---------------------------------------------------------------------------
PLATFORM=${LIVE_UNAME:-$(uname -s)}

pick_editor_screen_auto() {
    [ "$PLATFORM" = Linux ] || return 1
    command -v xrandr >/dev/null || return 1
    local line geom name cap_x="" cap_y="" fallback=""
    # Pass 1: the capture/visuals monitor = first landscape, else first.
    local first_x="" first_y=""
    while IFS= read -r line; do
        geom=$(awk '{print $3}' <<<"$line")
        if [[ $geom =~ ^([0-9]+)/[0-9]+x([0-9]+)/[0-9]+\+(-?[0-9]+)\+(-?[0-9]+)$ ]]; then
            if [ -z "$first_x" ]; then
                first_x=${BASH_REMATCH[3]} first_y=${BASH_REMATCH[4]}
            fi
            if [ -z "$cap_x" ] && (( BASH_REMATCH[1] > BASH_REMATCH[2] )); then
                cap_x=${BASH_REMATCH[3]} cap_y=${BASH_REMATCH[4]}
            fi
        fi
    done < <(xrandr --listmonitors | tail -n +2)
    if [ -z "$cap_x" ]; then
        cap_x=$first_x cap_y=$first_y
    fi
    [ -n "$cap_x" ] || return 1
    # Pass 2: any other monitor, preferring landscape.
    while IFS= read -r line; do
        geom=$(awk '{print $3}' <<<"$line")
        name=$(awk '{print $NF}' <<<"$line")
        if [[ $geom =~ ^([0-9]+)/[0-9]+x([0-9]+)/[0-9]+\+(-?[0-9]+)\+(-?[0-9]+)$ ]]; then
            [ "${BASH_REMATCH[3]}" = "$cap_x" ] && [ "${BASH_REMATCH[4]}" = "$cap_y" ] && continue
            if (( BASH_REMATCH[1] > BASH_REMATCH[2] )); then
                echo "$name"
                return 0
            fi
            [ -z "$fallback" ] && fallback=$name
        fi
    done < <(xrandr --listmonitors | tail -n +2)
    [ -n "$fallback" ] && { echo "$fallback"; return 0; }
    return 1
}

# Globals the supervisor and cleanup share (EXIT trap fires after main()
# returns, when locals are gone and `set -u` would abort the shutdown).
showsync_pid="" keyframes_pid="" exit_code=0
showsync_cmd=() keyframes_cmd=() launch_bank="" bank_state=""

start_showsync() {
    "${showsync_cmd[@]}" &
    showsync_pid=$!
}

start_keyframes() {
    # The bank for THIS launch: whatever Keyframes last published (launch
    # bank or an F5/F6 switch — keyframes writes KEYFRAMES_BANK_STATE on
    # every bank load), falling back to --bank from our command line. A
    # crash-restart therefore lands in the bank that was live on stage.
    local current_bank=$launch_bank
    if [ -n "$bank_state" ] && [ -s "$bank_state" ]; then
        current_bank=$(head -n1 "$bank_state")
    fi
    local -a cmd=("${keyframes_cmd[@]}")
    if [ -n "$current_bank" ]; then
        cmd+=(--bank "$current_bank")
    fi
    # nice: Keyframes' video decode must never outbid ShowSync's audio for
    # CPU — a late video frame is fine, an audio underrun is not (canon
    # midi:I39). nice execs through, so $! names the python process.
    KEYFRAMES_BANK_STATE="$bank_state" nice -n 5 "${cmd[@]}" &
    keyframes_pid=$!
}

stop_pid() {
    local pid=$1
    [ -n "$pid" ] || return 0
    if kill -0 "$pid" 2>/dev/null; then
        kill -TERM "$pid" 2>/dev/null || true
    fi
    wait "$pid" 2>/dev/null || true
}

cleanup() {
    trap '' INT TERM HUP
    trap - EXIT
    set +e
    stop_pid "$keyframes_pid"; keyframes_pid=""
    stop_pid "$showsync_pid"; showsync_pid=""
    [ -n "$bank_state" ] && rm -f "$bank_state" "$bank_state.tmp"
}

# Reap a finished app into the global `rc`. MUST run in the main shell —
# `wait` inside a $(...) subshell cannot see the parent's children and
# would report 127 for every exit, clean or crashed. Call only after
# kill -0 says the pid is gone (bash 3.2 has no `wait -n`, so we poll).
reap() {
    rc=0
    wait "$1" 2>/dev/null || rc=$?
}

main() {
    local headless=0 no_restart=0 bank="" showsync_args=()
    while (( $# )); do
        case $1 in
            --bank)
                [ -n "${2:-}" ] || { echo "ERROR: --bank needs a name" >&2; exit 1; }
                bank=$2; shift 2 ;;
            --bank=*)
                bank=${1#--bank=}; shift ;;
            --no-restart)
                no_restart=1; shift ;;
            --headless)
                headless=1; showsync_args+=(--headless); shift ;;
            -h|--help)
                usage; exit 0 ;;
            *)
                showsync_args+=("$1"); shift ;;
        esac
    done

    case $PLATFORM in Linux|Darwin) ;; *)
        echo "WARNING: untested platform '$PLATFORM' — continuing as generic unix." >&2
    esac
    if [ "$PLATFORM" = Linux ] && [ -z "${DISPLAY:-}" ]; then
        echo "ERROR: DISPLAY is not set — live mode needs the real display." >&2
        exit 1
    fi

    # A setlist is required: a live show must never fall back to ShowSync's
    # "reopen last-used set" behavior and play the wrong set.
    local arg have_set=0
    for arg in ${showsync_args[@]+"${showsync_args[@]}"}; do
        case $arg in
            *.yaml|*.yml)
                have_set=1
                [ -f "$arg" ] || { echo "ERROR: setlist not found: $arg" >&2; exit 1; }
                ;;
        esac
    done
    if (( ! have_set )); then
        echo "ERROR: no setlist given. Usage: scripts/live.sh [options] setlist.yaml" >&2
        exit 1
    fi

    local python=${LIVE_PYTHON:-"$REPO_ROOT/venv/bin/python"}
    [ -x "$python" ] || python=$(command -v python3)

    # Hands-free start/stop from the KeyStep's hardware transport.
    if [[ " ${showsync_args[*]} " != *" --midi-transport"* ]]; then
        showsync_args+=(--midi-transport)
    fi

    # Keep the ShowSync editor off the visuals monitor where fullscreen
    # always-on-top Keyframes would cover it.
    local editor_screen=""
    if (( headless )); then
        echo "Editor screen: none (headless — projector only)"
    elif [[ " ${showsync_args[*]} " == *" --editor-screen"* ]]; then
        echo "Editor screen: set by caller"
    elif editor_screen=$(pick_editor_screen_auto); then
        echo "Editor screen: $editor_screen"
        showsync_args+=(--editor-screen "$editor_screen")
    elif [ "$PLATFORM" = Darwin ]; then
        echo "NOTE: macOS — ShowSync keeps its remembered editor screen;"
        echo "      pass --editor-screen INDEX if it opens on the projector."
    else
        echo "NOTE: only one monitor — the ShowSync editor will open under"
        echo "      fullscreen Keyframes. Use --autostart, or press F11 in"
        echo "      Keyframes to drop it out of fullscreen and reach the editor."
    fi

    showsync_cmd=("$python" "$REPO_ROOT/showsync/main.py"
                  ${showsync_args[@]+"${showsync_args[@]}"})
    keyframes_cmd=("$python" "$REPO_ROOT/keyframes/main.py")
    if [ -n "${LIVE_KEYFRAMES_ARGS:-}" ]; then
        # shellcheck disable=SC2206  # word-split on purpose
        keyframes_cmd+=(${LIVE_KEYFRAMES_ARGS})
    fi
    # --bank is handled by start_keyframes, not baked into keyframes_cmd:
    # each (re)launch re-reads the published bank state so a restart keeps
    # the bank that was live, F5/F6 switches included.
    launch_bank=$bank
    bank_state=$(mktemp "${TMPDIR:-/tmp}/live_bank_state.XXXXXX")
    rm -f "$bank_state"   # start empty: -s distinguishes "never published"

    # Signals exit EXPLICITLY after cleanup: a bare `trap cleanup` would
    # resume the supervisor loop mid-iteration — if the signal lands just
    # after a crash was reaped, the loop would relaunch the app AFTER its
    # siblings were torn down and then spin with nothing left to stop it.
    # Ctrl+C is the documented "end the show" path, so it exits 0.
    trap 'cleanup; exit 0' INT TERM HUP
    trap cleanup EXIT

    echo "Starting ShowSync (live — no capture)..."
    start_showsync

    # Let ShowSync open audio/MIDI and place its windows; abort early if it
    # died immediately (bad setlist, missing device) instead of putting
    # fullscreen Keyframes over its error output.
    local waited=0
    while (( waited < SETTLE_SECONDS * 10 )); do
        kill -0 "$showsync_pid" 2>/dev/null || break
        sleep 0.1
        waited=$((waited + 1))
    done
    if ! kill -0 "$showsync_pid" 2>/dev/null; then
        local rc
        reap "$showsync_pid"; showsync_pid=""
        if [ "$rc" -eq 0 ]; then
            echo "ShowSync exited before the show started."
        else
            echo "ERROR: ShowSync failed to start (exit $rc)." >&2
        fi
        exit "$rc"
    fi

    echo "Starting Keyframes (Esc in Keyframes ends the show)..."
    start_keyframes

    # Supervisor: poll both apps (bash 3.2: no `wait -n`). A clean exit of
    # either ends the show; a crash restarts the crashed app while the
    # other keeps running. Restarts are capped per app so a boot-loop
    # (missing media, dead GPU) cannot strobe the projector all night.
    local showsync_restarts=0 keyframes_restarts=0 rc
    while :; do
        sleep 0.5
        if [ -n "$keyframes_pid" ] && ! kill -0 "$keyframes_pid" 2>/dev/null; then
            reap "$keyframes_pid"; keyframes_pid=""
            if [ "$rc" -eq 0 ]; then
                echo "Keyframes exited (Esc) — ending the show."
                break
            fi
            echo "WARNING: Keyframes crashed (exit $rc)." >&2
            if (( no_restart )) || (( keyframes_restarts >= RESTART_LIMIT )); then
                echo "Not restarting Keyframes — ShowSync keeps playing;" >&2
                echo "Ctrl+C here ends the show." >&2
            else
                keyframes_restarts=$((keyframes_restarts + 1))
                echo "Restarting Keyframes ($keyframes_restarts/$RESTART_LIMIT)..."
                start_keyframes
            fi
        fi
        if [ -n "$showsync_pid" ] && ! kill -0 "$showsync_pid" 2>/dev/null; then
            reap "$showsync_pid"; showsync_pid=""
            if [ "$rc" -eq 0 ]; then
                echo "ShowSync exited cleanly (set complete / editor closed) — ending the show."
                break
            fi
            echo "WARNING: ShowSync crashed (exit $rc)." >&2
            if (( no_restart )) || (( showsync_restarts >= RESTART_LIMIT )); then
                echo "Not restarting ShowSync — visuals keep running;" >&2
                echo "Ctrl+C here ends the show." >&2
                exit_code=$rc
            else
                showsync_restarts=$((showsync_restarts + 1))
                echo "Restarting ShowSync ($showsync_restarts/$RESTART_LIMIT)..."
                echo "  A relaunch starts with no set playing: restart from the"
                echo "  editor (Skip to reach the current song), or it counts"
                echo "  down again if --autostart was passed (see runbook)."
                start_showsync
            fi
        fi
        # Both down and nothing restarted them: nothing left to supervise.
        [ -z "$keyframes_pid" ] && [ -z "$showsync_pid" ] && break
    done

    exit "$exit_code"
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
    main "$@"
fi
