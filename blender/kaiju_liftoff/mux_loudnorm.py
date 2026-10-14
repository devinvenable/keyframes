"""Mux a reusable silent video master with two-pass loudness-normalized audio.

This stage is deliberately independent from the slow Blender grade.  Re-run it
with another ``--target-i`` to create a louder or quieter variant without
touching the graded video stream.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
from fractions import Fraction
from pathlib import Path


def run(args: list[object], **kwargs) -> subprocess.CompletedProcess:
    command = [str(arg) for arg in args]
    result = subprocess.run(command, capture_output=True, text=True, **kwargs)
    if result.returncode:
        raise RuntimeError(
            f"Command failed ({result.returncode}): {' '.join(command)}\n"
            f"{result.stdout[-2000:]}\n{result.stderr[-4000:]}"
        )
    return result


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def probe(path: Path) -> dict:
    result = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-count_frames",
            "-show_entries",
            (
                "format=duration,size,bit_rate:"
                "stream=index,codec_type,codec_name,width,height,avg_frame_rate,"
                "nb_read_frames,duration,sample_rate,channels,channel_layout"
            ),
            "-of",
            "json",
            path,
        ]
    )
    return json.loads(result.stdout)


def measure_loudness(path: Path, target_i: float, target_tp: float, target_lra: float) -> dict:
    result = run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostdin",
            "-i",
            path,
            "-map",
            "0:a:0",
            "-af",
            f"loudnorm=I={target_i}:TP={target_tp}:LRA={target_lra}:print_format=json",
            "-f",
            "null",
            "-",
        ]
    )
    matches = re.findall(r'\{\s*"input_i".*?\}', result.stderr, flags=re.DOTALL)
    assert matches, result.stderr[-4000:]
    return json.loads(matches[-1])


def video_stream(info: dict) -> dict:
    streams = [stream for stream in info["streams"] if stream["codec_type"] == "video"]
    assert len(streams) == 1, streams
    return streams[0]


def audio_stream(info: dict) -> dict:
    streams = [stream for stream in info["streams"] if stream["codec_type"] == "audio"]
    assert len(streams) == 1, streams
    return streams[0]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, required=True, help="silent graded master")
    parser.add_argument("--audio", type=Path, required=True, help="media containing source audio")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--target-i", type=float, default=-12.0)
    parser.add_argument("--target-tp", type=float, default=-1.0)
    parser.add_argument("--target-lra", type=float, default=11.0)
    args = parser.parse_args()

    video = args.video.resolve()
    audio = args.audio.resolve()
    output = args.output.resolve()
    report_path = (args.report or output.with_suffix(".qa.json")).resolve()
    assert video.is_file() and audio.is_file()
    assert output not in {video, audio}, "Output must be a new file"
    output.parent.mkdir(parents=True, exist_ok=True)

    audio_hash = sha256(audio)
    before = measure_loudness(audio, args.target_i, args.target_tp, args.target_lra)
    # AAC can shift integrated loudness by several tenths of a LU and create
    # inter-sample peaks above the filter-domain ceiling.  Correct against the
    # actual encoded result; every retry stream-copies the already graded video.
    # Leave AAC encoding headroom, then correct integrated loudness after the
    # R128 pass with a peak-limited makeup stage.  This is needed when the
    # requested loudness cannot be reached by linear normalization alone.
    processing_tp = max(-9.0, args.target_tp - 0.5)
    measured = measure_loudness(
        audio, args.target_i, processing_tp, args.target_lra
    )
    makeup_db = 0.0
    limiter_db = processing_tp
    attempts = []
    after = None
    for attempt_number in range(1, 7):
        limiter_amplitude = math.pow(10.0, limiter_db / 20.0)
        loudnorm = (
            f"loudnorm=I={args.target_i}:TP={processing_tp}:LRA={args.target_lra}:"
            f"measured_I={measured['input_i']}:measured_TP={measured['input_tp']}:"
            f"measured_LRA={measured['input_lra']}:"
            f"measured_thresh={measured['input_thresh']}:"
            f"offset={measured['target_offset']}:linear=true:print_format=summary,"
            f"volume={makeup_db}dB,"
            f"alimiter=limit={limiter_amplitude}:attack=5:release=50:level=false"
        )
        run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                video,
                "-i",
                audio,
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "copy",
                "-af",
                loudnorm,
                "-ar",
                "48000",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-movflags",
                "+faststart",
                output,
            ]
        )
        after = measure_loudness(output, args.target_i, args.target_tp, args.target_lra)
        attempts.append(
            {
                "attempt": attempt_number,
                "loudnorm_i": args.target_i,
                "loudnorm_tp": processing_tp,
                "makeup_db": makeup_db,
                "limiter_db": limiter_db,
                "measured_output_i": after["input_i"],
                "measured_output_tp": after["input_tp"],
            }
        )
        loudness_ok = abs(float(after["input_i"]) - args.target_i) <= 0.3
        peak_ok = float(after["input_tp"]) <= args.target_tp + 0.1
        if loudness_ok and peak_ok:
            break
        makeup_db += args.target_i - float(after["input_i"])
        peak_excess = float(after["input_tp"]) - args.target_tp
        if peak_excess > 0:
            limiter_db = max(-9.0, limiter_db - peak_excess - 0.1)
    assert after is not None

    video_probe = probe(video)
    before_video = video_stream(video_probe)
    output_probe = probe(output)
    after_video = video_stream(output_probe)
    after_audio = audio_stream(output_probe)
    assert int(after_video["nb_read_frames"]) == int(before_video["nb_read_frames"])
    assert (after_video["width"], after_video["height"]) == (
        before_video["width"],
        before_video["height"],
    )
    assert Fraction(after_video["avg_frame_rate"]) == Fraction(
        before_video["avg_frame_rate"]
    )
    frame_duration = float(Fraction(1, 1) / Fraction(before_video["avg_frame_rate"]))
    assert (
        abs(float(output_probe["format"]["duration"]) - float(video_probe["format"]["duration"]))
        <= frame_duration
    )
    run(["ffmpeg", "-v", "error", "-i", output, "-f", "null", "-"])
    assert abs(float(after["input_i"]) - args.target_i) <= 0.3, after
    assert float(after["input_tp"]) <= args.target_tp + 0.1, after
    assert sha256(audio) == audio_hash, "Audio source changed during mux"

    report = {
        "status": "PASS",
        "video_master": str(video),
        "audio_source": str(audio),
        "audio_source_sha256": audio_hash,
        "output": str(output),
        "targets": {
            "integrated_lufs": args.target_i,
            "true_peak_dbtp": args.target_tp,
            "loudness_range_lu": args.target_lra,
        },
        "first_pass": before,
        "encode_attempts": attempts,
        "measured_output": after,
        "video": after_video,
        "audio": after_audio,
        "duration": output_probe["format"]["duration"],
        "full_decode": "PASS",
        "sha256": sha256(output),
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
