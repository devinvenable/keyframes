#!/usr/bin/env bash
# Run the frozen artifact's image/video/RT-MIDI self-test on the Windows VM.
set -euo pipefail

if [[ $# -ne 2 ]]; then
    echo "Usage: $0 <windows-ssh-host> <windows-repo-wsl-path>" >&2
    exit 2
fi

windows_vm=$1
windows_repo=$2
windows_repo_win=${windows_repo#/mnt/c/}
windows_repo_win="C:\\${windows_repo_win//\//\\}"
exe_path="$windows_repo_win\\dist\\Keyframes_Windows\\Keyframes.exe"

ssh "$windows_vm" "powershell.exe -NoProfile -Command \"& '$exe_path' --packaging-smoke-test; exit \\\$LASTEXITCODE\""
