#!/usr/bin/env bash
# deploy-mac.sh — sync the gig build to the Mac mini (T248).
#
# Pushes git-tracked code plus the untracked gig media (song audio,
# Keyframes banks and images/) to the mini over SSH, then installs/updates
# the Python deps in the mini's venv. Idempotent: rsync only moves deltas.
#
# Usage: scripts/deploy-mac.sh [host]   # host defaults to 'mac' (ssh alias)
#
# Run from the checkout you want deployed (main or a worktree) — the code
# file list is `git ls-files` of the CURRENT checkout, while media is
# always taken from the main checkout at ~/src/2026/midi (worktrees do not
# carry the untracked media).
set -euo pipefail

HOST=${1:-mac}
REMOTE_DIR='src/2026/midi'
REPO_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
MEDIA_ROOT=${DEPLOY_MEDIA_ROOT:-$HOME/src/2026/midi}

cd "$REPO_ROOT"
ssh "$HOST" "mkdir -p $REMOTE_DIR"

echo "==> code ($(git ls-files | wc -l) tracked files)"
git ls-files | rsync -a --files-from=- . "$HOST:$REMOTE_DIR/"

echo '==> media (songs, keyframes banks + images)'
rsync -a --exclude BL_proxy --exclude '*.bak-*' \
    "$MEDIA_ROOT/songs/" "$HOST:$REMOTE_DIR/songs/"
rsync -a "$MEDIA_ROOT/keyframes/banks/" "$HOST:$REMOTE_DIR/keyframes/banks/"
rsync -a "$MEDIA_ROOT/keyframes/images/" "$HOST:$REMOTE_DIR/keyframes/images/"

echo '==> python deps'
ssh "$HOST" "cd $REMOTE_DIR && \
    { [ -x venv/bin/python ] || /usr/local/bin/python3 -m venv venv; } && \
    venv/bin/pip -q install -r showsync/requirements.txt \
        -r keyframes/requirements.txt"

# The mini's /usr/local is an INTEL Homebrew prefix: `env bash` resolves to
# x86_64 bash, and a universal2 venv launcher spawned from it runs its
# Rosetta slice — which cannot import the arm64-only wheels (rtmidi, numpy),
# killing live.sh at launch. Thin the launcher to arm64 so the interpreter
# arch never depends on who spawned it. Re-applied on every deploy because a
# venv rebuild restores the universal binary.
echo '==> force arm64 interpreter'
ssh "$HOST" "cd $REMOTE_DIR/venv/bin && \
    if lipo -archs python3.11 2>/dev/null | grep -q x86_64; then \
        lipo python3.11 -thin arm64 -output python3.11.arm64 && \
        mv python3.11.arm64 python3.11 && chmod +x python3.11; \
    fi"
ssh "$HOST" "bash -c '$REMOTE_DIR/venv/bin/python -c \
    \"import platform, rtmidi; assert platform.machine() == \\\"arm64\\\"\"'" \
    && echo 'arm64 verify: OK (from x86_64 bash parent)'

echo 'deploy-mac: done'
