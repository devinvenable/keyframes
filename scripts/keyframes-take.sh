#!/usr/bin/env bash
# Fullscreen Keyframes + capture, driven by MIDI without ShowSync.
# Defaults to mixer USB audio; pass --audio to override, or --help for options.
set -euo pipefail
exec "$(dirname -- "${BASH_SOURCE[0]}")/perform.sh" --keyframes-only "$@"
