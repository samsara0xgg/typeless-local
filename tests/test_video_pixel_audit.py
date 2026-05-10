from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

from PIL import Image


def _load_audit_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "video_pixel_audit.py"
    spec = importlib.util.spec_from_file_location("video_pixel_audit", module_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_copy_fallback_rows_rejects_thin_dark_window_edge() -> None:
    audit = _load_audit_module()
    image = Image.new("RGB", (200, 160), (244, 244, 244))
    pixels = image.load()
    for y in (80, 81):
        for x in range(200):
            pixels[x, y] = (0, 0, 0)

    assert audit.copy_fallback_rows(image) is None


def test_copy_fallback_rows_accepts_large_dark_sheet() -> None:
    audit = _load_audit_module()
    image = Image.new("RGB", (200, 160), (244, 244, 244))
    pixels = image.load()
    for y in range(60, 120):
        for x in range(200):
            pixels[x, y] = (24, 22, 23)

    assert audit.copy_fallback_rows(image) == (60, 119)


def test_copy_fallback_rows_accepts_centered_alert_component() -> None:
    audit = _load_audit_module()
    image = Image.new("RGB", (1000, 800), (244, 244, 244))
    pixels = image.load()
    for y in range(570, 690):
        for x in range(320, 680):
            pixels[x, y] = (29, 26, 26)

    assert audit.copy_fallback_rows(image) == (570, 689)


def test_parse_args_uses_process_specific_default_workdir(monkeypatch) -> None:
    audit = _load_audit_module()
    monkeypatch.setattr(sys, "argv", ["video_pixel_audit.py", "--official", "official.mov"])

    args = audit.parse_args()

    assert str(args.workdir).startswith("/tmp/typeless-video-audit-")


def test_parse_args_requires_workdir_for_reuse(monkeypatch) -> None:
    audit = _load_audit_module()
    monkeypatch.setattr(
        sys,
        "argv",
        ["video_pixel_audit.py", "--official", "official.mov", "--reuse"],
    )

    try:
        audit.parse_args()
    except SystemExit as exc:
        assert exc.code == 2
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("parse_args should reject --reuse without --workdir")


def test_gate_failures_accepts_close_metrics() -> None:
    audit = _load_audit_module()
    result = {
        "official": {"copy_fallback_spans": [{"start": 1, "end": 2, "frames": 3}]},
        "local": {
            "copy_fallback_spans": [{"start": 1, "end": 2, "frames": 3}],
            "recording_bbox_median": {"width": 228, "height": 64},
            "thinking_bbox_median": {"width": 180, "height": 64},
        },
        "comparison": {
            "recording_bbox_median_delta": {"width": 0, "height": 0},
            "thinking_bbox_median_delta": {"width": 1, "height": -1},
            "waveform_delta": {
                "mean_avg_height": 1.0,
                "median_avg_height": 2.0,
                "low_ratio_avg_le_4px": 0.1,
                "unique_shapes": 4,
                "mean_symmetry_delta": 0.5,
                "center_peak_ratio": 0.05,
                "max_height_median": 2.0,
            },
        },
    }

    assert audit.gate_failures(result) == []


def test_gate_failures_reports_missing_visual_requirements() -> None:
    audit = _load_audit_module()
    result = {
        "official": {"copy_fallback_spans": [{"start": 1, "end": 2, "frames": 3}]},
        "local": {
            "copy_fallback_spans": [],
            "recording_bbox_median": None,
            "thinking_bbox_median": {"width": 190, "height": 64},
        },
        "comparison": {
            "thinking_bbox_median_delta": {"width": 10, "height": 0},
            "recording_bbox_median_delta": {"x": 5, "y": 0, "width": 0, "height": 0},
            "waveform_delta": {
                "mean_avg_height": 5.0,
                "median_avg_height": 0,
                "low_ratio_avg_le_4px": 0,
                "unique_shapes": 0,
                "mean_symmetry_delta": 0,
                "center_peak_ratio": 0,
                "max_height_median": 0,
            },
        },
    }

    failures = audit.gate_failures(result)

    assert "copy fallback spans are missing from local recording" in failures
    assert "recording_bbox_median is missing from local recording" in failures
    assert "recording_bbox_median_delta.x delta 5.00px exceeds 2px" in failures
    assert "thinking_bbox_median_delta.width delta 10.00px exceeds 2px" in failures
    assert "waveform_delta.mean_avg_height 5.00 exceeds 2.5" in failures
