#!/usr/bin/env bash
# keyframes-watch.sh — sidecar process watcher for live Keyframes runs.
#
# Replaces the ad-hoc "watcher2" from the 2026-10-10 lockup session, whose
# pgrep pattern '^python3 .*keyframes/main.py' never matched anything:
# live.sh launches Keyframes via the venv python's ABSOLUTE path (and
# through `nice`), so the command line never starts with 'python3'. The
# correct match is the one invariant part of the command line —
# 'keyframes/main.py' — with this watcher's own process tree excluded.
#
# Samples the Keyframes process once a second (state, %CPU, RSS) to stdout
# and/or a log file, logs when the process vanishes or a new one appears
# (live.sh crash-restarts), and — the payload — if the process looks wedged
# (alive but its stall heartbeat is silent) you can get a stack from it
# WITHOUT killing it, provided it was started with KEYFRAMES_STALL_LOG set:
#
#   kill -USR1 <pid>     # all-thread stack dump appended to the stall log
#
# Usage: scripts/keyframes-watch.sh [logfile]
#   logfile   append samples there as well as stdout (default: stdout only)

set -u

LOG=${1:-}

say() {
    local line="$(date '+%H:%M:%S') $*"
    echo "$line"
    [ -n "$LOG" ] && echo "$line" >> "$LOG"
}

find_pid() {
    # -f matches the full command line; exclude this watcher's own shell and
    # children so a dead Keyframes can never read as "still running".
    pgrep -f 'keyframes/main\.py' 2>/dev/null | while read -r pid; do
        [ "$pid" = "$$" ] && continue
        [ "$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')" = "$$" ] && continue
        echo "$pid"
    done | head -n1
}

say "watching for keyframes/main.py (Ctrl+C stops the watcher only)"
pid=""
while :; do
    current=$(find_pid || true)
    if [ -z "$current" ]; then
        if [ -n "$pid" ]; then
            say "keyframes pid $pid GONE (exited or was killed)"
            pid=""
        fi
    else
        if [ "$current" != "$pid" ]; then
            [ -n "$pid" ] && say "keyframes pid changed $pid -> $current (restart?)"
            pid=$current
            say "keyframes pid $pid: $(ps -o args= -p "$pid" 2>/dev/null)"
        fi
        sample=$(ps -o stat=,pcpu=,rss= -p "$pid" 2>/dev/null | tr -s ' ')
        say "pid $pid stat/cpu/rss:$sample"
    fi
    sleep 1
done
