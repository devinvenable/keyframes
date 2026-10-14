"""Apply the recovered ``kaiju_1960s`` chain to a complete video.

This is the arbitrary-video counterpart to ``apply_grade_sequence.py``.  It
creates a silent graded master so audio targets can be changed later without
re-running Blender.  The input and its audio are never modified.

The visual chain is the T309 chain, unchanged:

    decoded RGB -> inverse AgX -> scene-linear EXR -> Blender 4.1.1
    kaiju_1960s compositor -> forward AgX PNG -> RGB -3 code-value trim

Example:

    python3 blender/kaiju_liftoff/apply_grade_video.py \
      --input /path/to/grid.mp4 \
      --output /path/to/grid_1960s_silent.mp4

The work directory is retained by default so an interrupted multi-hour pass is
resumable.  Use ``--cleanup`` only after the silent master has passed QA.
"""

from __future__ import annotations

import argparse
from collections import deque
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
from fractions import Fraction
from pathlib import Path


BLENDER_411 = Path("/home/devin/bin/blender-4.1.1-linux-x64/blender")
OCIO_CONFIG = Path(
    "/home/devin/bin/blender-5.1.2-linux-x64/5.1/datafiles/colormanagement/config.ocio"
)
PROFILE = Path("/home/devin/src/2026/voxel-shorts/scripts/post_process_profiles.py")
PROFILE_SHA256 = "adf204f3cc23499a93616a5c8abc2ac73e9f106663fcf2b9c2d899f0a6952c38"
PYTHON_DEPS = Path(
    "/home/devin/src/2026/videdit/work/liftoff_305/probe_apr25/python_deps"
)
TRIM_CODE_VALUES = 3


def run(args: list[object], **kwargs) -> str:
    command = [str(arg) for arg in args]
    result = subprocess.run(command, capture_output=True, text=True, **kwargs)
    if result.returncode:
        raise RuntimeError(
            f"Command failed ({result.returncode}): {' '.join(command)}\n"
            f"{result.stdout[-2000:]}\n{result.stderr[-4000:]}"
        )
    return result.stdout


def run_streaming(args: list[object]) -> str:
    """Run a long command with live combined output and return its transcript."""
    command = [str(arg) for arg in args]
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    lines = deque(maxlen=2000)
    for line in process.stdout:
        lines.append(line)
        if any(
            marker in line
            for marker in ("GRADE_BATCH ", "GRADE_BATCH_DONE", "Traceback", "Error")
        ):
            print(line, end="", flush=True)
    return_code = process.wait()
    transcript = "".join(lines)
    if return_code:
        raise RuntimeError(
            f"Command failed ({return_code}): {' '.join(command)}\n{transcript[-6000:]}"
        )
    return transcript


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def probe_video(path: Path) -> dict:
    output = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-count_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "format=duration:stream=width,height,r_frame_rate,avg_frame_rate,nb_read_frames,duration",
            "-of",
            "json",
            path,
        ]
    )
    payload = json.loads(output)
    streams = payload["streams"]
    assert len(streams) == 1, (path, streams)
    info = streams[0]
    info["format_duration"] = payload["format"]["duration"]
    return info


def valid_png(path: Path, width: int, height: int) -> bool:
    if not path.is_file():
        return False
    with path.open("rb") as handle:
        header = handle.read(24)
    if header[:8] != b"\x89PNG\r\n\x1a\n":
        return False
    dimensions = [int.from_bytes(header[index : index + 4], "big") for index in (16, 20)]
    return dimensions == [width, height]


def extract_frames(source: Path, frames_dir: Path, count: int, width: int, height: int) -> None:
    frames_dir.mkdir(parents=True, exist_ok=True)
    existing = list(frames_dir.glob("frame_*.png"))
    if len(existing) == count and all(valid_png(path, width, height) for path in existing):
        print(f"EXTRACT resume: {count} valid frames already present", flush=True)
        return
    for path in existing:
        path.unlink()
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
            "-fps_mode",
            "passthrough",
            "-start_number",
            "1",
            frames_dir / "frame_%06d.png",
        ]
    )
    extracted = sorted(frames_dir.glob("frame_*.png"))
    assert len(extracted) == count, (len(extracted), count)
    assert all(valid_png(path, width, height) for path in extracted)
    print(f"EXTRACT done: {count} frames", flush=True)


def inverse_agx(
    frames_dir: Path, exr_dir: Path, count: int, width: int, height: int
) -> dict:
    sys.path.insert(0, str(PYTHON_DEPS))
    os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
    import cv2
    import numpy as np
    import PyOpenColorIO as ocio

    config = ocio.Config.CreateFromFile(str(OCIO_CONFIG))
    transform = ocio.DisplayViewTransform(
        src="Linear Rec.709",
        display="sRGB",
        view="AgX",
        direction=ocio.TRANSFORM_DIR_INVERSE,
    )
    processor = config.getProcessor(transform).getDefaultCPUProcessor()
    exr_dir.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    clipped = 0.0
    completed = 0
    for number in range(1, count + 1):
        output = exr_dir / f"frame_{number:06}.exr"
        if output.is_file() and output.stat().st_size > width * height:
            completed += 1
            continue
        image = cv2.imread(str(frames_dir / f"frame_{number:06}.png"))
        assert image is not None and image.shape[:2] == (height, width), number
        linear = np.ascontiguousarray(image[:, :, ::-1], dtype=np.float32) / 255
        processor.applyRGB(linear)
        assert cv2.imwrite(str(output), linear[:, :, ::-1])
        clipped = max(clipped, float(np.mean(image == 255)))
        completed += 1
        if completed % 24 == 0 or completed == count:
            print(
                f"INVERSE {completed}/{count} {time.monotonic() - start:.1f}s",
                flush=True,
            )
    return {
        "seconds": time.monotonic() - start,
        "ocio_version": ocio.__version__,
        "config_sha256": sha256(OCIO_CONFIG),
        "worst_clipped_channel_fraction_this_run": clipped,
    }


def blender_batch(argv: list[str]) -> None:
    import bpy

    parser = argparse.ArgumentParser()
    parser.add_argument("--exr-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument("--count", type=int, required=True)
    args = parser.parse_args(argv)

    assert bpy.app.version[:2] == (4, 1), bpy.app.version_string
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.render.resolution_x = args.width
    scene.render.resolution_y = args.height
    scene.render.resolution_percentage = 100
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "None"

    spec = importlib.util.spec_from_file_location("historical_profile", args.profile)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._apply_kaiju_1960s(
        scene,
        chromatic_aberration=0.018,
        grain_intensity=0.05,
        vignette_strength=0.25,
        glare_strength=0.35,
    )
    tree = scene.node_tree
    render_layer = next(node for node in tree.nodes if node.type == "R_LAYERS")
    destinations = [link.to_socket for link in render_layer.outputs["Image"].links]
    tree.nodes.remove(render_layer)
    image_node = tree.nodes.new("CompositorNodeImage")
    for socket in destinations:
        tree.links.new(image_node.outputs["Image"], socket)

    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    args.out_dir.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    for number in range(1, args.count + 1):
        output = args.out_dir / f"frame_{number:06}.png"
        if valid_png(output, args.width, args.height):
            continue
        image = bpy.data.images.load(
            str((args.exr_dir / f"frame_{number:06}.exr").resolve())
        )
        image_node.image = image
        scene.render.filepath = str(output.resolve())
        bpy.ops.render.render(write_still=True)
        bpy.data.images.remove(image)
        if number % 24 == 0 or number == args.count:
            print(
                f"GRADE_BATCH {number}/{args.count} {time.monotonic() - start:.1f}s",
                flush=True,
            )
    print(
        "GRADE_BATCH_DONE",
        json.dumps(
            {
                "frames": args.count,
                "seconds": time.monotonic() - start,
                "blender_version": bpy.app.version_string,
            }
        ),
        flush=True,
    )


def trim_frames(
    graded_dir: Path, final_dir: Path, count: int, width: int, height: int
) -> None:
    os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
    import cv2

    final_dir.mkdir(parents=True, exist_ok=True)
    for number in range(1, count + 1):
        output = final_dir / f"frame_{number:06}.png"
        if valid_png(output, width, height):
            continue
        image = cv2.imread(str(graded_dir / f"frame_{number:06}.png"))
        assert image is not None and image.dtype.name == "uint8", number
        assert cv2.imwrite(str(output), cv2.subtract(image, TRIM_CODE_VALUES))
        if number % 120 == 0 or number == count:
            print(f"TRIM {number}/{count}", flush=True)


def encode_silent(
    frames_dir: Path, output: Path, frame_rate: str, count: int
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-framerate",
            frame_rate,
            "-start_number",
            "1",
            "-i",
            frames_dir / "frame_%06d.png",
            "-frames:v",
            count,
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


def visual_comparison(source: Path, graded: Path) -> dict:
    import cv2
    import numpy as np

    before = cv2.imread(str(source))
    after = cv2.imread(str(graded))
    assert before is not None and after is not None and before.shape == after.shape
    delta = np.abs(before.astype(np.int16) - after.astype(np.int16))
    return {
        "rgb_mae": float(delta.mean()),
        "rgb_max_difference": int(delta.max()),
        "changed_channel_fraction": float(np.mean(delta != 0)),
    }


def cleanup_work(work_dir: Path) -> None:
    # The directory is derived from --output and contains only generated intermediates.
    if work_dir.is_dir():
        shutil.rmtree(work_dir)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--cleanup", action="store_true")
    args = parser.parse_args()

    source = args.input.resolve()
    output = args.output.resolve()
    assert source.is_file(), source
    assert output != source, "Output must not overwrite the input"
    assert sha256(PROFILE) == PROFILE_SHA256, "Historical profile hash changed"
    for dependency in (BLENDER_411, OCIO_CONFIG, PYTHON_DEPS):
        assert dependency.exists(), dependency

    work = (args.work_dir or output.with_suffix(".work")).resolve()
    report_path = (args.report or output.with_suffix(".visual_qa.json")).resolve()
    input_hash = sha256(source)
    info = probe_video(source)
    width, height = int(info["width"]), int(info["height"])
    frame_rate = info["avg_frame_rate"]
    count = int(info["nb_read_frames"])
    assert width > 0 and height > 0 and count > 0
    assert Fraction(frame_rate) > 0

    source_frames = work / "source_frames"
    exr_frames = work / "inverse_agx_exr"
    graded_frames = work / "graded_frames"
    final_frames = work / "graded_trimmed_frames"
    extract_frames(source, source_frames, count, width, height)

    report = {
        "status": "RUNNING",
        "chain": (
            "decoded RGB -> inverse AgX (Blender 5.1.2 OCIO) -> scene-linear EXR "
            "-> kaiju_1960s compositor (Blender 4.1.1) -> forward AgX -> RGB -3 trim"
        ),
        "input": str(source),
        "input_sha256": input_hash,
        "source_video": info,
        "profile_sha256": PROFILE_SHA256,
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n")

    report["inverse"] = inverse_agx(source_frames, exr_frames, count, width, height)
    blender_output = run_streaming(
        [
            BLENDER_411,
            "--background",
            "--factory-startup",
            "--python",
            __file__,
            "--",
            "--blender-batch",
            "--exr-dir",
            exr_frames,
            "--out-dir",
            graded_frames,
            "--profile",
            PROFILE,
            "--width",
            width,
            "--height",
            height,
            "--count",
            count,
        ]
    )
    marker = blender_output.rsplit("GRADE_BATCH_DONE", 1)[1].strip().splitlines()[0]
    report["compositor"] = json.loads(marker)
    trim_frames(graded_frames, final_frames, count, width, height)
    encode_silent(final_frames, output, frame_rate, count)

    output_info = probe_video(output)
    assert int(output_info["nb_read_frames"]) == count, output_info
    assert (int(output_info["width"]), int(output_info["height"])) == (width, height)
    assert Fraction(output_info["avg_frame_rate"]) == Fraction(frame_rate), output_info
    frame_duration = float(Fraction(1, 1) / Fraction(frame_rate))
    assert (
        abs(float(output_info["format_duration"]) - float(info["format_duration"]))
        <= frame_duration
    )
    run(["ffmpeg", "-v", "error", "-i", output, "-f", "null", "-"])
    assert sha256(source) == input_hash, "Input changed during processing"

    stills = []
    for label, number in (("a", max(1, count // 3)), ("b", max(1, 2 * count // 3))):
        before = output.parent / f"{output.stem}_before_{label}.png"
        after = output.parent / f"{output.stem}_after_{label}.png"
        shutil.copy2(source_frames / f"frame_{number:06}.png", before)
        shutil.copy2(final_frames / f"frame_{number:06}.png", after)
        comparison = visual_comparison(before, after)
        assert comparison["rgb_mae"] > 1.0, comparison
        stills.append(
            {
                "frame": number,
                "before": str(before),
                "after": str(after),
                **comparison,
            }
        )

    report.update(
        {
            "silent_master": {**output_info, "path": str(output), "sha256": sha256(output)},
            "spot_checks": stills,
            "full_decode": "PASS",
            "input_unchanged": True,
            "status": "PASS",
        }
    )
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    if args.cleanup:
        cleanup_work(work)
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    if "--blender-batch" in sys.argv:
        blender_batch(
            [value for value in sys.argv[sys.argv.index("--") + 1 :] if value != "--blender-batch"]
        )
    else:
        main()
