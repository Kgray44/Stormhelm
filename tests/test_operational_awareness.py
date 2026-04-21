from __future__ import annotations

from stormhelm.core.operations.service import OperationalAwarenessService


def test_operational_awareness_flags_elevated_battery_drain() -> None:
    service = OperationalAwarenessService()

    finding = service.assess_power(
        {
            "available": True,
            "ac_line_status": "offline",
            "battery_percent": 78,
            "remaining_capacity_mwh": 52000,
            "full_charge_capacity_mwh": 70000,
            "rolling_power_draw_watts": 28.4,
            "instant_power_draw_watts": 31.0,
            "discharge_rate_watts": 30.5,
            "time_to_empty_seconds": 6500,
        }
    )

    assert finding.kind == "drain_elevated"
    assert finding.headline == "Battery drain elevated"
    assert "draining faster than usual" in finding.summary.lower()


def test_operational_awareness_flags_memory_pressure_as_primary_slowdown() -> None:
    service = OperationalAwarenessService()

    finding = service.assess_resources(
        {
            "cpu": {
                "name": "AMD Ryzen",
                "utilization_percent": 39.0,
                "package_temperature_c": 66.0,
            },
            "memory": {
                "total_bytes": 32 * 1024**3,
                "used_bytes": 29 * 1024**3,
                "free_bytes": 3 * 1024**3,
            },
            "gpu": [
                {
                    "name": "NVIDIA RTX",
                    "utilization_percent": 22.0,
                    "temperature_c": 58.0,
                }
            ],
        },
        {
            "drives": [
                {
                    "drive": "C:\\",
                    "total_bytes": 512 * 1024**3,
                    "free_bytes": 180 * 1024**3,
                    "used_bytes": 332 * 1024**3,
                }
            ]
        },
    )

    assert finding.kind == "memory_pressure"
    assert finding.headline == "Memory pressure elevated"
    assert "may explain sluggishness" in finding.summary.lower()


def test_operational_awareness_builds_interpreted_signals_from_system_and_job_outcomes() -> None:
    service = OperationalAwarenessService()

    signals = service.build_signals(
        events=[
            {
                "event_id": 1,
                "level": "INFO",
                "source": "core",
                "message": "Stormhelm core started.",
                "created_at": "2026-04-20T12:00:00Z",
            },
            {
                "event_id": 2,
                "level": "WARNING",
                "source": "network",
                "message": "Packet-loss burst",
                "created_at": "2026-04-20T12:01:00Z",
                "payload": {
                    "detail": "Gateway and external probes degraded together.",
                    "severity": "warning",
                },
            },
        ],
        jobs=[
            {
                "job_id": "job-maintenance",
                "tool_name": "maintenance_action",
                "status": "completed",
                "created_at": "2026-04-20T12:00:30Z",
                "finished_at": "2026-04-20T12:01:40Z",
                "result": {
                    "summary": "Archived older screenshots.",
                    "data": {
                        "workflow": {
                            "kind": "maintenance",
                            "steps": [{"title": "Archive older screenshots", "status": "completed"}],
                            "item_progress": {
                                "processed": 45,
                                "changed": 31,
                                "skipped": 4,
                                "total": 45,
                            },
                        }
                    },
                },
            }
        ],
        system_state={
            "network": {
                "assessment": {
                    "kind": "local_link_issue",
                    "headline": "Local Wi-Fi instability likely",
                    "summary": "Gateway and external probes degraded together, which points to the local link.",
                    "confidence": "moderate",
                }
            },
            "power": {
                "available": True,
                "ac_line_status": "offline",
                "battery_percent": 74,
                "rolling_power_draw_watts": 27.5,
            },
        },
    )

    titles = [signal.title for signal in signals]

    assert "Wi-Fi instability detected" in titles
    assert any("skipped" in signal.title.lower() for signal in signals)


def test_operational_awareness_watch_snapshot_prioritizes_active_progress_and_recent_failures() -> None:
    service = OperationalAwarenessService()

    watch = service.build_watch_snapshot(
        jobs=[
            {
                "job_id": "job-running",
                "tool_name": "workflow_execute",
                "status": "running",
                "created_at": "2026-04-20T12:00:00Z",
                "started_at": "2026-04-20T12:00:01Z",
                "result": {
                    "summary": "Running step 2 of 3.",
                    "data": {
                        "workflow": {
                            "kind": "diagnostics_setup",
                            "current_step_index": 1,
                            "steps": [
                                {"title": "Restore context", "status": "completed"},
                                {"title": "Run network diagnostics", "status": "running"},
                                {"title": "Open systems surface", "status": "pending"},
                            ],
                        }
                    },
                },
            },
            {
                "job_id": "job-failed",
                "tool_name": "maintenance_action",
                "status": "failed",
                "created_at": "2026-04-20T11:58:00Z",
                "finished_at": "2026-04-20T11:58:12Z",
                "error": "locked file prevented archive",
            },
        ],
        worker_capacity=6,
        default_timeout_seconds=30,
    )

    assert watch.active_jobs == 1
    assert watch.recent_failures == 1
    assert watch.tasks[0].status == "running"
    assert "step 2 of 3" in watch.tasks[0].detail.lower()
