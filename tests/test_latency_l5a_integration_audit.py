from __future__ import annotations

import json

from stormhelm.core.latency_integration_audit import AuditRecommendation
from stormhelm.core.latency_integration_audit import AuditStatus
from stormhelm.core.latency_integration_audit import build_latency_integration_audit
from stormhelm.core.latency_integration_audit import render_latency_integration_audit_markdown


def _items_by_id() -> dict[str, object]:
    audit = build_latency_integration_audit()
    return {item.feature_id: item for item in audit.items}


def test_l5a_inventory_includes_all_latency_phase_categories() -> None:
    audit = build_latency_integration_audit()

    categories = {item.category for item in audit.items}

    assert {
        "L0 tracing",
        "L1 budgets and partial response",
        "L2 route triage",
        "L3 context snapshots",
        "L4 async progress",
        "L4.1 worker scheduler",
        "L4.2/L4.3 subsystem continuations",
        "L4.4 validation and Kraken",
        "L4.5 scheduler hardening",
        "L5 voice streaming",
        "UI/status/reporting surfaces",
    }.issubset(categories)


def test_l5a_inventory_items_are_typed_recommended_and_not_unknown_for_critical_features() -> None:
    audit = build_latency_integration_audit()
    critical_ids = {
        "l0.latency_trace_contract",
        "l0.chat_send_metadata",
        "l1.route_latency_policy",
        "l2.fast_route_classifier",
        "l3.context_snapshot_store",
        "l4.async_route_progress_contract",
        "l41.job_manager_lane_timing",
        "l42.workspace_assemble_deep_continuation",
        "l45.priority_scheduler_and_caps",
        "l5.voice_first_audio_metrics",
    }

    for item in audit.items:
        assert item.current_status in set(AuditStatus)
        assert item.recommended_action in set(AuditRecommendation)
        assert item.current_status != AuditStatus.UNKNOWN
        assert item.evidence or item.missing_evidence

    indexed = {item.feature_id: item for item in audit.items}
    assert critical_ids.issubset(indexed)
    assert all(indexed[feature_id].current_status != AuditStatus.UNKNOWN for feature_id in critical_ids)


def test_l5a_live_used_items_have_runtime_test_and_visibility_evidence() -> None:
    audit = build_latency_integration_audit()

    live_items = [item for item in audit.items if item.current_status == AuditStatus.LIVE_USED]

    assert live_items
    for item in live_items:
        assert item.runtime_entrypoints, item.feature_id
        assert item.test_coverage, item.feature_id
        assert item.trace_fields or item.status_surface or item.kraken_fields, item.feature_id


def test_l5a_known_scaffolds_and_deferred_paths_are_labeled_honestly() -> None:
    items = _items_by_id()

    assert items["l43.screen_awareness_verify_change_continuation"].current_status == AuditStatus.POLICY_ONLY
    assert items["l43.screen_awareness_verify_change_continuation"].recommended_action == AuditRecommendation.DEFER_TO_PHASE
    assert items["l42.software_execute_approved_operation_continuation"].current_status == AuditStatus.POLICY_ONLY
    assert items["l41.background_refresh_hook"].current_status == AuditStatus.SCAFFOLD_ONLY
    assert items["l45.retry_yield_cancellation_cooperation"].current_status == AuditStatus.PARTIAL_USED
    assert items["l5.true_openai_http_streaming"].current_status == AuditStatus.LIVE_USED
    assert items["l5.local_live_playback_backend_streaming"].current_status == AuditStatus.LIVE_USED
    assert items["l5.normal_assistant_voice_output_streaming"].current_status == AuditStatus.LIVE_USED
    assert items["l5.normal_assistant_voice_output_streaming"].recommended_phase == "L6"


def test_l5a_subsystem_continuation_audit_separates_handler_from_normal_route_usage() -> None:
    items = _items_by_id()

    assert items["l42.workspace_assemble_deep_continuation"].current_status == AuditStatus.LIVE_USED
    assert "AssistantOrchestrator._queue_workspace_assembly_continuation" in items[
        "l42.workspace_assemble_deep_continuation"
    ].runtime_entrypoints
    assert items["l43.workspace_restore_deep_continuation"].current_status == AuditStatus.PARTIAL_USED
    assert "handler registered" in " ".join(items["l43.workspace_restore_deep_continuation"].evidence)
    assert "not automatically created by /chat/send front half" in " ".join(
        items["l43.workspace_restore_deep_continuation"].missing_evidence
    )
    assert items["l43.software_verify_operation_continuation"].current_status == AuditStatus.PARTIAL_USED
    assert items["l43.network_live_diagnosis_continuation"].current_status == AuditStatus.PARTIAL_USED


def test_l5a_audit_report_builder_is_deterministic_and_serializes_safely() -> None:
    first = build_latency_integration_audit().to_dict()
    second = build_latency_integration_audit().to_dict()

    assert len(first["items"]) == first["summary"]["item_count"]
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    serialized = json.dumps(first, sort_keys=True)
    assert "api_key" not in serialized.lower()
    assert "authorization" not in serialized.lower()
    assert "raw_audio" not in serialized.lower()
    assert "generated_audio_bytes" not in serialized.lower()


def test_l5a_markdown_report_contains_required_sections_and_evidence_table() -> None:
    markdown = render_latency_integration_audit_markdown(build_latency_integration_audit())

    assert "# Stormhelm Latency Integration Audit" in markdown
    assert "## Fully Live And Used" in markdown
    assert "## Partially Wired" in markdown
    assert "## Scaffold Or Policy Only" in markdown
    assert "## Recommended L5.1 Scope" in markdown
    assert "| Feature | Phase | Status | Runtime usage | Test coverage | Trace/Kraken visibility | Risk | Recommendation | Future phase |" in markdown
    assert "l5.normal_assistant_voice_output_streaming" in markdown
