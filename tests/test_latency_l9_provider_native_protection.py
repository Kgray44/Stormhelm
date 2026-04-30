from __future__ import annotations

from stormhelm.core.provider_fallback import evaluate_provider_fallback_eligibility


def test_l9_provider_enabled_config_does_not_hijack_native_hot_paths() -> None:
    for family in ("calculations", "browser_destination", "software_control"):
        eligibility = evaluate_provider_fallback_eligibility(
            request_id=f"req-native-{family}",
            route_family=family,
            native_route_candidates=(family, "generic_provider"),
            native_route_winner=family,
            native_route_state="routed",
            provider_fallback_enabled=True,
            config_allows_provider=True,
            provider_availability_probe=lambda: (_ for _ in ()).throw(AssertionError("provider availability should not be checked")),
        )

        assert eligibility.provider_fallback_allowed is False
        assert eligibility.provider_fallback_blocked_reason == "provider_blocked_by_native_route"


def test_l9_provider_unavailable_does_not_change_native_block_decision() -> None:
    eligibility = evaluate_provider_fallback_eligibility(
        request_id="req-provider-unavailable",
        route_family="calculations",
        native_route_candidates=("calculations",),
        native_route_winner="calculations",
        native_route_state="routed",
        native_can_answer=True,
        provider_fallback_enabled=True,
        config_allows_provider=True,
        provider_available=False,
    )

    assert eligibility.provider_fallback_allowed is False
    assert eligibility.provider_fallback_blocked_reason == "provider_blocked_by_native_route"
    assert eligibility.provider_unavailable_reason == ""


def test_l9_provider_auth_missing_surfaces_for_eligible_provider_only() -> None:
    eligibility = evaluate_provider_fallback_eligibility(
        request_id="req-auth-missing",
        route_family="generic_provider",
        native_route_candidates=(),
        native_route_winner="",
        native_route_state="declined",
        provider_fallback_enabled=True,
        config_allows_provider=True,
        provider_available=False,
        provider_unavailable_reason="provider_auth_missing",
        user_requested_open_ended_reasoning=True,
    )

    assert eligibility.provider_fallback_allowed is False
    assert eligibility.provider_fallback_blocked_reason == "provider_auth_missing"
