#!/usr/bin/env bash
# live_smoke_test.sh — exercises scripts/live.sh with stub apps (no display,
# no audio, no real ShowSync/Keyframes). Covers argument handling, launch
# order and env hygiene, the crash supervisor (restart the crashed half,
# keep the other running), bank preservation across a Keyframes restart,
# clean-exit teardown, and the macOS code path (LIVE_UNAME=Darwin).
#
# Usage: scripts/live_smoke_test.sh
set -u

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
LIVE="$SCRIPT_DIR/live.sh"

WORK=$(mktemp -d "${TMPDIR:-/tmp}/live_smoke.XXXXXX")
trap 'rm -rf "$WORK"' EXIT

PASS=0 FAIL=0
ok()   { PASS=$((PASS + 1)); echo "ok   - $1"; }
fail() { FAIL=$((FAIL + 1)); echo "FAIL - $1"; }
check() {  # check DESCRIPTION COMMAND...
    local desc=$1; shift
    if "$@"; then ok "$desc"; else fail "$desc"; fi
}

# --- stub python ----------------------------------------------------------
# Stands in for both apps. Logs each launch ("<role> <args...>") to
# $STUB_LOG and relevant env to $STUB_ENV_LOG. Behavior per launch comes
# from $WORK/ctl.<role>: the first line is consumed on each start —
#   sleep  (default)  run until TERM, exit 0 on TERM (clean teardown)
#   exit0             exit 0 immediately (clean exit: Esc / set complete)
#   crash             exit 3 immediately
#   bank-switch-crash publish bank 'neon' to KEYFRAMES_BANK_STATE, then exit 3
STUB_LOG="$WORK/launches.log"
STUB_ENV_LOG="$WORK/env.log"
mkdir -p "$WORK/bin"
cat > "$WORK/bin/python-stub" <<'EOF'
#!/usr/bin/env bash
role=other
case "${1:-}" in
    */showsync/main.py)  role=showsync ;;
    */keyframes/main.py) role=keyframes ;;
esac
shift || true
echo "$role $*" >> "$STUB_LOG"
echo "$role BANK_STATE=${KEYFRAMES_BANK_STATE:-unset} MIDI_LOG=${KEYFRAMES_MIDI_LOG:-unset} MARKERS=${SHOWSYNC_MARKERS:-unset}" >> "$STUB_ENV_LOG"
beh=sleep
ctl="$STUB_CTL/ctl.$role"
if [ -s "$ctl" ]; then
    beh=$(head -n1 "$ctl")
    tail -n +2 "$ctl" > "$ctl.t" && mv "$ctl.t" "$ctl"
fi
case $beh in
    exit0) exit 0 ;;
    crash) exit 3 ;;
    bank-switch-crash)
        if [ -n "${KEYFRAMES_BANK_STATE:-}" ]; then
            printf 'neon\n' > "$KEYFRAMES_BANK_STATE"
        fi
        exit 3 ;;
    *) trap 'exit 0' TERM; while :; do sleep 0.1; done ;;
esac
EOF
chmod +x "$WORK/bin/python-stub"

# Fake xrandr: two landscape monitors, so the Linux editor-screen pick has
# something to choose. Only on PATH for the tests that opt in.
mkdir -p "$WORK/xrandr-bin"
cat > "$WORK/xrandr-bin/xrandr" <<'EOF'
#!/usr/bin/env bash
echo "Monitors: 2"
echo " 0: +*DP-1 1920/480x1080/270+0+0  DP-1"
echo " 1: +HDMI-1 1920/480x1080/270+1920+0  HDMI-1"
EOF
chmod +x "$WORK/xrandr-bin/xrandr"

SETLIST="$WORK/set.yaml"
echo "songs: []" > "$SETLIST"

# Launch live.sh in the background with a clean stub state. Args pass through.
RUN_LOG=""
run_live() {
    : > "$STUB_LOG"; : > "$STUB_ENV_LOG"
    RUN_LOG="$WORK/run.log"
    STUB_LOG="$STUB_LOG" STUB_ENV_LOG="$STUB_ENV_LOG" STUB_CTL="$WORK" \
    LIVE_PYTHON="$WORK/bin/python-stub" \
    LIVE_SETTLE_SECONDS="${SETTLE_OVERRIDE:-0}" \
    DISPLAY="${DISPLAY:-:99}" \
        "$LIVE" "$@" > "$RUN_LOG" 2>&1 &
    LIVE_PID=$!
}

# Wait until $1 lines matching $2 appear in the launch log (3s cap).
wait_launches() {
    local count=$1 pattern=$2 i=0
    while (( i < 60 )); do
        [ "$(grep -c "$pattern" "$STUB_LOG" 2>/dev/null)" -ge "$count" ] && return 0
        sleep 0.05; i=$((i + 1))
    done
    return 1
}

# Both set the global `rc`. They MUST run in the main shell — `wait` in a
# $(...) subshell cannot see this shell's children and returns 127 at once,
# leaking the stubs into the next test.
end_live() {  # TERM live.sh and reap it
    kill -TERM "$LIVE_PID" 2>/dev/null
    rc=0
    wait "$LIVE_PID" 2>/dev/null || rc=$?
}

wait_live_exit() {  # wait for live.sh to exit on its own (5s cap)
    local i=0
    rc=0
    while kill -0 "$LIVE_PID" 2>/dev/null && (( i < 100 )); do
        sleep 0.05; i=$((i + 1))
    done
    if kill -0 "$LIVE_PID" 2>/dev/null; then
        kill -KILL "$LIVE_PID" 2>/dev/null
        wait "$LIVE_PID" 2>/dev/null
        rc=timeout
        return
    fi
    wait "$LIVE_PID" 2>/dev/null || rc=$?
}

clear_ctl() { rm -f "$WORK"/ctl.*; }

# --- 1. usage / argument errors -------------------------------------------
"$LIVE" --help > "$WORK/help.out" 2>&1
check "--help exits 0 and prints usage" \
    grep -q "one-command LIVE performance launcher" "$WORK/help.out"

if "$LIVE" > "$WORK/noset.out" 2>&1; then fail "no setlist refused"; else
    check "no setlist refused" grep -q "no setlist given" "$WORK/noset.out"; fi

if "$LIVE" "$WORK/absent.yaml" > "$WORK/badset.out" 2>&1; then
    fail "missing setlist file refused"
else
    check "missing setlist file refused" grep -q "setlist not found" "$WORK/badset.out"
fi

# --- 2. normal run: launch order, args, env hygiene, clean teardown -------
clear_ctl
# A real settle here so the launch-order check is not racing the two
# stubs' first log writes.
SETTLE_OVERRIDE=1 run_live "$SETLIST"
wait_launches 1 "^keyframes" || true
check "showsync launched" grep -q "^showsync .*set.yaml" "$STUB_LOG"
# Rig topology v3 (D15): the KeyStep transport belongs to Devin's rig, so
# live.sh must never opt ShowSync into it — pure caller opt-in.
check "no --midi-transport injected by default" \
    bash -c '! grep -q -- "--midi-transport" "$1"' _ "$STUB_LOG"
check "keyframes launched" grep -q "^keyframes" "$STUB_LOG"
check "showsync starts before keyframes" \
    bash -c 'head -n1 "$1" | grep -q "^showsync"' _ "$STUB_LOG"
check "no capture sidecars in env (markers/midi log unset)" \
    bash -c '! grep -vq "MIDI_LOG=unset MARKERS=unset" "$1"' _ "$STUB_ENV_LOG"
check "keyframes got a bank-state path" \
    grep -q "^keyframes BANK_STATE=/" "$STUB_ENV_LOG"
end_live
check "Ctrl+C/TERM tears down cleanly (exit 0)" test "$rc" = 0
# [-] so pgrep cannot match this checking process's own command line.
check "stubs are gone after teardown" \
    bash -c '! pgrep -f "python[-]stub" >/dev/null'

# --- 2b. --midi-transport is pass-through only ------------------------------
clear_ctl
run_live --midi-transport "$SETLIST"
wait_launches 1 "^keyframes" || true
check "caller's --midi-transport reaches showsync" \
    grep -q "^showsync .*--midi-transport" "$STUB_LOG"
check "caller's --midi-transport appears exactly once" \
    bash -c 'test "$(head -n1 "$1" | grep -o -- "--midi-transport" | wc -l)" = 1' _ "$STUB_LOG"
end_live
check "pass-through run teardown clean" test "$rc" = 0

# --- 3. keyframes clean exit (Esc) ends the show ---------------------------
clear_ctl
printf 'sleep\nexit0\n' > /dev/null  # (behaviors are per-launch via ctl files)
printf 'exit0\n' > "$WORK/ctl.keyframes"
run_live "$SETLIST"
wait_live_exit
check "keyframes Esc ends the show with exit 0" test "$rc" = 0
check "keyframes not restarted after clean exit" \
    test "$(grep -c '^keyframes' "$STUB_LOG")" = 1

# --- 4. keyframes crash: restarted, showsync untouched ---------------------
clear_ctl
printf 'crash\n' > "$WORK/ctl.keyframes"   # first launch crashes, second sleeps
run_live "$SETLIST"
wait_launches 2 "^keyframes" \
    && ok "keyframes restarted after crash" \
    || fail "keyframes restarted after crash"
check "showsync launched exactly once across keyframes crash" \
    test "$(grep -c '^showsync' "$STUB_LOG")" = 1
end_live
check "post-restart teardown clean" test "$rc" = 0

# --- 5. bank preserved across keyframes crash-restart ----------------------
clear_ctl
printf 'bank-switch-crash\n' > "$WORK/ctl.keyframes"
run_live --bank robots "$SETLIST"
wait_launches 2 "^keyframes" || fail "bank test: keyframes restarted"
check "first keyframes launch uses --bank robots" \
    bash -c 'grep "^keyframes" "$1" | head -n1 | grep -q -- "--bank robots"' _ "$STUB_LOG"
check "restart uses the live bank (neon), not the launch bank" \
    bash -c 'grep "^keyframes" "$1" | sed -n 2p | grep -q -- "--bank neon"' _ "$STUB_LOG"
end_live
check "bank test teardown clean" test "$rc" = 0

# --- 6. showsync crash: restarted, keyframes untouched ---------------------
clear_ctl
printf 'sleep\n' > "$WORK/ctl.showsync"    # first launch OK...
run_live "$SETLIST"
wait_launches 1 "^keyframes" || true
# Match showsync/main.py specifically: a broader "showsync" would also hit
# the keyframes stub when the repo path itself contains "showsync" (e.g. a
# task worktree named after this feature).
pkill -KILL -f "python-stub.*showsync/main.py" 2>/dev/null   # simulate a hard crash
wait_launches 2 "^showsync" \
    && ok "showsync restarted after crash" \
    || fail "showsync restarted after crash"
check "keyframes launched exactly once across showsync crash" \
    test "$(grep -c '^keyframes' "$STUB_LOG")" = 1
end_live
check "showsync-crash teardown clean" test "$rc" = 0

# --- 7. --no-restart leaves a crashed app down ------------------------------
clear_ctl
printf 'crash\n' > "$WORK/ctl.keyframes"
run_live --no-restart "$SETLIST"
sleep 1.5
check "--no-restart: keyframes stays down" \
    test "$(grep -c '^keyframes' "$STUB_LOG")" = 1
end_live
check "--no-restart teardown clean" test "$rc" = 0

# --- 8. showsync dies at startup: abort before keyframes -------------------
clear_ctl
printf 'crash\n' > "$WORK/ctl.showsync"
# Direct invocation (to capture rc) bypasses run_live's log truncation —
# clear the stub logs here or section 7's keyframes launch fails the check.
: > "$STUB_LOG"; : > "$STUB_ENV_LOG"
STUB_LOG="$STUB_LOG" STUB_ENV_LOG="$STUB_ENV_LOG" STUB_CTL="$WORK" \
LIVE_PYTHON="$WORK/bin/python-stub" LIVE_SETTLE_SECONDS=1 \
DISPLAY="${DISPLAY:-:99}" \
    "$LIVE" "$SETLIST" > "$WORK/run.log" 2>&1
rc=$?
check "startup failure exits nonzero" test "$rc" != 0
check "startup failure reported" grep -q "failed to start" "$WORK/run.log"
check "keyframes never launched after startup failure" \
    bash -c '! grep -q "^keyframes" "$1"' _ "$STUB_LOG"

# --- 9. Linux editor-screen auto-pick (fake xrandr) -------------------------
clear_ctl
OLD_PATH=$PATH
PATH="$WORK/xrandr-bin:$PATH"
LIVE_UNAME=Linux run_live "$SETLIST"
wait_launches 1 "^keyframes" || true
check "editor screen auto-picked on Linux (HDMI-1)" \
    grep -q -- "--editor-screen HDMI-1" "$STUB_LOG"
end_live
PATH=$OLD_PATH
check "editor-screen run teardown clean" test "$rc" = 0

# --- 10. macOS path: no xrandr, no editor-screen injection ------------------
clear_ctl
LIVE_UNAME=Darwin run_live "$SETLIST"
wait_launches 1 "^keyframes" || true
check "macOS: apps launch without xrandr" grep -q "^keyframes" "$STUB_LOG"
check "macOS: no --editor-screen injected" \
    bash -c '! grep -q -- "--editor-screen" "$1"' _ "$STUB_LOG"
check "macOS note printed" grep -q "macOS" "$RUN_LOG"
end_live
check "macOS run teardown clean" test "$rc" = 0

# --- 11. --headless skips editor-screen logic -------------------------------
clear_ctl
PATH="$WORK/xrandr-bin:$PATH" LIVE_UNAME=Linux run_live --headless "$SETLIST"
wait_launches 1 "^keyframes" || true
check "--headless passed to showsync" grep -q "^showsync .*--headless" "$STUB_LOG"
check "--headless: no --editor-screen" \
    bash -c '! grep -q -- "--editor-screen" "$1"' _ "$STUB_LOG"
end_live
check "--headless teardown clean" test "$rc" = 0

echo ""
echo "live_smoke_test: $PASS passed, $FAIL failed"
exit $(( FAIL > 0 ))
