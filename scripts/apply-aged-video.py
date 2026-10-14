#!/usr/bin/env python3
"""Apply the exact insect-war AI-video aging chain to a complete video.

The output is a silent visual master.  Use
``blender/kaiju_liftoff/mux_loudnorm.py`` to add normalized audio without
re-encoding the video, allowing fast alternate loudness targets.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from fractions import Fraction
from pathlib import Path


GRADE = (
    "hue=s=0,"
    "curves=master='0/0.04 0.25/0.22 0.5/0.52 0.75/0.8 1/0.97',"
    "gblur=sigma=0.6,"
    "noise=alls=14:allf=t+u,"
    "vignette=PI/5.5:mode=backward:dither=1"
)


def run(args: list[object]) -> str:
    command = [str(arg) for arg in args]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(
            f"Command failed ({result.returncode}): {' '.join(command)}\n"
            f"{result.stdout[-2000:]}\n{result.stderr[-4000:]}"
        )
    return result.stdout


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def probe_video(path: Path) -> dict:
    payload = json.loads(
        run(
            [
                "ffprobe",
                "-v",
                "error",
                "-count_frames",
                "-select_streams",
                "v:0",
                "-show_entries",
                "format=duration:stream=width,height,avg_frame_rate,nb_read_frames,duration",
                "-of",
                "json",
                path,
            ]
        )
    )
    assert len(payload["streams"]) == 1, payload
    info = payload["streams"][0]
    info["format_duration"] = payload["format"]["duration"]
    return info


def extract_frame(video: Path, number: int, output: Path) -> None:
    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            video,
            "-vf",
            f"select=eq(n\\,{number - 1})",
            "-frames:v",
            "1",
            output,
        ]
    )
    assert output.is_file(), output


def frame_metrics(path: Path) -> dict:
    import cv2
    import numpy as np

    image = cv2.imread(str(path))
    assert image is not None
    channel_spread = image.max(axis=2).astype(np.int16) - image.min(axis=2).astype(np.int16)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape
    border = np.concatenate(
        (
            gray[: height // 8].ravel(),
            gray[-height // 8 :].ravel(),
            gray[:, : width // 8].ravel(),
            gray[:, -width // 8 :].ravel(),
        )
    )
    center = gray[height // 4 : 3 * height // 4, width // 4 : 3 * width // 4]
    return {
        "mean_rgb_channel_spread": float(channel_spread.mean()),
        "max_rgb_channel_spread": int(channel_spread.max()),
        "luma_mean": float(gray.mean()),
        "center_luma_mean": float(center.mean()),
        "border_luma_mean": float(border.mean()),
        "laplacian_variance": float(cv2.Laplacian(gray, cv2.CV_64F).var()),
    }


def signalstats(path: Path) -> dict:
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(path),
            "-vf",
            "select=eq(n\\,0),signalstats,metadata=print",
            "-frames:v",
            "1",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr[-4000:]
    values = {
        key: float(value)
        for key, value in re.findall(
            r"lavfi\.signalstats\.(SATAVG|YAVG|UAVG|VAVG)=([0-9.]+)", result.stderr
        )
    }
    assert set(values) == {"SATAVG", "YAVG", "UAVG", "VAVG"}, values
    return values


def comparison(before: Path, after: Path) -> dict:
    import cv2
    import numpy as np

    a = cv2.imread(str(before))
    b = cv2.imread(str(after))
    assert a is not None and b is not None and a.shape == b.shape
    delta = np.abs(a.astype(np.int16) - b.astype(np.int16))
    return {
        "rgb_mae": float(delta.mean()),
        "changed_channel_fraction": float(np.mean(delta != 0)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--reference-aged", type=Path)
    args = parser.parse_args()

    source = args.input.resolve()
    output = args.output.resolve()
    report_path = (args.report or output.with_suffix(".visual_qa.json")).resolve()
    assert source.is_file() and output != source
    if args.reference_aged:
        assert args.reference_aged.is_file(), args.reference_aged
    output.parent.mkdir(parents=True, exist_ok=True)
    source_hash = sha256(source)
    source_info = probe_video(source)

    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            source,
            "-map",
            "0:v:0",
            "-vf",
            GRADE,
            "-c:v",
            "libx264",
            "-preset",
            "slow",
            "-crf",
            "16",
            "-pix_fmt",
            "yuv420p",
            "-an",
            "-movflags",
            "+faststart",
            output,
        ]
    )

    output_info = probe_video(output)
    assert int(output_info["nb_read_frames"]) == int(source_info["nb_read_frames"])
    assert (output_info["width"], output_info["height"]) == (
        source_info["width"],
        source_info["height"],
    )
    assert Fraction(output_info["avg_frame_rate"]) == Fraction(source_info["avg_frame_rate"])
    frame_duration = float(Fraction(1, 1) / Fraction(source_info["avg_frame_rate"]))
    assert (
        abs(float(output_info["format_duration"]) - float(source_info["format_duration"]))
        <= frame_duration
    )
    run(["ffmpeg", "-v", "error", "-i", output, "-f", "null", "-"])
    assert sha256(source) == source_hash

    count = int(source_info["nb_read_frames"])
    spot_checks = []
    for label, number in (("a", count // 3), ("b", 2 * count // 3)):
        before = output.parent / f"{output.stem}_before_{label}.png"
        after = output.parent / f"{output.stem}_after_{label}.png"
        extract_frame(source, number, before)
        extract_frame(output, number, after)
        metrics = frame_metrics(after)
        difference = comparison(before, after)
        assert difference["rgb_mae"] > 5.0, difference
        spot_checks.append(
            {"frame": number, "before": str(before), "after": str(after), **metrics, **difference}
        )

    output_signalstats = signalstats(output)
    assert output_signalstats["SATAVG"] < 5.0, output_signalstats
    reference = None
    if args.reference_aged:
        reference_still = output.parent / f"{output.stem}_insect_war_reference.png"
        extract_frame(args.reference_aged.resolve(), 1, reference_still)
        reference = {
            "video": str(args.reference_aged.resolve()),
            "still": str(reference_still),
            "signalstats": signalstats(args.reference_aged.resolve()),
            **frame_metrics(reference_still),
        }
        assert reference["signalstats"]["SATAVG"] < 5.0, reference

    report = {
        "status": "PASS",
        "filter": GRADE,
        "input": str(source),
        "input_sha256": source_hash,
        "source_video": source_info,
        "output": str(output),
        "output_sha256": sha256(output),
        "output_video": output_info,
        "full_decode": "PASS",
        "output_signalstats": output_signalstats,
        "spot_checks": spot_checks,
        "insect_war_reference": reference,
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
