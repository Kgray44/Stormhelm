from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / ".artifacts" / "voice_ar11_sync_offset_sweep"
DEFAULT_OFFSETS = [0, -60, -100, -140, -180]
BLOCKING_CLASSES = {
    "delayed_speaking_entry",
    "speaking_stuck_after_audio",
    "false_speaking_without_audio",
    "voice_visual_active_flap",
    "stale_broad_voice_snapshot_overrides_hot_path",
    "anchor_state_latch_bug",
    "anchor_release_bug",
    "sync_measurement_stale_authoritative_rows",
    "fog_or_shared_clock_starvation",
    "render_cadence_problem",
    "canvas_paint_backend_bottleneck",
}

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from run_voice_ar5_live_kraken_probe import (  # noqa: E402
    _clamp_voice_visual_offset_ms,
    _normalize_qsg_visual_approval,
)
from stormhelm.core.voice.live_kraken_probe import (  # noqa: E402
    assert_no_raw_audio_payload,
    sanitize_kraken_payload,
)


def parse_offsets(value: str | Sequence[int] | None) -> list[int]:
    if value is None:
        candidates: Sequence[int | str] = DEFAULT_OFFSETS
    elif isinstance(value, str):
        candidates = [part.strip() for part in value.split(",") if part.strip()]
    else:
        candidates = list(value)
    offsets: list[int] = []
    for item in candidates:
        offset = _clamp_voice_visual_offset_ms(item)
        if offset not in offsets:
            offsets.append(offset)
    return offsets or [0]


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _scenario_reports(report: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows = report.get("scenario_reports")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return []
    return [row for row in rows if isinstance(row, Mapping)]


def _scenario_summary(report: Mapping[str, Any], scenario: str) -> dict[str, Any]:
    matches = [
        row for row in _scenario_reports(report)
        if str(row.get("scenario") or "") == scenario
    ]
    if not matches:
        return {"scenario": scenario, "present": False, "raw_audio_present": False}
    row = matches[0]
    render = row.get("render_metrics") if isinstance(row.get("render_metrics"), Mapping) else {}
    lifetime = row.get("speaking_lifetime") if isinstance(row.get("speaking_lifetime"), Mapping) else {}
    ranges = row.get("ranges") if isinstance(row.get("ranges"), Mapping) else {}
    alignment = (
        row.get("audio_visual_alignment")
        if isinstance(row.get("audio_visual_alignment"), Mapping)
        else {}
    )
    final_range = ranges.get("finalSpeakingEnergy") if isinstance(ranges.get("finalSpeakingEnergy"), Mapping) else {}
    blob_range = ranges.get("blobScaleDrive") if isinstance(ranges.get("blobScaleDrive"), Mapping) else {}
    return sanitize_kraken_payload(
        {
            "scenario": scenario,
            "present": True,
            "classification": list(row.get("classification") or []),
            "paint_fps": render.get("anchorPaintFpsDuringSpeaking"),
            "dynamic_paint_fps": render.get("dynamicCorePaintFpsDuringSpeaking"),
            "start_delay_ms": lifetime.get("anchor_speaking_start_delay_ms"),
            "release_tail_ms": lifetime.get("anchor_release_tail_ms"),
            "finalSpeakingEnergy_span": final_range.get("span"),
            "blobScaleDrive_span": blob_range.get("span"),
            "direct_pcm_to_blob_lag_ms": alignment.get("perceptual_sync_best_lag_ms"),
            "direct_pcm_to_blob_correlation": alignment.get("perceptual_sync_correlation"),
            "correlation_confidence": alignment.get("sync_confidence"),
            "stage_latency_estimate_ms": alignment.get("stage_latency_estimate_ms"),
            "perceptual_sync_status": alignment.get("perceptual_sync_status"),
            "perceptual_sync_basis": alignment.get("perceptual_sync_basis"),
            "syncMeasurementConfidence": alignment.get(
                "syncMeasurementConfidence",
                alignment.get("sync_confidence"),
            ),
            "syncMeasurementRejectionReason": alignment.get(
                "syncMeasurementRejectionReason"
            ),
            "syncOffsetCandidateSafe": alignment.get("syncOffsetCandidateSafe"),
            "syncOffsetCandidateRejectedReason": alignment.get(
                "syncOffsetCandidateRejectedReason"
            ),
            "visual_appears": alignment.get("perceptual_sync_status"),
            "raw_audio_present": False,
        }
    )


def extract_offset_result(report: Mapping[str, Any], *, offset_ms: int, output_dir: Path | None = None) -> dict[str, Any]:
    scenarios = {
        name: _scenario_summary(report, name)
        for name in ("single_spoken_response", "repeated_speech", "renderer_comparison")
    }
    classes = {str(item) for item in report.get("classification", []) if str(item)}
    for item in scenarios.values():
        classes.update(str(value) for value in item.get("classification", []) if str(value))
    paint_values = [
        _number(item.get("paint_fps"))
        for item in scenarios.values()
        if item.get("present")
    ]
    return sanitize_kraken_payload(
        {
            "visual_offset_ms": int(offset_ms),
            "output_dir": str(output_dir) if output_dir is not None else None,
            "classification": sorted(classes) or ["unknown"],
            "scenarios": scenarios,
            "min_paint_fps": min([value for value in paint_values if value is not None], default=None),
            "raw_audio_present": False,
        }
    )


def _scenario_improved(candidate: Mapping[str, Any], baseline: Mapping[str, Any]) -> bool:
    candidate_lag = _number(candidate.get("direct_pcm_to_blob_lag_ms"))
    baseline_lag = _number(baseline.get("direct_pcm_to_blob_lag_ms"))
    if candidate_lag is not None and baseline_lag is not None:
        return abs(candidate_lag) <= max(0.0, abs(baseline_lag) - 25.0)
    candidate_classes = {str(item) for item in candidate.get("classification", [])}
    baseline_classes = {str(item) for item in baseline.get("classification", [])}
    return "sync_visual_late" in baseline_classes and "sync_visual_late" not in candidate_classes


def _scenario_worsened(candidate: Mapping[str, Any], baseline: Mapping[str, Any]) -> bool:
    candidate_lag = _number(candidate.get("direct_pcm_to_blob_lag_ms"))
    baseline_lag = _number(baseline.get("direct_pcm_to_blob_lag_ms"))
    if candidate_lag is not None and baseline_lag is not None:
        return abs(candidate_lag) > abs(baseline_lag) + 80.0
    candidate_classes = {str(item) for item in candidate.get("classification", [])}
    baseline_classes = {str(item) for item in baseline.get("classification", [])}
    return "sync_visual_early" in candidate_classes and "sync_visual_early" not in baseline_classes


def summarize_offset_sweep(
    results: Sequence[Mapping[str, Any]],
    *,
    visual_approval: str,
    apply_requested: bool = False,
    operator_sync_approved: bool = False,
    operator_note: str = "",
) -> dict[str, Any]:
    sanitized = [sanitize_kraken_payload(result) for result in results]
    baseline = next((item for item in sanitized if int(item.get("visual_offset_ms") or 0) == 0), None)
    recommended_offset: int | None = None
    recommendation_reason = "baseline_missing"
    if baseline is not None:
        recommendation_reason = "no_offset_met_application_gate"
        for candidate in sorted(
            [item for item in sanitized if int(item.get("visual_offset_ms") or 0) != 0],
            key=lambda item: abs(int(item.get("visual_offset_ms") or 0)),
        ):
            classes = {str(item) for item in candidate.get("classification", [])}
            if classes & BLOCKING_CLASSES:
                continue
            scenarios = candidate.get("scenarios") if isinstance(candidate.get("scenarios"), Mapping) else {}
            baseline_scenarios = baseline.get("scenarios") if isinstance(baseline.get("scenarios"), Mapping) else {}
            improved = 0
            worsened = 0
            medium_or_high = 0
            confident_sync_late = False
            unsafe_sync_candidate = False
            for name in ("single_spoken_response", "repeated_speech", "renderer_comparison"):
                scenario = scenarios.get(name) if isinstance(scenarios.get(name), Mapping) else {}
                base = baseline_scenarios.get(name) if isinstance(baseline_scenarios.get(name), Mapping) else {}
                confidence = str(scenario.get("correlation_confidence") or "").lower()
                if scenario.get("syncOffsetCandidateSafe") is False:
                    unsafe_sync_candidate = True
                if confidence in {"medium", "high"}:
                    medium_or_high += 1
                    if "sync_visual_late" in {
                        str(item) for item in scenario.get("classification", [])
                    }:
                        confident_sync_late = True
                if _scenario_improved(scenario, base):
                    improved += 1
                if _scenario_worsened(scenario, base):
                    worsened += 1
            min_paint = _number(candidate.get("min_paint_fps"))
            if (
                improved >= 2
                and worsened == 0
                and medium_or_high >= 2
                and not confident_sync_late
                and not unsafe_sync_candidate
                and (min_paint is None or min_paint >= 30.0)
            ):
                recommended_offset = int(candidate.get("visual_offset_ms") or 0)
                recommendation_reason = "smallest_offset_improved_two_scenarios_without_regression"
                break
    approval = _normalize_qsg_visual_approval(visual_approval)
    apply_allowed = bool(
        apply_requested
        and operator_sync_approved
        and approval == "approved"
        and recommended_offset is not None
    )
    return sanitize_kraken_payload(
        {
            "probe": "voice_ar11_sync_offset_sweep",
            "qsg_visual_approval": approval,
            "sync_calibration_results": sanitized,
            "recommended_visual_offset_ms": recommended_offset,
            "recommendation_reason": recommendation_reason,
            "apply_requested": bool(apply_requested),
            "operator_sync_approved": bool(operator_sync_approved),
            "operator_sync_note": str(operator_note or ""),
            "recommended_visual_offset_ms": (
                recommended_offset if recommended_offset is not None else "none"
            ),
            "recommended_visual_offset_ms_value": (
                recommended_offset if recommended_offset is not None else "none"
            ),
            "visual_offset_applied_ms": recommended_offset if apply_allowed else 0,
            "offset_applied": bool(apply_allowed),
            "rollback_config": "[voice.visual_meter]\\nvisual_offset_ms = 0",
            "raw_audio_present": False,
        }
    )


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(sanitize_kraken_payload(payload), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _write_default_config_visual_offset(offset_ms: int) -> None:
    path = PROJECT_ROOT / "config" / "default.toml"
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    in_visual_meter = False
    changed = False
    output: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_visual_meter = stripped == "[voice.visual_meter]"
        if in_visual_meter and stripped.startswith("visual_offset_ms"):
            output.append(f"visual_offset_ms = {int(offset_ms)}")
            changed = True
            continue
        output.append(line)
    if not changed:
        output.append("")
        output.append("[voice.visual_meter]")
        output.append(f"visual_offset_ms = {int(offset_ms)}")
    path.write_text("\n".join(output) + "\n", encoding="utf-8")


def _write_csv(path: Path, results: Sequence[Mapping[str, Any]]) -> None:
    rows: list[dict[str, Any]] = []
    for result in results:
        scenarios = result.get("scenarios") if isinstance(result.get("scenarios"), Mapping) else {}
        for name, scenario in scenarios.items():
            if not isinstance(scenario, Mapping):
                continue
            rows.append(
                {
                    "visual_offset_ms": result.get("visual_offset_ms"),
                    "scenario": name,
                    "classification": ",".join(str(item) for item in scenario.get("classification", [])),
                    "paint_fps": scenario.get("paint_fps"),
                    "start_delay_ms": scenario.get("start_delay_ms"),
                    "release_tail_ms": scenario.get("release_tail_ms"),
                    "finalSpeakingEnergy_span": scenario.get("finalSpeakingEnergy_span"),
                    "blobScaleDrive_span": scenario.get("blobScaleDrive_span"),
                    "direct_pcm_to_blob_lag_ms": scenario.get("direct_pcm_to_blob_lag_ms"),
                    "correlation_confidence": scenario.get("correlation_confidence"),
                    "stage_latency_estimate_ms": scenario.get("stage_latency_estimate_ms"),
                    "syncMeasurementConfidence": scenario.get("syncMeasurementConfidence"),
                    "syncMeasurementRejectionReason": scenario.get("syncMeasurementRejectionReason"),
                    "syncOffsetCandidateSafe": scenario.get("syncOffsetCandidateSafe"),
                    "syncOffsetCandidateRejectedReason": scenario.get("syncOffsetCandidateRejectedReason"),
                    "raw_audio_present": False,
                }
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["visual_offset_ms"])
        writer.writeheader()
        writer.writerows(rows)


def _markdown(summary: Mapping[str, Any]) -> str:
    lines = [
        "# Voice AR11 Sync Offset Sweep",
        "",
        f"- QSG visual approval: `{summary.get('qsg_visual_approval')}`",
        f"- Recommended visual_offset_ms: `{summary.get('recommended_visual_offset_ms')}`",
        f"- Offset applied: `{summary.get('offset_applied')}`",
        f"- Recommendation reason: `{summary.get('recommendation_reason')}`",
        "- Privacy: scalar-only diagnostics, raw_audio_present=false",
        "",
        "## Results",
    ]
    for result in summary.get("sync_calibration_results", []):
        lines.append(f"### visual_offset_ms={result.get('visual_offset_ms')}")
        scenarios = result.get("scenarios") if isinstance(result.get("scenarios"), Mapping) else {}
        for name, scenario in scenarios.items():
            if not isinstance(scenario, Mapping):
                continue
            lines.append(
                "- "
                f"{name}: classification=`{','.join(str(item) for item in scenario.get('classification', []))}`, "
                f"paint_fps={scenario.get('paint_fps')}, "
                f"start_delay_ms={scenario.get('start_delay_ms')}, "
                f"release_tail_ms={scenario.get('release_tail_ms')}, "
                f"lag_ms={scenario.get('direct_pcm_to_blob_lag_ms')}, "
                f"confidence={scenario.get('correlation_confidence')}"
            )
    lines.extend(["", "## Rollback", "", "```toml", "[voice.visual_meter]", "visual_offset_ms = 0", "```"])
    return "\n".join(lines) + "\n"


def _build_kraken_command(args: argparse.Namespace, *, offset: int, output_dir: Path) -> list[str]:
    command = [
        sys.executable,
        str(SCRIPTS_DIR / "run_voice_ar5_live_kraken_probe.py"),
        "--host",
        str(args.host),
        "--port",
        str(args.port),
        "--fog",
        str(args.fog),
        "--spoken-prompt",
        str(args.spoken_prompt),
        "--timeout-seconds",
        str(args.timeout_seconds),
        "--idle-observe-seconds",
        str(args.idle_observe_seconds),
        "--post-speech-observe-seconds",
        str(args.post_speech_observe_seconds),
        "--anchor-renderer",
        "legacy_blob_qsg_candidate",
        "--voice-visual-offset-ms",
        str(offset),
        "--qsg-visual-approval",
        _normalize_qsg_visual_approval(args.qsg_visual_approval),
        "--qsg-visual-approval-reason",
        str(args.qsg_visual_approval_reason or ""),
        "--output-dir",
        str(output_dir),
    ]
    if args.stormforge:
        command.append("--stormforge")
    if args.clear_cache:
        command.append("--clear-cache")
    if args.audible:
        command.append("--audible")
    if args.use_local_pcm_voice_fixture:
        command.append("--use-local-pcm-voice-fixture")
    return command


def _run_offset(args: argparse.Namespace, *, offset: int, output_dir: Path) -> dict[str, Any]:
    command = _build_kraken_command(args, offset=offset, output_dir=output_dir)
    timeout = max(
        600,
        int(
            (
                float(args.timeout_seconds)
                + float(args.idle_observe_seconds)
                + float(args.post_speech_observe_seconds)
            )
            * 12
        ),
    )
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        check=False,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    report_path = output_dir / "ar5_live_kraken_report.json"
    if not report_path.exists():
        return sanitize_kraken_payload(
            {
                "visual_offset_ms": offset,
                "output_dir": str(output_dir),
                "classification": ["probe_run_failed"],
                "returncode": completed.returncode,
                "stdout_tail": completed.stdout[-2000:],
                "stderr_tail": completed.stderr[-2000:],
                "raw_audio_present": False,
            }
        )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    result = extract_offset_result(report, offset_ms=offset, output_dir=output_dir)
    result["returncode"] = completed.returncode
    return sanitize_kraken_payload(result)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run AR11 QSG voice visual sync offset sweep without applying offsets by default."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--stormforge", action="store_true")
    parser.add_argument("--fog", choices=["on", "off", "auto"], default="auto")
    parser.add_argument("--clear-cache", action="store_true")
    parser.add_argument("--spoken-prompt", default="Testing one, two, three. Anchor sync check.")
    parser.add_argument("--audible", action="store_true")
    parser.add_argument("--use-local-pcm-voice-fixture", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=24.0)
    parser.add_argument("--idle-observe-seconds", type=float, default=10.0)
    parser.add_argument("--post-speech-observe-seconds", type=float, default=8.0)
    parser.add_argument("--offsets", default="0,-60,-100,-140,-180")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument(
        "--qsg-visual-approval",
        choices=["pending", "approved", "rejected"],
        default="pending",
    )
    parser.add_argument("--qsg-visual-approval-reason", default="")
    parser.add_argument("--sync-calibration-even-if-pending", action="store_true")
    parser.add_argument("--apply-recommended-offset", action="store_true")
    parser.add_argument("--operator-sync-approved", action="store_true")
    parser.add_argument("--operator-sync-note", default="")
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    approval = _normalize_qsg_visual_approval(args.qsg_visual_approval)
    if approval != "approved" and not args.sync_calibration_even_if_pending:
        summary = summarize_offset_sweep(
            [],
            visual_approval=approval,
            apply_requested=False,
            operator_note="sync sweep skipped until visual approval or explicit pending override",
        )
        summary["skipped"] = True
        summary["skip_reason"] = "qsg_visual_approval_not_approved"
        _write_json(output_dir / "sync_offset_sweep_report.json", summary)
        (output_dir / "sync_offset_sweep_report.md").write_text(_markdown(summary), encoding="utf-8")
        print(json.dumps({"skipped": True, "report": str(output_dir / "sync_offset_sweep_report.json")}, indent=2))
        return 0

    results = [
        _run_offset(args, offset=offset, output_dir=output_dir / f"offset_{offset:+d}")
        for offset in parse_offsets(args.offsets)
    ]
    summary = summarize_offset_sweep(
        results,
        visual_approval=approval,
        apply_requested=bool(args.apply_recommended_offset),
        operator_sync_approved=bool(args.operator_sync_approved),
        operator_note=args.operator_sync_note,
    )
    if summary.get("offset_applied") is True:
        _write_default_config_visual_offset(int(summary.get("visual_offset_applied_ms") or 0))
        summary["applied_config_path"] = str((PROJECT_ROOT / "config" / "default.toml").resolve())
    assert_no_raw_audio_payload(summary)
    _write_json(output_dir / "sync_offset_sweep_report.json", summary)
    _write_csv(output_dir / "sync_offset_sweep_table.csv", summary.get("sync_calibration_results", []))
    (output_dir / "sync_offset_sweep_report.md").write_text(_markdown(summary), encoding="utf-8")
    print(
        json.dumps(
            {
                "report": str(output_dir / "sync_offset_sweep_report.json"),
                "recommended_visual_offset_ms": summary.get("recommended_visual_offset_ms"),
                "offset_applied": summary.get("offset_applied"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
