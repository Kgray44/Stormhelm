from __future__ import annotations

from stormhelm.core.orchestrator.browser_destinations import BrowserDestinationResolver
from stormhelm.core.subsystem_latency import SubsystemLatencyMode


def test_direct_url_browser_open_plan_ack_is_separate_from_external_load() -> None:
    resolver = BrowserDestinationResolver()
    request = resolver.parse("open https://example.com", surface_mode="ghost")
    assert request is not None

    resolution = resolver.resolve(request)
    plan = resolver.build_open_plan(resolution)

    assert resolution.success is True
    assert resolution.resolution_kind == "direct_domain"
    assert plan.latency_mode == SubsystemLatencyMode.PLAN_FIRST.value
    assert plan.external_load_blocking is False
    assert plan.load_verification_required is True
    assert plan.tool_arguments["ack_stage"] == "open_requested"
    assert plan.tool_arguments["external_load_blocking"] is False
    assert plan.tool_arguments["verification_stage"] == "separate_adapter_evidence"
    assert plan.tool_arguments["provider_fallback_allowed"] is False


def test_known_destination_browser_plan_uses_native_cache_not_provider_fallback() -> None:
    resolver = BrowserDestinationResolver()
    request = resolver.parse("open youtube", surface_mode="ghost")
    assert request is not None

    resolution = resolver.resolve(request)
    plan = resolver.build_open_plan(resolution)

    assert resolution.success is True
    assert resolution.resolution_kind == "known_destination"
    assert plan.cache_policy_id == "browser_known_destination_cache"
    assert plan.provider_fallback_used is False
    assert "requested" in plan.response_contract["micro_response"].lower()
    assert "verified" not in plan.response_contract["micro_response"].lower()
