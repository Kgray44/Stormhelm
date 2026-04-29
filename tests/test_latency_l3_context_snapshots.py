from __future__ import annotations

import json

from fastapi.testclient import TestClient

from stormhelm.core.api.app import create_app
from stormhelm.core.context_snapshots import ContextSnapshot
from stormhelm.core.context_snapshots import ContextSnapshotFamily
from stormhelm.core.context_snapshots import ContextSnapshotFreshness
from stormhelm.core.context_snapshots import ContextSnapshotPolicy
from stormhelm.core.context_snapshots import ContextSnapshotSource
from stormhelm.core.context_snapshots import ContextSnapshotStore
from stormhelm.core.context_snapshots import describe_snapshot_freshness
from stormhelm.core.orchestrator.command_eval.models import CommandEvalCase
from stormhelm.core.orchestrator.command_eval.models import CommandEvalResult
from stormhelm.core.orchestrator.command_eval.models import CoreObservation
from stormhelm.core.orchestrator.command_eval.models import ExpectedBehavior
from stormhelm.core.orchestrator.command_eval.report import build_checkpoint_summary


def _post_chat(client: TestClient, message: str, *, session_id: str = "latency-l3") -> dict[str, object]:
    response = client.post(
        "/chat/send",
        json={
            "message": message,
            "session_id": session_id,
            "surface_mode": "ghost",
            "active_module": "chartroom",
            "response_profile": "command_eval_compact",
        },
    )
    assert response.status_code == 200
    return response.json()["assistant_message"]["metadata"]


def test_context_snapshot_serializes_with_redaction_and_bounds() -> None:
    snapshot = ContextSnapshot.create(
        family=ContextSnapshotFamily.ACTIVE_WORKSPACE,
        source=ContextSnapshotSource.RUNTIME,
        created_at_ms=1_000.0,
        ttl_ms=30_000,
        payload_summary={
            "title": "Current workspace",
            "api_key": "sk-secret",
            "authorization": "Bearer secret",
            "raw_audio": b"abc",
            "generated_audio_bytes": b"def",
            "large": "x" * 10_000,
        },
        max_payload_bytes=512,
    )

    payload = snapshot.to_dict(now_ms=1_010.0)
    encoded = json.dumps(payload)

    assert payload["freshness_state"] == "fresh"
    assert payload["payload_summary"]["api_key"] == "<redacted>"
    assert payload["payload_summary"]["authorization"] == "<redacted>"
    assert payload["payload_summary"]["raw_audio"] == "<bytes:redacted>"
    assert payload["payload_summary"]["generated_audio_bytes"] == "<bytes:redacted>"
    assert len(encoded) < 1400


def test_snapshot_policy_freshness_expiration_and_invalidated_truth() -> None:
    policy = ContextSnapshotPolicy.for_family(ContextSnapshotFamily.SCREEN_CONTEXT)
    snapshot = ContextSnapshot.create(
        family=ContextSnapshotFamily.SCREEN_CONTEXT,
        source=ContextSnapshotSource.RUNTIME,
        created_at_ms=1_000.0,
        ttl_ms=policy.ttl_ms,
        payload_summary={"window": "Example"},
    )

    assert snapshot.freshness(now_ms=1_000.0 + policy.ttl_ms - 1).state == ContextSnapshotFreshness.FRESH
    assert snapshot.freshness(now_ms=1_000.0 + policy.ttl_ms + 1).state == ContextSnapshotFreshness.USABLE_STALE

    trust_policy = ContextSnapshotPolicy.for_family(ContextSnapshotFamily.PENDING_TRUST)
    trust_snapshot = ContextSnapshot.create(
        family=ContextSnapshotFamily.PENDING_TRUST,
        source=ContextSnapshotSource.TRUST,
        created_at_ms=1_000.0,
        ttl_ms=trust_policy.ttl_ms,
        payload_summary={"request_id": "trust-1"},
    )
    assert trust_snapshot.freshness(now_ms=1_000.0 + trust_policy.ttl_ms + 1).state == ContextSnapshotFreshness.EXPIRED

    invalidated = snapshot.invalidate("focus_changed")
    assert invalidated.freshness(now_ms=1_001.0).state == ContextSnapshotFreshness.INVALIDATED
    assert invalidated.safe_for_user_claims is False
    assert invalidated.safe_for_deictic_binding is False


def test_context_snapshot_store_uses_fresh_hit_refreshes_expired_and_invalidates() -> None:
    now = [1_000.0]
    calls = {"count": 0}
    store = ContextSnapshotStore(clock_ms=lambda: now[0])
    policy = ContextSnapshotPolicy(ttl_ms=100, allow_stale_use=False, supports_user_claims=True)

    def refresh() -> dict[str, object]:
        calls["count"] += 1
        return {"value": calls["count"]}

    first = store.get_or_refresh(
        ContextSnapshotFamily.PROVIDER_READINESS,
        refresh_fn=refresh,
        policy=policy,
    )
    second = store.get_or_refresh(
        ContextSnapshotFamily.PROVIDER_READINESS,
        refresh_fn=refresh,
        policy=policy,
    )
    now[0] = 1_200.0
    third = store.get_or_refresh(
        ContextSnapshotFamily.PROVIDER_READINESS,
        refresh_fn=refresh,
        policy=policy,
    )
    store.invalidate(family=ContextSnapshotFamily.PROVIDER_READINESS, reason="config_reload")
    fourth = store.get_snapshot(ContextSnapshotFamily.PROVIDER_READINESS)

    assert first.refreshed is True
    assert second.hot_path_hit is True
    assert third.refreshed is True
    assert calls["count"] == 2
    assert fourth is None
    assert store.snapshot_summary()["invalidation_count"] == 1


def test_freshness_wording_refuses_current_claims_for_stale_or_hint_snapshots() -> None:
    workspace = ContextSnapshot.create(
        family=ContextSnapshotFamily.ACTIVE_WORKSPACE,
        source=ContextSnapshotSource.RUNTIME,
        created_at_ms=1_000.0,
        ttl_ms=5_000,
        payload_summary={"title": "Workspace"},
    )
    screen = ContextSnapshot.create(
        family=ContextSnapshotFamily.SCREEN_CONTEXT,
        source=ContextSnapshotSource.RUNTIME,
        created_at_ms=1_000.0,
        ttl_ms=250,
        payload_summary={"window": "Old window"},
    )
    clipboard = ContextSnapshot.create(
        family=ContextSnapshotFamily.CLIPBOARD_HINT,
        source=ContextSnapshotSource.CLIPBOARD,
        created_at_ms=1_000.0,
        ttl_ms=2_000,
        payload_summary={"text": "copied value"},
    )

    assert "last workspace snapshot" in describe_snapshot_freshness(workspace, now_ms=8_000.0)
    assert "prior screen observation" in describe_snapshot_freshness(screen, now_ms=2_000.0)
    assert "clipboard value is only a hint" in describe_snapshot_freshness(clipboard, now_ms=1_100.0)


def test_chat_send_calculation_records_snapshot_hot_path_without_heavy_context(temp_config) -> None:
    app = create_app(temp_config)

    with TestClient(app) as client:
        _post_chat(client, "47k / 2.2u", session_id="latency-l3-calc")
        metadata = _post_chat(client, "48k / 2u", session_id="latency-l3-calc")

    summary = metadata["latency_summary"]

    assert summary["heavy_context_loaded"] is False
    assert "provider_readiness" in summary["snapshots_checked"]
    assert summary["snapshot_hot_path_hit"] is True
    assert summary["heavy_context_avoided_by_snapshot"] is True


def test_chat_send_software_and_discord_routes_record_family_snapshots(temp_config) -> None:
    app = create_app(temp_config)

    with TestClient(app) as client:
        software_metadata = _post_chat(client, "install Minecraft", session_id="latency-l3-software")
        relay_metadata = _post_chat(client, "send this to Baby", session_id="latency-l3-relay")

    software_summary = software_metadata["latency_summary"]
    relay_summary = relay_metadata["latency_summary"]

    assert "software_catalog" in software_summary["snapshots_checked"]
    assert "software_catalog" in software_summary["snapshots_refreshed"] + software_summary["snapshots_used"]
    assert software_summary["snapshot_freshness"]["software_catalog"] == "fresh"
    assert "discord_aliases" in relay_summary["snapshots_checked"]
    assert relay_summary["heavy_context_loaded"] is True
    assert relay_metadata["partial_response"]["completion_claimed"] is False


def test_trust_pending_snapshot_refuses_stale_approval_binding() -> None:
    now = [1_000.0]
    store = ContextSnapshotStore(clock_ms=lambda: now[0])
    policy = ContextSnapshotPolicy.for_family(ContextSnapshotFamily.PENDING_TRUST)
    store.set_snapshot(
        ContextSnapshot.create(
            family=ContextSnapshotFamily.PENDING_TRUST,
            source=ContextSnapshotSource.TRUST,
            created_at_ms=now[0],
            ttl_ms=policy.ttl_ms,
            session_id="trust-session",
            payload_summary={"request_id": "trust-1"},
            safe_for_deictic_binding=True,
        )
    )

    now[0] += policy.ttl_ms + 1

    assert store.get_snapshot(
        ContextSnapshotFamily.PENDING_TRUST,
        session_id="trust-session",
        require_current=True,
    ) is None
    assert store.get_snapshot(
        ContextSnapshotFamily.PENDING_TRUST,
        session_id="trust-session",
        allow_usable_stale=True,
    ) is None


def test_latency_l3_fields_flow_into_kraken_rows_and_aggregates() -> None:
    case = CommandEvalCase(
        case_id="l3-row-1",
        message="install Minecraft",
        expected=ExpectedBehavior(route_family="software_control", subsystem="software"),
    )
    observation = CoreObservation(
        case_id=case.case_id,
        input_boundary="POST /chat/send",
        latency_ms=800.0,
        ui_response="Prepared the software plan.",
        actual_route_family="software_control",
        actual_subsystem="software",
        result_state="plan_ready",
        stage_timings_ms={
            "route_triage_ms": 1.0,
            "snapshot_lookup_ms": 2.0,
            "planner_route_ms": 25.0,
        },
        latency_summary={
            "execution_mode": "plan_first",
            "snapshots_checked": ["provider_readiness", "software_catalog"],
            "snapshots_used": ["software_catalog"],
            "snapshots_refreshed": ["provider_readiness"],
            "snapshot_hot_path_hit": True,
            "snapshot_miss_reason": {"provider_readiness": "missing"},
            "snapshot_age_ms": {"software_catalog": 50.0},
            "stale_snapshot_used_cautiously": False,
            "heavy_context_avoided_by_snapshot": True,
            "invalidation_count": 1,
            "freshness_warnings": ["software catalog is for planning, not verification"],
            "longest_stage": "planner_route_ms",
            "longest_stage_ms": 25.0,
        },
        budget_result={
            "budget_label": "ghost_interactive",
            "target_ms": 1500.0,
            "soft_ceiling_ms": 2500.0,
            "hard_ceiling_ms": 5000.0,
            "budget_exceeded": False,
            "hard_ceiling_exceeded": False,
            "async_continuation_expected": False,
        },
    )
    result = CommandEvalResult(case=case, observation=observation, assertions={})

    row = result.to_dict()
    report = build_checkpoint_summary([result])["kraken_latency_report"]

    assert row["snapshot_hot_path_hit"] is True
    assert row["snapshots_used"] == ["software_catalog"]
    assert row["heavy_context_avoided_by_snapshot"] is True
    assert report["snapshot_hit_rate"] == 1.0
    assert report["snapshot_miss_count_by_family"]["provider_readiness"] == 1
    assert report["heavy_context_avoidance_count"] == 1
    assert report["invalidation_events_count"] == 1
