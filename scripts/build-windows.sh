#!/usr/bin/env bash
# Build Keyframes on the reusable Windows VM and copy back the distributable.
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
windows_vm=${KEYFRAMES_WINDOWS_VM:-devin@192.168.1.225}
windows_repo=${KEYFRAMES_WINDOWS_REPO:-/mnt/c/Users/devin/src/keyframes}
branch=$(git -C "$repo_root" branch --show-current)
skip_deps=false
clean=false

usage() {
    cat <<'EOF'
Usage: scripts/build-windows.sh [--skip-deps] [--clean]

Pushes the current branch, has the Windows VM pull it, builds the one-folder
release, runs the frozen image/video/RT-MIDI smoke test, then copies back:
  dist/Keyframes_Windows.zip

Override KEYFRAMES_WINDOWS_VM or KEYFRAMES_WINDOWS_REPO if the VM differs.
EOF
}

for arg in "$@"; do
    case "$arg" in
        --skip-deps) skip_deps=true ;;
        --clean) clean=true ;;
        --help|-h) usage; exit 0 ;;
        *) echo "Unknown option: $arg" >&2; usage >&2; exit 2 ;;
    esac
done

if [[ -z "$branch" ]]; then
    echo 'Cannot build from a detached HEAD.' >&2
    exit 1
fi

git -C "$repo_root" push origin "HEAD:$branch"
ssh "$windows_vm" "cd '$windows_repo' && git fetch origin && git checkout '$branch' && git pull --ff-only origin '$branch'"

windows_repo_win=${windows_repo#/mnt/c/}
windows_repo_win="C:\\${windows_repo_win//\//\\}"
ps_args=''
[[ "$skip_deps" == true ]] && ps_args+=' -SkipDeps'
[[ "$clean" == true ]] && ps_args+=' -Clean'
ssh "$windows_vm" "powershell.exe -NoProfile -ExecutionPolicy Bypass -File '$windows_repo_win\\scripts\\build_windows.ps1'$ps_args"

"$repo_root/scripts/verify-windows-build.sh" "$windows_vm" "$windows_repo"
mkdir -p "$repo_root/dist"
scp "$windows_vm:$windows_repo/dist/Keyframes_Windows.zip" "$repo_root/dist/Keyframes_Windows.zip"
echo "Windows distributable copied to $repo_root/dist/Keyframes_Windows.zip"
