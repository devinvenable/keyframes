#!/usr/bin/env bash
# mixdown.sh — post-process a perform.sh take into a single-audio-track mp4.
#
# Mixes the take's two audio tracks (title=mixer line-in + title=system
# backing tracks) into one stereo AAC track. The video stream is COPIED
# untouched — no re-encode, so this is fast and lossless for the picture.
# A take with a single audio track goes through the same gain chain
# (no amix). Tracks are found by their title metadata; a two-track take
# without titles falls back to the recording layout (first=mixer,
# second=system) with a note.
#
# Usage: scripts/mixdown.sh [options] <take.mkv>
#   --mixer-gain G    volume for the title=mixer track (default 1.0;
#                     ffmpeg volume syntax: 1.5, 0.5, -3dB, ...)
#   --system-gain G   volume for the title=system track (default 1.0)
#   --loudnorm        apply EBU R128 loudness normalization after the mix
#   -o, --output F    output file (default: <take>_final.mp4)
#   -y                overwrite an existing output file
#
# Exit nonzero when the input is missing, has no audio, or a gain value is
# not a number/dB — a typo must not silently produce a wrong mix.

set -euo pipefail

usage() {
    sed -n '2,21p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

fail() { echo "ERROR: $*" >&2; exit 1; }

# Volume values are spliced into -filter_complex; accept only a plain
# number or a dB value so a typo cannot mangle the filtergraph.
check_gain() {
    [[ $2 =~ ^-?[0-9]+(\.[0-9]+)?(dB)?$ ]] ||
        fail "$1 must be a number or NdB (got '$2')"
}

main() {
    local mixer_gain="1.0" system_gain="1.0" loudnorm=0 out="" overwrite=()
    local in=""
    while (( $# )); do
        case $1 in
            --mixer-gain)   [[ -n ${2:-} ]] || fail "--mixer-gain needs a value"
                            mixer_gain=$2; shift 2 ;;
            --mixer-gain=*) mixer_gain=${1#*=}; shift ;;
            --system-gain)  [[ -n ${2:-} ]] || fail "--system-gain needs a value"
                            system_gain=$2; shift 2 ;;
            --system-gain=*) system_gain=${1#*=}; shift ;;
            --loudnorm)     loudnorm=1; shift ;;
            -o|--output)    [[ -n ${2:-} ]] || fail "$1 needs a path"
                            out=$2; shift 2 ;;
            --output=*)     out=${1#*=}; shift ;;
            -y)             overwrite=(-y); shift ;;
            -h|--help)      usage; exit 0 ;;
            -*)             fail "unknown option '$1' (see --help)" ;;
            *)              [[ -z $in ]] || fail "only one input take, got '$in' and '$1'"
                            in=$1; shift ;;
        esac
    done
    [[ -n $in ]] || { usage >&2; exit 1; }
    [[ -f $in ]] || fail "input '$in' not found"
    check_gain --mixer-gain "$mixer_gain"
    check_gain --system-gain "$system_gain"
    command -v ffmpeg  >/dev/null || fail "ffmpeg not found"
    command -v ffprobe >/dev/null || fail "ffprobe not found"

    if [[ -z $out ]]; then
        out="${in%.*}_final.mp4"
    fi
    if [[ -e $out && ${#overwrite[@]} -eq 0 ]]; then
        fail "output '$out' exists (pass -y to overwrite)"
    fi

    # Find the audio streams and their titles: lines "INDEX[,TITLE]".
    local streams
    streams=$(ffprobe -v error -select_streams a \
        -show_entries stream=index:stream_tags=title -of csv=p=0 "$in") ||
        fail "ffprobe cannot read '$in'"

    local idx title mixer_idx="" system_idx="" indexes=() count=0
    while IFS=, read -r idx title; do
        [[ -n $idx ]] || continue
        indexes+=("$idx")
        (( ++count ))
        case ${title:-} in
            mixer)  mixer_idx=$idx ;;
            system) system_idx=$idx ;;
        esac
    done <<<"$streams"

    local fc="" mode=""
    if (( count == 0 )); then
        fail "'$in' has no audio streams"
    elif [[ -n $mixer_idx && -n $system_idx ]]; then
        mode="mix (mixer #$mixer_idx + system #$system_idx)"
    elif (( count >= 2 )); then
        # Untitled two-track take: perform.sh records mixer first, system
        # second — assume that layout rather than refusing the file.
        mixer_idx=${indexes[0]} system_idx=${indexes[1]}
        echo "NOTE: audio titles missing — assuming track #$mixer_idx=mixer," \
             "#$system_idx=system (perform.sh layout)."
        mode="mix (untitled #$mixer_idx + #$system_idx)"
    else
        # Single audio track: apply its matching gain, no amix.
        local only=${indexes[0]} gain=$mixer_gain label="mixer"
        [[ $only == "$system_idx" ]] && { gain=$system_gain; label="system"; }
        fc="[0:${only}]volume=${gain}[aout]"
        mode="single track #$only ($label, gain $gain)"
    fi
    if [[ -z $fc ]]; then
        # Live inputs start at different timestamps (-isync in perform.sh).
        # amix combines samples, so pad each stream to the common origin
        # before mixing, rather than moving a later track's sound earlier.
        fc="[0:${mixer_idx}]aresample=async=1:first_pts=0,volume=${mixer_gain}[m];"
        fc+="[0:${system_idx}]aresample=async=1:first_pts=0,volume=${system_gain}[s];"
        fc+="[m][s]amix=inputs=2:duration=longest:normalize=0[aout]"
    fi
    if (( loudnorm )); then
        fc="${fc/\[aout\]/[mix]};[mix]loudnorm=I=-16:TP=-1.5:LRA=11[aout]"
        mode+=" + loudnorm"
    fi

    echo "Mixdown: $in -> $out"
    echo "Audio  : $mode (mixer gain $mixer_gain, system gain $system_gain)"
    ffmpeg -hide_banner -loglevel warning -nostdin ${overwrite[@]+"${overwrite[@]}"} \
        -i "$in" \
        -filter_complex "$fc" \
        -map 0:v:0 -map '[aout]' \
        -c:v copy -c:a aac -b:a 192k -ar 48000 \
        -movflags +faststart \
        "$out" || fail "ffmpeg mixdown failed"

    local dur=""
    dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$out" 2>/dev/null) || true
    echo "Done: $out${dur:+ (${dur%.*}s)}"
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
    main "$@"
fi
