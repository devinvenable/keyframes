#!/usr/bin/env bash
# Run the frozen artifact's image/video/RT-MIDI self-test on the Windows VM.
set -euo pipefail

if [[ $# -ne 2 ]]; then
    echo "Usage: $0 <windows-ssh-host> <windows-repo-wsl-path>" >&2
    exit 2
fi

windows_vm=$1
windows_repo=$2
# powershell.exe is not on PATH for a non-login SSH shell into WSL; invoke it by
# its stable absolute path.  Override if the box installs it elsewhere.
windows_powershell=${KEYFRAMES_WINDOWS_POWERSHELL:-/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe}
windows_repo_win=${windows_repo#/mnt/c/}
windows_repo_win="C:\\${windows_repo_win//\//\\}"
exe_path="$windows_repo_win\\dist\\Keyframes_Windows\\Keyframes.exe"

# Keyframes.exe is a windowed (GUI-subsystem) build, so $LASTEXITCODE is not
# updated for it and cannot be trusted.  The smoke test prints a fixed success
# sentinel and prints nothing on failure (it raises), so gate on the sentinel to
# fail closed.
sentinel='Packaging smoke test passed'
output=$(ssh "$windows_vm" "'$windows_powershell' -NoProfile -Command \"& '$exe_path' --packaging-smoke-test\"")
echo "$output"
if ! grep -qF "$sentinel" <<<"$output"; then
    echo "Smoke test did not report success ('$sentinel' not found)." >&2
    exit 1
fi
