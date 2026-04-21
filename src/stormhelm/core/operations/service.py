from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from stormhelm.core.operations.models import (
    DiagnosticEvidenceBundle,
    DiagnosticFinding,
    OperationalSignal,
    SystemsInterpretationSnapshot,
    TaskProgressSnapshot,
    WatchStateSnapshot,
)


class OperationalAwarenessService:
    def assess_power(self, power: dict[str, Any]) -> DiagnosticFinding:
        if not isinstance(power, dict) or not power.get("available"):
            return DiagnosticFinding(
                kind="power_unavailable",
                headline="Power telemetry unavailable",
                summary="Stormhelm cannot read reliable battery or charging telemetry on this machine right now.",
                severity="attention",
                confidence="low",
                label="Battery",
            )

        ac_state = str(power.get("ac_line_status", "unknown")).strip().lower()
        battery_percent = _int_or_none(power.get("battery_percent"))
        rolling_draw = _float_or_none(power.get("rolling_power_draw_watts"))
        instant_draw = _float_or_none(power.get("instant_power_draw_watts"))
        discharge_draw = _float_or_none(power.get("discharge_rate_watts"))
        charge_draw = _float_or_none(power.get("charge_rate_watts"))
        time_to_empty = _int_or_none(power.get("time_to_empty_seconds") or power.get("seconds_remaining"))
        time_to_full = _int_or_none(power.get("time_to_full_seconds"))

        evidence = DiagnosticEvidenceBundle(
            metrics={
                "battery_percent": battery_percent,
                "rolling_power_draw_watts": rolling_draw,
                "instant_power_draw_watts": instant_draw,
                "discharge_rate_watts": discharge_draw,
                "charge_rate_watts": charge_draw,
            }
        )

        if ac_state == "online":
            if charge_draw and charge_draw > 5.0:
                summary = "Battery is charging normally on AC power."
                if time_to_full:
                    summary = f"{summary[:-1]} with about {_duration_label(time_to_full)} until full."
                return DiagnosticFinding(
                    kind="charging_normally",
                    headline="Battery charging normally",
                    summary=summary,
                    severity="steady",
                    confidence="moderate",
                    label="Battery",
                    evidence=evidence,
                )
            return DiagnosticFinding(
                kind="on_ac_power",
                headline="Battery on AC power",
                summary="AC is online, but this machine is not exposing a strong charging-rate signal right now.",
                severity="steady",
                confidence="low",
                label="Battery",
                evidence=evidence,
            )

        dominant_draw = rolling_draw or discharge_draw or instant_draw
        if dominant_draw is not None and dominant_draw >= 25.0:
            detail = f"Battery is draining faster than usual at about {dominant_draw:.1f} W."
            if battery_percent is not None and time_to_empty:
                detail = f"{detail[:-1]} At the current draw, about {_duration_label(time_to_empty)} remain."
            return DiagnosticFinding(
                kind="drain_elevated",
                headline="Battery drain elevated",
                summary=detail,
                severity="warning",
                confidence="moderate",
                label="Battery",
                evidence=evidence,
                next_checks=["Check the heaviest active app or run a short live diagnostics burst."],
            )

        if battery_percent is not None and time_to_empty is not None:
            return DiagnosticFinding(
                kind="battery_discharging",
                headline="Battery on discharge",
                summary=f"Battery is discharging normally with about {_duration_label(time_to_empty)} remaining at the current posture.",
                severity="steady",
                confidence="moderate",
                label="Battery",
                evidence=evidence,
            )

        return DiagnosticFinding(
            kind="battery_discharging",
            headline="Battery on discharge",
            summary="Battery is discharging, but the machine is not exposing a reliable draw or remaining-time estimate yet.",
            severity="steady",
            confidence="low",
            label="Battery",
            evidence=evidence,
        )

    def assess_storage(self, storage: dict[str, Any]) -> DiagnosticFinding:
        drives = storage.get("drives", []) if isinstance(storage, dict) else []
        primary = drives[0] if isinstance(drives, list) and drives and isinstance(drives[0], dict) else {}
        total = _float_or_none(primary.get("total_bytes"))
        free = _float_or_none(primary.get("free_bytes"))
        if not total or free is None:
            return DiagnosticFinding(
                kind="storage_unknown",
                headline="Storage telemetry limited",
                summary="Stormhelm cannot see enough disk telemetry to judge pressure confidently.",
                severity="attention",
                confidence="low",
                label="Storage",
            )
        free_pct = (free / total) * 100 if total > 0 else None
        evidence = DiagnosticEvidenceBundle(metrics={"free_percent": round(free_pct or 0.0, 1)})
        if free_pct is not None and free_pct <= 12.0:
            return DiagnosticFinding(
                kind="disk_pressure",
                headline="Disk pressure elevated",
                summary="Primary storage is getting tight enough that cache, temp, or update work may start to feel constrained.",
                severity="warning",
                confidence="moderate",
                label="Storage",
                evidence=evidence,
            )
        if free_pct is not None and free_pct <= 20.0:
            return DiagnosticFinding(
                kind="storage_tight",
                headline="Storage getting tight",
                summary="Primary storage still has room, but free space is low enough to be worth watching.",
                severity="attention",
                confidence="moderate",
                label="Storage",
                evidence=evidence,
            )
        return DiagnosticFinding(
            kind="storage_healthy",
            headline="Storage healthy",
            summary="No strong evidence of disk pressure is visible right now.",
            severity="steady",
            confidence="moderate",
            label="Storage",
            evidence=evidence,
        )

    def assess_resources(self, resources: dict[str, Any], storage: dict[str, Any] | None = None) -> DiagnosticFinding:
        cpu = resources.get("cpu", {}) if isinstance(resources, dict) else {}
        memory = resources.get("memory", {}) if isinstance(resources, dict) else {}
        gpu_items = resources.get("gpu", []) if isinstance(resources, dict) else []
        primary_gpu = gpu_items[0] if isinstance(gpu_items, list) and gpu_items and isinstance(gpu_items[0], dict) else {}
        total = _float_or_none(memory.get("total_bytes"))
        used = _float_or_none(memory.get("used_bytes"))
        free = _float_or_none(memory.get("free_bytes"))
        memory_pct = (used / total) * 100 if total and used is not None else None
        cpu_util = _float_or_none(cpu.get("utilization_percent"))
        cpu_temp = _float_or_none(cpu.get("package_temperature_c"))
        gpu_temp = _float_or_none(primary_gpu.get("temperature_c"))
        storage_finding = self.assess_storage(storage or {})

        evidence = DiagnosticEvidenceBundle(
            metrics={
                "memory_percent": round(memory_pct or 0.0, 1) if memory_pct is not None else None,
                "cpu_utilization_percent": cpu_util,
                "cpu_temperature_c": cpu_temp,
                "gpu_temperature_c": gpu_temp,
            }
        )

        if memory_pct is not None and (memory_pct >= 85.0 or ((free or 0.0) <= 4 * 1024**3 and (used or 0.0) > 0)):
            return DiagnosticFinding(
                kind="memory_pressure",
                headline="Memory pressure elevated",
                summary="RAM usage is high enough that it may explain sluggishness. No equally strong disk or network bottleneck is visible right now.",
                severity="warning",
                confidence="moderate",
                label="Machine Load",
                evidence=evidence,
            )
        if cpu_util is not None and cpu_util >= 85.0:
            return DiagnosticFinding(
                kind="cpu_pressure",
                headline="CPU load elevated",
                summary="CPU load is high enough to explain general machine sluggishness right now.",
                severity="warning",
                confidence="moderate",
                label="Machine Load",
                evidence=evidence,
            )
        if (cpu_temp is not None and cpu_temp >= 90.0) or (gpu_temp is not None and gpu_temp >= 85.0):
            return DiagnosticFinding(
                kind="thermal_strain",
                headline="Thermal strain visible",
                summary="Thermal telemetry is high enough that throttling or fan-heavy behavior may be affecting responsiveness.",
                severity="warning",
                confidence="moderate",
                label="Machine Load",
                evidence=evidence,
            )
        if storage_finding.kind in {"disk_pressure", "storage_tight"}:
            return DiagnosticFinding(
                kind="storage_pressure",
                headline=storage_finding.headline,
                summary=storage_finding.summary,
                severity=storage_finding.severity,
                confidence=storage_finding.confidence,
                label="Machine Load",
                evidence=evidence,
            )
        return DiagnosticFinding(
            kind="resource_stable",
            headline="No strong machine-wide resource issue detected",
            summary="CPU, memory, and storage do not show one dominant system-wide bottleneck right now.",
            severity="steady",
            confidence="moderate",
            label="Machine Load",
            evidence=evidence,
        )

    def build_systems_interpretation(self, system_state: dict[str, Any]) -> SystemsInterpretationSnapshot:
        power_finding = self.assess_power(system_state.get("power", {}) if isinstance(system_state, dict) else {})
        storage_finding = self.assess_storage(system_state.get("storage", {}) if isinstance(system_state, dict) else {})
        resource_finding = self.assess_resources(
            system_state.get("resources", {}) if isinstance(system_state, dict) else {},
            system_state.get("storage", {}) if isinstance(system_state, dict) else {},
        )
        network_assessment = {}
        if isinstance(system_state, dict):
            network = system_state.get("network", {})
            if isinstance(network, dict) and isinstance(network.get("assessment"), dict):
                network_assessment = dict(network.get("assessment") or {})
        domains: list[dict[str, Any]] = []
        if network_assessment:
            domains.append(
                {
                    "key": "network",
                    "label": "Network",
                    "headline": str(network_assessment.get("headline") or "Network monitoring"),
                    "summary": str(network_assessment.get("summary") or ""),
                    "severity": "warning" if str(network_assessment.get("kind") or "") not in {"stable", "insufficient_evidence", ""} else "steady",
                    "confidence": str(network_assessment.get("confidence") or "low"),
                }
            )
        domains.append(resource_finding.to_dict(key="resources", label="Machine Load"))
        domains.append(power_finding.to_dict(key="power", label="Battery"))
        domains.append(storage_finding.to_dict(key="storage", label="Storage"))

        primary = next((domain for domain in domains if str(domain.get("severity")) == "warning"), None)
        if primary is None:
            primary = domains[0] if domains else {"headline": "Systems steady", "summary": "No interpreted system state is available yet."}
        return SystemsInterpretationSnapshot(
            headline=str(primary.get("headline") or "Systems steady"),
            summary=str(primary.get("summary") or "No interpreted system state is available yet."),
            domains=domains,
        )

    def build_watch_snapshot(
        self,
        *,
        jobs: list[dict[str, Any]],
        worker_capacity: int,
        default_timeout_seconds: float,
    ) -> WatchStateSnapshot:
        active = sum(1 for job in jobs if str(job.get("status", "")).lower() == "running")
        queued = sum(1 for job in jobs if str(job.get("status", "")).lower() == "queued")
        failed = sum(1 for job in jobs if str(job.get("status", "")).lower() in {"failed", "timed_out"})
        completed = sum(1 for job in jobs if str(job.get("status", "")).lower() == "completed")
        ordered = sorted(jobs, key=lambda item: _job_priority(str(item.get("status", ""))))
        tasks = [
            TaskProgressSnapshot(
                title=_tool_label(str(job.get("tool_name", "operation"))),
                status=str(job.get("status", "queued")).lower(),
                detail=self._job_detail(job),
                severity=_job_severity(str(job.get("status", ""))),
                meta=_short_time_label(str(job.get("finished_at") or job.get("started_at") or job.get("created_at") or "")),
            )
            for job in ordered[:8]
        ]
        headline_parts: list[str] = []
        if active:
            headline_parts.append(f"{active} running")
        if queued:
            headline_parts.append(f"{queued} queued")
        if failed:
            headline_parts.append(f"{failed} held failures")
        if not headline_parts:
            headline_parts.append("Worker deck clear")
        return WatchStateSnapshot(
            active_jobs=active,
            queued_jobs=queued,
            recent_failures=failed,
            completed_recently=completed,
            worker_capacity=worker_capacity,
            default_timeout_seconds=default_timeout_seconds,
            tasks=tasks,
            headline=" · ".join(headline_parts),
        )

    def build_signals(
        self,
        *,
        events: list[dict[str, Any]],
        jobs: list[dict[str, Any]],
        system_state: dict[str, Any],
    ) -> list[OperationalSignal]:
        signals: list[OperationalSignal] = []
        network = system_state.get("network", {}) if isinstance(system_state, dict) else {}
        assessment = network.get("assessment", {}) if isinstance(network, dict) else {}
        network_events = [event for event in events if str(event.get("source", "")).lower() == "network"]
        assessment_kind = str(assessment.get("kind") or "").strip().lower()
        if network_events and assessment_kind in {"local_link_issue", "upstream_issue", "dns_issue", "roam_or_ap_handoff", "weak_signal_possible"}:
            title_map = {
                "local_link_issue": "Wi-Fi instability detected",
                "upstream_issue": "Upstream instability detected",
                "dns_issue": "DNS trouble detected",
                "roam_or_ap_handoff": "Access point handoff detected",
                "weak_signal_possible": "Weak signal detected",
            }
            latest_network = network_events[-1]
            signals.append(
                OperationalSignal(
                    title=title_map.get(assessment_kind, str(assessment.get("headline") or "Network event")),
                    detail=str(assessment.get("summary") or self._event_detail(latest_network)),
                    severity="warning",
                    category="network",
                    source="systems",
                    meta=_signal_meta(latest_network),
                )
            )

        power_finding = self.assess_power(system_state.get("power", {}) if isinstance(system_state, dict) else {})
        if power_finding.kind == "drain_elevated":
            signals.append(
                OperationalSignal(
                    title="Battery drain elevated",
                    detail=power_finding.summary,
                    severity="warning",
                    category="power",
                    source="systems",
                )
            )

        storage_finding = self.assess_storage(system_state.get("storage", {}) if isinstance(system_state, dict) else {})
        if storage_finding.kind in {"disk_pressure", "storage_tight"}:
            signals.append(
                OperationalSignal(
                    title=storage_finding.headline,
                    detail=storage_finding.summary,
                    severity=storage_finding.severity,
                    category="storage",
                    source="systems",
                )
            )

        for job in jobs[:8]:
            status = str(job.get("status", "")).lower()
            result = job.get("result")
            workflow = {}
            if isinstance(result, dict):
                data = result.get("data")
                if isinstance(data, dict) and isinstance(data.get("workflow"), dict):
                    workflow = dict(data.get("workflow") or {})
            item_progress = workflow.get("item_progress") if isinstance(workflow.get("item_progress"), dict) else {}
            skipped = int(item_progress.get("skipped", 0) or 0)
            changed = int(item_progress.get("changed", 0) or 0)
            if status == "completed" and skipped > 0:
                signals.append(
                    OperationalSignal(
                        title=f"Cleanup skipped {skipped} items",
                        detail=f"Completed with {changed} changed and {skipped} skipped items.",
                        severity="attention",
                        category="workflow",
                        source="watch",
                        meta=_short_time_label(str(job.get("finished_at") or job.get("created_at") or "")),
                    )
                )
                continue
            if status in {"failed", "timed_out"}:
                signals.append(
                    OperationalSignal(
                        title=f"{_tool_label(str(job.get('tool_name', 'operation')))} failed",
                        detail=self._job_detail(job),
                        severity="warning",
                        category="workflow",
                        source="watch",
                        meta=_short_time_label(str(job.get("finished_at") or job.get("created_at") or "")),
                    )
                )

        deduped: list[OperationalSignal] = []
        seen_titles: set[str] = set()
        for signal in signals:
            key = signal.title.strip().lower()
            if not key or key in seen_titles:
                continue
            seen_titles.add(key)
            deduped.append(signal)
        return deduped[:8]

    def _job_detail(self, job: dict[str, Any]) -> str:
        status = str(job.get("status", "")).strip().lower()
        result = job.get("result")
        summary = str(result.get("summary", "")).strip() if isinstance(result, dict) else ""
        workflow = {}
        if isinstance(result, dict):
            data = result.get("data")
            if isinstance(data, dict) and isinstance(data.get("workflow"), dict):
                workflow = dict(data.get("workflow") or {})
        if status == "running":
            current_step = int(workflow.get("current_step_index", -1)) + 1 if workflow else 0
            steps = workflow.get("steps") if isinstance(workflow.get("steps"), list) else []
            total_steps = len(steps)
            if current_step > 0 and total_steps > 0:
                step = steps[current_step - 1] if current_step - 1 < len(steps) and isinstance(steps[current_step - 1], dict) else {}
                title = str(step.get("title", "")).strip()
                if title:
                    return f"Running step {current_step} of {total_steps}: {title}."
                return f"Running step {current_step} of {total_steps}."
            return "Running now."
        if status == "queued":
            return "Queued for dispatch."
        if status == "completed":
            return f"Completed cleanly: {summary}" if summary else "Completed cleanly."
        if status in {"failed", "timed_out", "cancelled"}:
            error = str(job.get("error", "")).strip()
            label = {"failed": "Failed", "timed_out": "Timed out", "cancelled": "Cancelled"}.get(status, status.title())
            if error:
                return f"{label}: {error}"
            return f"{label}."
        return summary or "Awaiting output."

    def _event_detail(self, event: dict[str, Any]) -> str:
        payload = event.get("payload", {})
        if isinstance(payload, dict):
            detail = str(payload.get("detail", "")).strip()
            if detail:
                return detail
        return str(event.get("message", "Recent signal")).strip()


def _float_or_none(value: object) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: object) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _duration_label(seconds: int) -> str:
    seconds = max(int(seconds), 0)
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _short_time_label(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return parsed.astimezone(timezone.utc).strftime("%H:%M")


def _signal_meta(event: dict[str, Any]) -> str:
    created_at = str(event.get("created_at") or event.get("timestamp") or "").strip()
    if created_at:
        return _short_time_label(created_at)
    seconds_ago = _int_or_none(event.get("seconds_ago"))
    if seconds_ago is None:
        return ""
    if seconds_ago < 60:
        return f"{seconds_ago}s ago"
    return f"{seconds_ago // 60}m ago"


def _tool_label(name: str) -> str:
    labels = {
        "workflow_execute": "Workflow",
        "maintenance_action": "Maintenance",
        "network_diagnosis": "Network",
        "power_diagnosis": "Power",
        "resource_diagnosis": "Resources",
        "storage_diagnosis": "Storage",
    }
    normalized = str(name or "").strip().lower()
    return labels.get(normalized, normalized.replace("_", " ").title() or "Operation")


def _job_severity(status: str) -> str:
    normalized = str(status or "").strip().lower()
    if normalized in {"failed", "timed_out"}:
        return "warning"
    if normalized == "cancelled":
        return "attention"
    return "steady"


def _job_priority(status: str) -> tuple[int, str]:
    normalized = str(status or "").strip().lower()
    rank = {
        "running": 0,
        "queued": 1,
        "failed": 2,
        "timed_out": 2,
        "cancelled": 3,
        "completed": 4,
    }.get(normalized, 5)
    return (rank, normalized)
