#!/usr/bin/env python3
"""Pixel-level audit helper for Typeless Local screen recordings.

This intentionally avoids OpenCV so it can run in the existing Jarvis venv. It
uses ffmpeg for frame extraction and Pillow for image inspection.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median
from typing import Iterable

try:
    from PIL import Image
except ImportError as exc:  # pragma: no cover - environment guard
    raise SystemExit("Pillow is required: uv pip install Pillow") from exc


@dataclass(frozen=True)
class Box:
    x: int
    y: int
    width: int
    height: int
    area: int


@dataclass(frozen=True)
class Span:
    start: float
    end: float
    frames: int


@dataclass(frozen=True)
class WaveformMetrics:
    frames: int
    mean_avg_height: float
    median_avg_height: float
    low_ratio_avg_le_4px: float
    unique_shapes: int
    mean_symmetry_delta: float
    center_peak_ratio: float
    max_height_median: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare Typeless UI geometry and waveform metrics from screen recordings.")
    parser.add_argument("--official", required=True, type=Path, help="Official Typeless .mov/.mp4 recording.")
    parser.add_argument("--local", type=Path, help="Local Typeless .mov/.mp4 recording to compare.")
    parser.add_argument("--fps", type=float, default=10.0, help="Frame sampling FPS for audit extraction.")
    parser.add_argument("--workdir", type=Path, help="Directory for extracted frames. Defaults to a process-specific directory under /tmp.")
    parser.add_argument("--ffmpeg", default=shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg", help="ffmpeg executable path.")
    parser.add_argument("--reuse", action="store_true", help="Reuse already extracted frames when present.")
    parser.add_argument("--gate", action="store_true", help="Exit non-zero when the local recording fails pixel-audit thresholds.")
    args = parser.parse_args()
    workdir_was_provided = args.workdir is not None
    if args.reuse and not workdir_was_provided:
        parser.error("--reuse requires --workdir because default workdirs are process-specific.")
    if not workdir_was_provided:
        args.workdir = Path(f"/tmp/typeless-video-audit-{os.getpid()}")
    return args


def run_ffmpeg(ffmpeg: str, video: Path, out_dir: Path, fps: float, reuse: bool) -> None:
    if out_dir.exists() and not reuse:
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if reuse and any(out_dir.glob("f_*.png")):
        return
    pattern = str(out_dir / "f_%04d.png")
    command = [ffmpeg, "-y", "-loglevel", "error", "-i", str(video), "-vf", f"fps={fps}", pattern]
    subprocess.run(command, check=True)


def dark_components(image: Image.Image, *, threshold: int = 55, lower_fraction: float = 0.70) -> list[Box]:
    rgb = image.convert("RGB")
    width, height = rgb.size
    pixels = rgb.load()
    start_y = int(height * lower_fraction)
    mask = bytearray(width * height)

    for y in range(start_y, height):
        for x in range(width):
            red, green, blue = pixels[x, y]
            if red < threshold and green < threshold and blue < threshold:
                mask[y * width + x] = 1

    seen = bytearray(width * height)
    boxes: list[Box] = []
    for y in range(start_y, height):
        for x in range(width):
            index = y * width + x
            if not mask[index] or seen[index]:
                continue
            stack = [(x, y)]
            seen[index] = 1
            min_x = max_x = x
            min_y = max_y = y
            area = 0
            touches_edge = False
            while stack:
                current_x, current_y = stack.pop()
                area += 1
                min_x = min(min_x, current_x)
                max_x = max(max_x, current_x)
                min_y = min(min_y, current_y)
                max_y = max(max_y, current_y)
                if current_x in {0, width - 1} or current_y in {0, height - 1}:
                    touches_edge = True
                for next_x, next_y in (
                    (current_x + 1, current_y),
                    (current_x - 1, current_y),
                    (current_x, current_y + 1),
                    (current_x, current_y - 1),
                ):
                    if 0 <= next_x < width and 0 <= next_y < height:
                        next_index = next_y * width + next_x
                        if mask[next_index] and not seen[next_index]:
                            seen[next_index] = 1
                            stack.append((next_x, next_y))

            if area >= 80 and not touches_edge:
                boxes.append(Box(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1, area))

    return sorted(boxes, key=lambda box: box.area, reverse=True)


def classify_bottom_box(boxes: Iterable[Box], min_width: int, max_width: int) -> Box | None:
    candidates = [
        box
        for box in boxes
        if min_width <= box.width <= max_width and 48 <= box.height <= 85 and box.area >= 1000
    ]
    return max(candidates, key=lambda box: box.area) if candidates else None


def copy_fallback_rows(image: Image.Image, *, threshold: int = 60, min_rows: int = 40) -> tuple[int, int] | None:
    rgb = image.convert("RGB")
    width, height = rgb.size
    pixels = rgb.load()
    rows: list[int] = []
    for y in range(int(height * 0.30), int(height * 0.86)):
        dark_count = 0
        for x in range(width):
            red, green, blue = pixels[x, y]
            if red < threshold and green < threshold and blue < threshold:
                dark_count += 1
        if dark_count > width * 0.75:
            rows.append(y)
    if len(rows) < min_rows:
        component = copy_fallback_component(image)
        if component is None:
            return None
        return component.y, component.y + component.height - 1
    return rows[0], rows[-1]


def copy_fallback_component(image: Image.Image) -> Box | None:
    """Detect a centered Typeless alert when the recording includes wider context."""

    width, height = image.size
    candidates = []
    for box in dark_components(image, threshold=65, lower_fraction=0.30):
        if box.width < 300 or box.height < 90:
            continue
        if box.width > min(width * 0.95, 900):
            continue
        if box.area < 25000:
            continue
        if box.y < height * 0.30 or box.y + box.height > height * 0.98:
            continue
        if box.width / max(box.height, 1) < 2.0:
            continue
        candidates.append(box)
    return max(candidates, key=lambda box: box.area) if candidates else None


def contiguous_spans(times: list[float], frame_step: float) -> list[Span]:
    if not times:
        return []
    spans: list[Span] = []
    start = previous = times[0]
    count = 1
    for time in times[1:]:
        if time - previous <= frame_step * 1.5:
            previous = time
            count += 1
            continue
        spans.append(Span(round(start, 3), round(previous, 3), count))
        start = previous = time
        count = 1
    spans.append(Span(round(start, 3), round(previous, 3), count))
    return spans


def waveform_heights(image: Image.Image, box: Box) -> list[int]:
    rgb = image.convert("RGB")
    pixels = rgb.load()
    wave_x = box.x + 76
    heights: list[int] = []
    for index in range(10):
        bar_x0 = round(wave_x + index * 8)
        bar_x1 = bar_x0 + 4
        bright_rows: list[int] = []
        for y in range(box.y, box.y + box.height):
            has_bright_pixel = False
            for x in range(bar_x0, bar_x1):
                if 0 <= x < rgb.size[0]:
                    red, green, blue = pixels[x, y]
                    if red > 110 and green > 110 and blue > 110:
                        has_bright_pixel = True
                        break
            if has_bright_pixel:
                bright_rows.append(y)
        heights.append(max(bright_rows) - min(bright_rows) + 1 if bright_rows else 0)
    return heights


def build_waveform_metrics(rows: list[list[int]]) -> WaveformMetrics | None:
    valid = [row for row in rows if sum(row) > 0]
    if not valid:
        return None

    averages = [sum(row) / len(row) for row in valid]
    rounded_shapes = {tuple(round(value / 2) * 2 for value in row) for row in valid}
    symmetry = [sum(abs(row[index] - row[-1 - index]) for index in range(5)) / 5 for row in valid]
    center_ratios = [max(row[4], row[5]) / (max(row) or 1) for row in valid]
    max_heights = [max(row) for row in valid]
    return WaveformMetrics(
        frames=len(valid),
        mean_avg_height=round(sum(averages) / len(averages), 2),
        median_avg_height=round(median(averages), 2),
        low_ratio_avg_le_4px=round(sum(value <= 4 for value in averages) / len(averages), 2),
        unique_shapes=len(rounded_shapes),
        mean_symmetry_delta=round(sum(symmetry) / len(symmetry), 2),
        center_peak_ratio=round(sum(center_ratios) / len(center_ratios), 2),
        max_height_median=round(median(max_heights), 2),
    )


def summarize_frames(frame_dir: Path, fps: float) -> dict[str, object]:
    recording_times: list[float] = []
    thinking_times: list[float] = []
    copy_times: list[float] = []
    recording_boxes: list[Box] = []
    thinking_boxes: list[Box] = []
    waveform_rows: list[list[int]] = []

    for frame_path in sorted(frame_dir.glob("f_*.png")):
        frame_index = int(frame_path.stem.split("_")[1])
        time = (frame_index - 1) / fps
        image = Image.open(frame_path)
        boxes = dark_components(image)
        recording_box = classify_bottom_box(boxes, 210, 250)
        thinking_box = classify_bottom_box(boxes, 165, 195)
        copy_rows = copy_fallback_rows(image)

        if recording_box is not None:
            recording_times.append(time)
            recording_boxes.append(recording_box)
            waveform_rows.append(waveform_heights(image, recording_box))
        if thinking_box is not None:
            thinking_times.append(time)
            thinking_boxes.append(thinking_box)
        if copy_rows is not None:
            copy_times.append(time)

    return {
        "recording_spans": [asdict(span) for span in contiguous_spans(recording_times, 1 / fps)],
        "thinking_spans": [asdict(span) for span in contiguous_spans(thinking_times, 1 / fps)],
        "copy_fallback_spans": [asdict(span) for span in contiguous_spans(copy_times, 1 / fps)],
        "recording_bbox_median": median_box(recording_boxes),
        "thinking_bbox_median": median_box(thinking_boxes),
        "waveform": asdict(build_waveform_metrics(waveform_rows)) if waveform_rows else None,
    }


def median_box(boxes: list[Box]) -> dict[str, float] | None:
    if not boxes:
        return None
    return {
        "x": round(median(box.x for box in boxes), 2),
        "y": round(median(box.y for box in boxes), 2),
        "width": round(median(box.width for box in boxes), 2),
        "height": round(median(box.height for box in boxes), 2),
    }


def compare_metrics(official: dict[str, object], local: dict[str, object] | None) -> dict[str, object] | None:
    if local is None:
        return None
    comparison: dict[str, object] = {}
    for key in ("recording_bbox_median", "thinking_bbox_median"):
        official_box = official.get(key)
        local_box = local.get(key)
        if isinstance(official_box, dict) and isinstance(local_box, dict):
            comparison[f"{key}_delta"] = {
                dimension: round(float(local_box[dimension]) - float(official_box[dimension]), 2)
                for dimension in ("x", "y", "width", "height")
            }
    official_wave = official.get("waveform")
    local_wave = local.get("waveform")
    if isinstance(official_wave, dict) and isinstance(local_wave, dict):
        comparison["waveform_delta"] = {
            key: round(float(local_wave[key]) - float(official_wave[key]), 2)
            for key in (
                "mean_avg_height",
                "median_avg_height",
                "low_ratio_avg_le_4px",
                "unique_shapes",
                "mean_symmetry_delta",
                "center_peak_ratio",
                "max_height_median",
            )
        }
    return comparison


def gate_failures(result: dict[str, object]) -> list[str]:
    """Return human-readable failures for the final pixel audit gate."""

    local = result.get("local")
    comparison = result.get("comparison")
    if not isinstance(local, dict):
        return ["local recording was not provided"]
    if not isinstance(comparison, dict):
        return ["comparison metrics are missing"]

    failures: list[str] = []
    official = result.get("official")
    if isinstance(official, dict):
        if official.get("copy_fallback_spans") and not local.get("copy_fallback_spans"):
            failures.append("copy fallback spans are missing from local recording")

    for key in ("recording_bbox_median", "thinking_bbox_median"):
        if local.get(key) is None:
            failures.append(f"{key} is missing from local recording")

    for key in ("recording_bbox_median_delta", "thinking_bbox_median_delta"):
        delta = comparison.get(key)
        if not isinstance(delta, dict):
            continue
        for dimension in ("x", "y", "width", "height"):
            value = abs(float(delta.get(dimension, 0.0)))
            if value > 2.0:
                failures.append(f"{key}.{dimension} delta {value:.2f}px exceeds 2px")

    waveform_delta = comparison.get("waveform_delta")
    if not isinstance(waveform_delta, dict):
        failures.append("waveform comparison is missing")
        return failures

    thresholds = {
        "mean_avg_height": 2.5,
        "median_avg_height": 4.0,
        "low_ratio_avg_le_4px": 0.25,
        "unique_shapes": 28.0,
        "mean_symmetry_delta": 1.5,
        "center_peak_ratio": 0.15,
        "max_height_median": 6.0,
    }
    for metric, threshold in thresholds.items():
        value = abs(float(waveform_delta.get(metric, 0.0)))
        if value > threshold:
            failures.append(f"waveform_delta.{metric} {value:.2f} exceeds {threshold}")
    return failures


def main() -> None:
    args = parse_args()
    official_frames = args.workdir / "official_frames"
    run_ffmpeg(args.ffmpeg, args.official, official_frames, args.fps, args.reuse)
    official_summary = summarize_frames(official_frames, args.fps)

    local_summary = None
    if args.local is not None:
        local_frames = args.workdir / "local_frames"
        run_ffmpeg(args.ffmpeg, args.local, local_frames, args.fps, args.reuse)
        local_summary = summarize_frames(local_frames, args.fps)

    result: dict[str, object] = {
        "fps": args.fps,
        "official": official_summary,
        "local": local_summary,
        "comparison": compare_metrics(official_summary, local_summary),
    }
    failures = gate_failures(result) if args.gate else []
    if args.gate:
        result["gate"] = {"passed": not failures, "failures": failures}
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if args.gate and failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
