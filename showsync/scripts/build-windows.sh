#!/usr/bin/env bash
# SSH transports source; native Windows PowerShell/Python performs the build.
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
host=${SHOWSYNC_WINDOWS_HOST:-devin@192.168.1.225}
repo=${SHOWSYNC_WINDOWS_REPO:-/mnt/c/Users/devin/src/showsync-build}
powershell=${SHOWSYNC_WINDOWS_POWERSHELL:-/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe}
branch=$(git -C "$root" branch --show-current)
args=()
for arg in "$@"; do
    case "$arg" in
        --skip-deps) args+=(-SkipDeps) ;;
        --clean) args+=(-Clean) ;;
        --help|-h) echo 'Usage: showsync/scripts/build-windows.sh [--skip-deps] [--clean]'; exit 0 ;;
        *) echo "Unknown argument: $arg" >&2; exit 2 ;;
    esac
done
[[ -n "$branch" ]] || { echo 'Cannot build a detached HEAD.' >&2; exit 1; }
[[ -z $(git -C "$root" status --porcelain --untracked-files=normal) ]] || {
    echo 'Commit changes before building: only committed source is transferred.' >&2; exit 1;
}
git -C "$root" push origin "HEAD:$branch"
url=$(git -C "$root" remote get-url origin)
# Quote arguments for the remote bash shell, including paths containing spaces.
printf -v init 'test -d %q/.git || git clone %q %q' "$repo" "$url" "$repo"
ssh -o BatchMode=yes "$host" "$init"
revision=$(git -C "$root" rev-parse HEAD)
printf -v sync 'cd %q && git fetch origin && git checkout --detach %q' "$repo" "$revision"
ssh -o BatchMode=yes "$host" "$sync"
printf -v convert 'wslpath -w %q' "$repo/showsync/scripts/build_windows.ps1"
script=$(ssh -o BatchMode=yes "$host" "$convert")
printf -v build '%q -NoProfile -ExecutionPolicy Bypass -File %q' "$powershell" "$script"
ssh -o BatchMode=yes "$host" "$build ${args[*]}"
mkdir -p "$root/dist"
scp "$host:$repo/showsync/dist/ShowSync_Windows.zip" "$root/dist/ShowSync_Windows.zip"
scp -r "$host:$repo/showsync/dist/windows-verification" "$root/dist/"
echo "Verified Windows release: $root/dist/ShowSync_Windows.zip"
