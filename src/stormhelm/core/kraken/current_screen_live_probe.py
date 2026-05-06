from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable, Mapping, Sequence

from stormhelm.config.loader import load_config
from stormhelm.config.models import AppConfig
from stormhelm.core.screen_awareness import ScreenIntentType
from stormhelm.core.screen_awareness import WindowsScreenCaptureProvider
from stormhelm.core.screen_awareness import build_screen_awareness_subsystem
from stormhelm.core.screen_awareness.models import ScreenResponse
from stormhelm.core.system.probe import SystemProbe
from stormhelm.ui.command_surface_v2 import _stations


DEFAULT_OUTPUT_DIR = Path(".artifacts") / "screen-awareness" / "live-current-screen-probe"
DEFAULT_PROMPTS = (
    "What is on my screen right now?",
    "What do you see?",
    "What am I looking at?",
    "Can you help with this?",
)
ALL_PROMPTS = (
    *DEFAULT_PROMPTS,
    "What is the main thing visible here?",
    "Summarize this screen.",
)
MINIMAL_PROMPTS = ("What is on my screen right now?",)
SCENARIO_LABELS = {
    "clipping-tool-error",
    "clipping-tool-homework",
    "browser-article",
    "browser-docs",
    "file-explorer-folder",
    "terminal-error",
    "settings-window",
    "multiple-windows",
    "blank-desktop",
    "ocr-heavy",
    "image-heavy-low-ocr",
    "capture-blocked",
    "clipboard-stale-mismatch",
    "general",
}
RAW_PAYLOAD_KEYS = {
    "raw_pixels",
    "pixel_bytes",
    "pixels",
    "image_bytes",
    "image_base64",
    "base64_png",
    "raw_screenshot",
    "screenshot_base64",
}
RAW_PAYLOAD_MARKERS = (
    "data:image",
    "base64_png",
    "image_base64",
    "raw_pixels",
    "pixel_bytes",
    "iVBORw0KGgo",
    "/9j/",
)
SENSITIVE_TEXT_PATTERN = re.compile(
    r"\b(password|passwd|secret|token|api[_ -]?key|bearer|authorization|private key)\b",
    flags=re.IGNORECASE,
)
ROW_FIELDS = (
    "scenario_label",
    "prompt",
    "route_family",
    "observation_attempted",
    "observation_available",
    "observation_allowed",
    "observation_blocked_reason",
    "evidence_before_observation",
    "evidence_after_observation",
    "answered_from_source",
    "visible_context_summary",
    "ghost_text",
    "deck_trace_summary",
    "weak_fallback_used",
    "no_visual_evidence_reason",
    "raw_payload_leak_detected",
    "ui_action_attempted",
    "pass_manual_review_hint",
    "warnings",
    "errors",
    "elapsed_ms",
)


@dataclass(frozen=True, slots=True)
class CurrentScreenLiveProbeOptions:
    scenario_label: str = "general"
    prompts: tuple[str, ...] = DEFAULT_PROMPTS
    output_dir: Path | str = DEFAULT_OUTPUT_DIR
    timestamp: str | None = None
    allow_debug_text: bool = False
    persist_screenshot: bool = False
    timeout_ms: int = 8000
    provider_vision: bool = False
    json_stdout: bool = False


@dataclass(slots=True)
class CurrentScreenLiveProbeRow:
    scenario_label: str
    prompt: str
    route_family: str
    observation_attempted: bool
    observation_available: bool
    observation_allowed: bool
    observation_blocked_reason: str | None
    evidence_before_observation: list[dict[str, Any]]
    evidence_after_observation: list[dict[str, Any]]
    answered_from_source: str
    visible_context_summary: dict[str, Any]
    ghost_text: str
    deck_trace_summary: str
    weak_fallback_used: bool
    no_visual_evidence_reason: str | None
    raw_payload_leak_detected: bool
    ui_action_attempted: bool
    pass_manual_review_hint: list[str]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    elapsed_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CurrentScreenLiveProbeResult:
    output_dir: Path
    report: dict[str, Any]
    rows: list[CurrentScreenLiveProbeRow]


class ObservationOnlyActionExecutor:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def execute(self, request: Any) -> Any:
        self.calls.append({"request": request})
        raise RuntimeError("Live current-screen probe is observation-only and must not execute UI actions.")


def detect_raw_payload_leak(payload: Any) -> bool:
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            key_text = str(key).strip().lower()
            if key_text in RAW_PAYLOAD_KEYS:
                return True
            if detect_raw_payload_leak(value):
                return True
        return False
    if isinstance(payload, (list, tuple, set)):
        return any(detect_raw_payload_leak(item) for item in payload)
    if isinstance(payload, (bytes, bytearray)):
        return True
    text = str(payload or "")
    if not text:
        return False
    lowered = text.lower()
    if any(marker.lower() in lowered for marker in RAW_PAYLOAD_MARKERS):
        return True
    return len(text) > 300 and bool(re.fullmatch(r"[A-Za-z0-9+/=\s]+", text))


def run_current_screen_live_probe(
    options: CurrentScreenLiveProbeOptions,
    *,
    config: AppConfig | None = None,
    subsystem: Any | None = None,
) -> CurrentScreenLiveProbeResult:
    scenario_label = _safe_scenario_label(options.scenario_label)
    timestamp = _safe_timestamp(options.timestamp)
    output_dir = Path(options.output_dir) / f"{timestamp}-{scenario_label}"
    output_dir.mkdir(parents=True, exist_ok=True)
    action_executor = ObservationOnlyActionExecutor()
    if subsystem is None:
        app_config = config or load_config(project_root=Path.cwd(), env={})
        _configure_screen_probe(app_config, options)
        subsystem = build_screen_awareness_subsystem(
            app_config.screen_awareness,
            system_probe=SystemProbe(app_config),
            screen_capture_provider=WindowsScreenCaptureProvider(
                ocr_timeout_seconds=max(0.5, options.timeout_ms / 1000.0),
                capture_timeout_seconds=max(0.5, options.timeout_ms / 1000.0),
            ),
            action_executor=action_executor,
        )

    rows: list[CurrentScreenLiveProbeRow] = []
    for prompt in options.prompts:
        started = perf_counter()
        try:
            response = subsystem.handle_request(
                session_id=f"live-current-screen-probe-{timestamp}",
                operator_text=prompt,
                intent=ScreenIntentType.INSPECT_VISIBLE_STATE,
                surface_mode="ghost",
                active_module="chartroom",
                active_context={"selection": {}, "clipboard": {}},
                workspace_context={},
            )
            status_snapshot = _status_snapshot(subsystem)
            elapsed_ms = round((perf_counter() - started) * 1000.0, 3)
            row = build_live_probe_row(
                scenario_label=scenario_label,
                prompt=prompt,
                response=response,
                status_snapshot=status_snapshot,
                action_calls=list(getattr(action_executor, "calls", [])),
                elapsed_ms=elapsed_ms,
                allow_debug_text=options.allow_debug_text,
            )
        except Exception as exc:
            elapsed_ms = round((perf_counter() - started) * 1000.0, 3)
            row = _error_row(
                scenario_label=scenario_label,
                prompt=prompt,
                elapsed_ms=elapsed_ms,
                error=str(exc)[:240],
            )
        rows.append(row)

    report = _build_report(options=options, output_dir=output_dir, rows=rows, timestamp=timestamp)
    _write_artifacts(output_dir, rows, report)
    return CurrentScreenLiveProbeResult(output_dir=output_dir, report=report, rows=rows)


def build_live_probe_row(
    *,
    scenario_label: str,
    prompt: str,
    response: ScreenResponse,
    status_snapshot: Mapping[str, Any],
    action_calls: Sequence[Mapping[str, Any]],
    elapsed_ms: float,
    allow_debug_text: bool,
) -> CurrentScreenLiveProbeRow:
    telemetry = response.telemetry if isinstance(response.telemetry, dict) else {}
    observation = dict(telemetry.get("observation") or {})
    trace = dict(telemetry.get("trace") or {})
    raw_payload_leak = detect_raw_payload_leak(
        {
            "response_contract": getattr(response, "response_contract", {}),
            "telemetry": telemetry,
            "status_snapshot": status_snapshot,
        }
    )
    route = dict(telemetry.get("route") or {})
    route_family = str(route.get("route_family") or route.get("family") or "screen_awareness")
    evidence_before = _sanitize_evidence_list(
        observation.get("evidence_before_observation") or trace.get("evidence_before_observation"),
        allow_debug_text=allow_debug_text,
    )
    evidence_after = _sanitize_evidence_list(
        observation.get("evidence_after_observation") or observation.get("evidence_ranking") or trace.get("evidence_ranking"),
        allow_debug_text=allow_debug_text,
    )
    visible_summary = _sanitize_visible_summary(
        observation.get("visible_context_summary") or trace.get("visible_context_summary"),
        allow_debug_text=allow_debug_text,
    )
    ghost_text = _safe_text(getattr(response, "assistant_response", ""), limit=900 if allow_debug_text else 520)
    deck_trace_summary = _deck_trace_summary(trace=trace, visible_context=visible_summary)
    ui_action_attempted = bool(action_calls or telemetry.get("action", {}).get("requested"))
    row = CurrentScreenLiveProbeRow(
        scenario_label=scenario_label,
        prompt=prompt,
        route_family=route_family,
        observation_attempted=bool(observation.get("observation_attempted")),
        observation_available=bool(observation.get("observation_available")),
        observation_allowed=bool(observation.get("observation_allowed")),
        observation_blocked_reason=_optional_text(observation.get("observation_blocked_reason")),
        evidence_before_observation=evidence_before,
        evidence_after_observation=evidence_after,
        answered_from_source=_optional_text(observation.get("answered_from_source")) or "",
        visible_context_summary=visible_summary,
        ghost_text=ghost_text,
        deck_trace_summary=deck_trace_summary,
        weak_fallback_used=bool(observation.get("weak_fallback_used")),
        no_visual_evidence_reason=_optional_text(observation.get("no_visual_evidence_reason")),
        raw_payload_leak_detected=raw_payload_leak,
        ui_action_attempted=ui_action_attempted,
        pass_manual_review_hint=[],
        warnings=_warnings_from_response(response, trace),
        errors=[],
        elapsed_ms=elapsed_ms,
    )
    row.pass_manual_review_hint = review_hints(row)
    return row


def review_hints(row: CurrentScreenLiveProbeRow) -> list[str]:
    hints: list[str] = []
    top_source = str(row.evidence_after_observation[0].get("source") or "") if row.evidence_after_observation else ""
    answered = str(row.answered_from_source or "")
    strong_sources = {
        "screen_capture",
        "local_ocr",
        "provider_vision",
        "selected_text",
        "accessibility_ui_tree",
        "app_semantic_adapter",
    }
    if top_source in strong_sources or answered in strong_sources:
        hints.append("strong_evidence_used")
    if top_source in {"screen_capture", "local_ocr", "provider_vision"} or answered in {"screen_capture", "local_ocr", "provider_vision"}:
        hints.append("answered_from_pixels_or_ocr")
    if row.weak_fallback_used or top_source in {"active_window_title", "foreground_window_stack"}:
        hints.append("weak_metadata_only")
    if top_source in {"clipboard_hint", "stale_recent_context"} or answered in {"clipboard_hint", "stale_recent_context"}:
        hints.append("stale_or_clipboard_only")
    if row.observation_blocked_reason or row.no_visual_evidence_reason in {"screen_capture_unavailable", "insufficient_visual_evidence"}:
        if "unavailable" in str(row.observation_blocked_reason or row.no_visual_evidence_reason):
            hints.append("capture_unavailable")
    if _ghost_compact(row.ghost_text):
        hints.append("ghost_compact")
    if row.deck_trace_summary:
        hints.append("deck_trace_present")
    if _possible_ocr_soup(row):
        hints.append("possible_ocr_soup")
    if _possible_overclaim(row.ghost_text, row.answered_from_source):
        hints.append("possible_overclaim")
    if _clipping_tool_content_first(row):
        hints.append("clipping_tool_content_first")
    if row.raw_payload_leak_detected:
        hints.append("raw_payload_leak_detected")
    if row.ui_action_attempted:
        hints.append("ui_action_attempted")
    return list(dict.fromkeys(hints))


def default_prompts(kind: str) -> tuple[str, ...]:
    normalized = str(kind or "default").strip().lower()
    if normalized == "minimal":
        return MINIMAL_PROMPTS
    if normalized == "all":
        return ALL_PROMPTS
    return DEFAULT_PROMPTS


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a safe live current-screen Screen Awareness probe.")
    parser.add_argument("--scenario", default="general", choices=sorted(SCENARIO_LABELS))
    parser.add_argument("--prompts", default="default", choices=("default", "minimal", "all"))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--json", action="store_true", dest="json_stdout")
    parser.add_argument("--allow-debug-text", nargs="?", const="true", default="false")
    parser.add_argument("--persist-screenshot", nargs="?", const="true", default="false")
    parser.add_argument("--timeout-ms", type=int, default=8000)
    parser.add_argument("--no-provider-vision", action="store_true", default=False)
    parser.add_argument("--provider-vision", action="store_true", default=False)
    args = parser.parse_args(argv)
    provider_vision = bool(args.provider_vision and not args.no_provider_vision)
    options = CurrentScreenLiveProbeOptions(
        scenario_label=args.scenario,
        prompts=default_prompts(args.prompts),
        output_dir=Path(args.output_dir),
        allow_debug_text=_parse_bool(args.allow_debug_text),
        persist_screenshot=_parse_bool(args.persist_screenshot),
        timeout_ms=int(args.timeout_ms),
        provider_vision=provider_vision,
        json_stdout=bool(args.json_stdout),
    )
    result = run_current_screen_live_probe(options)
    output = {
        "completed": result.report.get("completed"),
        "output_dir": str(result.output_dir),
        "rows": result.report.get("row_count"),
        "raw_payload_leaks": result.report.get("raw_payload_leak_count"),
        "ui_action_attempts": result.report.get("ui_action_attempt_count"),
        "hint_counts": result.report.get("hint_counts"),
    }
    if args.json_stdout:
        print(json.dumps(output, indent=2, sort_keys=True))
    else:
        print(f"Live current-screen probe wrote {output['rows']} row(s) to {output['output_dir']}")
        print(f"Raw payload leaks flagged: {output['raw_payload_leaks']}; UI action attempts flagged: {output['ui_action_attempts']}")
    return 0


def _configure_screen_probe(config: AppConfig, options: CurrentScreenLiveProbeOptions) -> None:
    screen = config.screen_awareness
    screen.action_policy_mode = "confirm_before_act"
    screen.screen_capture_provider_vision_enabled = bool(options.provider_vision and screen.screen_capture_provider_vision_enabled)
    screen.screen_capture_store_raw_images = bool(options.persist_screenshot and screen.screen_capture_store_raw_images)


def _parse_bool(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _safe_scenario_label(value: str) -> str:
    label = str(value or "general").strip().lower().replace("_", "-")
    if label not in SCENARIO_LABELS:
        return "general"
    return label


def _safe_timestamp(value: str | None) -> str:
    if value:
        cleaned = re.sub(r"[^0-9A-Za-zT.Z-]+", "-", value.strip())
        return cleaned.rstrip("-") or _safe_timestamp(None)
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


def _status_snapshot(subsystem: Any) -> dict[str, Any]:
    reader = getattr(subsystem, "status_snapshot", None)
    if not callable(reader):
        return {}
    try:
        snapshot = reader()
    except Exception as exc:
        return {"status_snapshot_error": str(exc)[:160]}
    return dict(snapshot) if isinstance(snapshot, dict) else {}


def _sanitize_evidence_list(value: Any, *, allow_debug_text: bool) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    entries: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        payload = {
            "rank": item.get("rank"),
            "tier": item.get("tier"),
            "source": item.get("source"),
            "source_type": item.get("source_type"),
            "freshness": item.get("freshness"),
            "confidence": _sanitize_payload(item.get("confidence"), allow_debug_text=allow_debug_text),
            "used_for_summary": item.get("used_for_summary"),
            "note": _safe_text(item.get("note"), limit=180),
        }
        details = item.get("details")
        if isinstance(details, Mapping):
            payload["details"] = {
                key: _safe_text(value, limit=180)
                for key, value in details.items()
                if str(key).lower() not in RAW_PAYLOAD_KEYS and (allow_debug_text or str(key).lower() not in {"preview", "text", "ocr_text"})
            }
        entries.append({key: value for key, value in payload.items() if value not in (None, "", [], {})})
    return entries


def _sanitize_visible_summary(value: Any, *, allow_debug_text: bool) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    summary = {
        "summary": _safe_text(value.get("summary"), limit=260),
        "source": _safe_text(value.get("source"), limit=80),
        "primary_content": _sanitize_payload(value.get("primary_content"), allow_debug_text=allow_debug_text),
        "key_text": [_safe_text(item, limit=220 if allow_debug_text else 140) for item in (value.get("key_text") or [])[:3]],
        "entities": [_safe_text(item, limit=120) for item in (value.get("entities") or [])[:6]],
        "windows": _sanitize_payload(value.get("windows"), allow_debug_text=allow_debug_text),
        "likely_task": _sanitize_payload(value.get("likely_task"), allow_debug_text=allow_debug_text),
        "help_options": [_safe_text(item, limit=160) for item in (value.get("help_options") or [])[:3]],
    }
    return {key: value for key, value in summary.items() if value not in (None, "", [], {})}


def _sanitize_payload(value: Any, *, allow_debug_text: bool) -> Any:
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key).strip()
            key_lower = key_text.lower()
            if key_lower in RAW_PAYLOAD_KEYS:
                continue
            if not allow_debug_text and key_lower in {"raw_text", "ocr_text", "full_text", "preview_text"}:
                continue
            sanitized[key_text] = _sanitize_payload(item, allow_debug_text=allow_debug_text)
        return {key: item for key, item in sanitized.items() if item not in (None, "", [], {})}
    if isinstance(value, list):
        return [_sanitize_payload(item, allow_debug_text=allow_debug_text) for item in value[:12]]
    if isinstance(value, (bytes, bytearray)):
        return "[redacted-bytes]"
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return _safe_text(value, limit=300 if allow_debug_text else 180)


def _safe_text(value: Any, *, limit: int) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""
    if detect_raw_payload_leak(text):
        return "[redacted-raw-payload]"
    if SENSITIVE_TEXT_PATTERN.search(text):
        return "[redacted-sensitive-text]"
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _optional_text(value: Any) -> str | None:
    text = _safe_text(value, limit=160)
    return text or None


def _warnings_from_response(response: ScreenResponse, trace: Mapping[str, Any]) -> list[str]:
    warnings: list[str] = []
    if response.telemetry.get("truthfulness_audit", {}).get("passed") is False:
        warnings.append("truthfulness_audit_warning")
    if trace.get("observation_blocked_reason"):
        warnings.append(str(trace.get("observation_blocked_reason")))
    return list(dict.fromkeys(warnings))


def _deck_trace_summary(*, trace: Mapping[str, Any], visible_context: Mapping[str, Any]) -> str:
    payload = dict(trace)
    payload.setdefault("durationMs", 0.0)
    if visible_context and not payload.get("visible_context_summary"):
        payload["visible_context_summary"] = dict(visible_context)
    stations = _stations(
        "screen_awareness",
        "Live Current Screen Probe",
        "Observation trace prepared.",
        "Prepared",
        "prepared",
        "current screen",
        {},
        {},
        {},
        {"present": False, "tone": "steady", "summary": "", "posture": "", "freshness": ""},
        {"present": False, "count": "Support memory", "contributors": []},
        {
            "present": True,
            "headline": "Live",
            "tone": "steady",
            "watch": {"present": False},
            "lifecycle": {"present": False},
            "screenAwareness": {
                "phase": "phase12",
                "policy": {"action_policy_mode": "confirm_before_act"},
                "trace": payload,
            },
        },
        [],
        [],
    )
    pieces: list[str] = []
    for station in stations:
        for section in station.get("sections", []):
            for entry in section.get("entries", []):
                pieces.extend(str(entry.get(key) or "") for key in ("primary", "secondary", "detail"))
    return _safe_text(" ".join(part for part in pieces if part), limit=1200)


def _ghost_compact(text: str) -> bool:
    return len(str(text or "")) <= 520 and "evidence_ranking" not in str(text or "").lower()


def _possible_ocr_soup(row: CurrentScreenLiveProbeRow) -> bool:
    key_text = row.visible_context_summary.get("key_text")
    if isinstance(key_text, list) and len(key_text) > 3:
        return True
    lowered = row.ghost_text.lower()
    return len(row.ghost_text) > 520 or "home search settings profile menu help back forward reload" in lowered


def _possible_overclaim(text: str, answered_from_source: str) -> bool:
    lowered = str(text or "").lower()
    weak_source = answered_from_source in {"active_window_title", "foreground_window_stack", "clipboard_hint", "stale_recent_context", "insufficient_visual_evidence"}
    if weak_source and any(token in lowered for token in {"definitely", "certainly", "the main thing on screen is"}):
        return True
    return "you are " in lowered and "it looks like you may be" not in lowered


def _clipping_tool_content_first(row: CurrentScreenLiveProbeRow) -> bool:
    if not row.scenario_label.startswith("clipping-tool"):
        return False
    lowered = row.ghost_text.lower()
    content_index = lowered.find("screenshot content")
    tool_index = lowered.find("clipping tool")
    if content_index != -1 and (tool_index == -1 or content_index < tool_index):
        return True
    primary = row.visible_context_summary.get("primary_content")
    return isinstance(primary, Mapping) and str(primary.get("kind") or "") == "screenshot_content"


def _error_row(*, scenario_label: str, prompt: str, elapsed_ms: float, error: str) -> CurrentScreenLiveProbeRow:
    row = CurrentScreenLiveProbeRow(
        scenario_label=scenario_label,
        prompt=prompt,
        route_family="screen_awareness",
        observation_attempted=False,
        observation_available=False,
        observation_allowed=False,
        observation_blocked_reason=None,
        evidence_before_observation=[],
        evidence_after_observation=[],
        answered_from_source="",
        visible_context_summary={},
        ghost_text="",
        deck_trace_summary="",
        weak_fallback_used=True,
        no_visual_evidence_reason="probe_error",
        raw_payload_leak_detected=False,
        ui_action_attempted=False,
        pass_manual_review_hint=[],
        warnings=[],
        errors=[error],
        elapsed_ms=elapsed_ms,
    )
    row.pass_manual_review_hint = review_hints(row)
    return row


def _build_report(
    *,
    options: CurrentScreenLiveProbeOptions,
    output_dir: Path,
    rows: Sequence[CurrentScreenLiveProbeRow],
    timestamp: str,
) -> dict[str, Any]:
    hint_counts: dict[str, int] = {}
    for row in rows:
        for hint in row.pass_manual_review_hint:
            hint_counts[hint] = hint_counts.get(hint, 0) + 1
    return {
        "completed": True,
        "scenario_label": _safe_scenario_label(options.scenario_label),
        "timestamp": timestamp,
        "output_dir": str(output_dir),
        "row_count": len(rows),
        "prompts": list(options.prompts),
        "safety": {
            "observation_only": True,
            "persist_screenshot_requested": bool(options.persist_screenshot),
            "persist_screenshot_default": False,
            "allow_debug_text": bool(options.allow_debug_text),
            "provider_vision_requested": bool(options.provider_vision),
            "raw_payloads_redacted_from_artifacts": True,
        },
        "raw_payload_leak_count": sum(1 for row in rows if row.raw_payload_leak_detected),
        "ui_action_attempt_count": sum(1 for row in rows if row.ui_action_attempted),
        "weak_fallback_count": sum(1 for row in rows if row.weak_fallback_used),
        "hint_counts": dict(sorted(hint_counts.items())),
        "rows": [row.to_dict() for row in rows],
    }


def _write_artifacts(output_dir: Path, rows: Sequence[CurrentScreenLiveProbeRow], report: Mapping[str, Any]) -> None:
    report_path = output_dir / "live_current_screen_probe_report.json"
    report_path.write_text(json.dumps(_artifact_safe(report), indent=2, sort_keys=True), encoding="utf-8")
    jsonl_path = output_dir / "live_current_screen_probe_rows.jsonl"
    with jsonl_path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(_artifact_safe(row.to_dict()), sort_keys=True) + "\n")
    csv_path = output_dir / "live_current_screen_probe_rows.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(ROW_FIELDS), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            payload = row.to_dict()
            writer.writerow({key: _csv_value(payload.get(key)) for key in ROW_FIELDS})
    (output_dir / "live_current_screen_probe_summary.md").write_text(_summary_markdown(report, rows), encoding="utf-8")


def _artifact_safe(payload: Any) -> Any:
    return _sanitize_payload(payload, allow_debug_text=True)


def _csv_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    return str(value or "")


def _summary_markdown(report: Mapping[str, Any], rows: Sequence[CurrentScreenLiveProbeRow]) -> str:
    lines = [
        "# Live Current-Screen Probe",
        "",
        f"- Scenario: {report.get('scenario_label')}",
        f"- Rows: {report.get('row_count')}",
        f"- Raw payload leaks flagged: {report.get('raw_payload_leak_count')}",
        f"- UI action attempts flagged: {report.get('ui_action_attempt_count')}",
        f"- Weak fallbacks: {report.get('weak_fallback_count')}",
        "",
        "## Rows",
    ]
    for row in rows:
        hints = ", ".join(row.pass_manual_review_hint) or "none"
        summary = row.visible_context_summary.get("summary") if isinstance(row.visible_context_summary, dict) else ""
        lines.extend(
            [
                "",
                f"### {row.prompt}",
                f"- Answered from: {row.answered_from_source or 'unknown'}",
                f"- Observation attempted: {row.observation_attempted}",
                f"- Review hints: {hints}",
                f"- Visible summary: {summary or 'not available'}",
                f"- Ghost: {row.ghost_text or 'not available'}",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "CurrentScreenLiveProbeOptions",
    "CurrentScreenLiveProbeResult",
    "CurrentScreenLiveProbeRow",
    "ObservationOnlyActionExecutor",
    "default_prompts",
    "detect_raw_payload_leak",
    "review_hints",
    "run_current_screen_live_probe",
    "main",
]
