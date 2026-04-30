from __future__ import annotations

from stormhelm.config.loader import load_config
from stormhelm.core.provider_fallback import evaluate_provider_fallback_eligibility


def test_l9_provider_fallback_disabled_by_default(temp_project_root) -> None:
    config = load_config(project_root=temp_project_root, env={})

    assert config.provider_fallback.enabled is False
    eligibility = evaluate_provider_fallback_eligibility(
        request_id="req-default-disabled",
        route_family="generic_provider",
        native_route_candidates=(),
        native_route_winner="",
        native_route_state="declined",
        provider_fallback_enabled=config.provider_fallback.enabled,
        config_allows_provider=config.provider_fallback.enabled,
        user_requested_open_ended_reasoning=True,
    )

    assert eligibility.provider_fallback_allowed is False
    assert eligibility.provider_fallback_blocked_reason == "provider_disabled"


def test_l9_provider_blocks_native_calculation_even_when_enabled() -> None:
    eligibility = evaluate_provider_fallback_eligibility(
        request_id="req-calc",
        route_family="calculations",
        native_route_candidates=("calculations", "generic_provider"),
        native_route_winner="calculations",
        native_route_state="routed",
        native_can_answer=True,
        provider_fallback_enabled=True,
        config_allows_provider=True,
        user_requested_open_ended_reasoning=True,
    )

    assert eligibility.provider_fallback_allowed is False
    assert eligibility.provider_fallback_blocked_reason == "provider_blocked_by_native_route"
    assert eligibility.native_route_winner == "calculations"


def test_l9_provider_blocks_native_browser_software_trust_voice_relay_screen_routes() -> None:
    protected = [
        "browser_destination",
        "software_control",
        "trust_approvals",
        "voice_control",
        "discord_relay",
        "screen_awareness",
    ]

    for family in protected:
        eligibility = evaluate_provider_fallback_eligibility(
            request_id=f"req-{family}",
            route_family=family,
            native_route_candidates=(family,),
            native_route_winner=family,
            native_route_state="planning",
            provider_fallback_enabled=True,
            config_allows_provider=True,
            user_requested_open_ended_reasoning=True,
        )
        assert eligibility.provider_fallback_allowed is False
        assert eligibility.provider_fallback_blocked_reason == "provider_blocked_by_native_route"


def test_l9_provider_eligible_for_open_ended_reasoning_when_enabled_and_safe() -> None:
    eligibility = evaluate_provider_fallback_eligibility(
        request_id="req-open-ended",
        route_family="generic_provider",
        native_route_candidates=(),
        native_route_winner="",
        native_route_state="declined",
        provider_fallback_enabled=True,
        config_allows_provider=True,
        trust_allows_provider=True,
        privacy_allows_provider=True,
        payload_safe_for_provider=True,
        user_requested_open_ended_reasoning=True,
    )

    assert eligibility.provider_fallback_allowed is True
    assert eligibility.provider_fallback_reason == "open_ended_reasoning_allowed"
    assert eligibility.provider_fallback_blocked_reason == ""


def test_l9_provider_eligible_after_native_explicit_decline_when_enabled() -> None:
    eligibility = evaluate_provider_fallback_eligibility(
        request_id="req-native-decline",
        route_family="unsupported",
        native_route_candidates=("screen_awareness",),
        native_route_winner="unsupported",
        native_route_state="declined",
        native_decline_code="unsupported_capability",
        provider_fallback_enabled=True,
        config_allows_provider=True,
        trust_allows_provider=True,
        privacy_allows_provider=True,
        payload_safe_for_provider=True,
    )

    assert eligibility.provider_fallback_allowed is True
    assert eligibility.provider_fallback_reason == "native_decline_allowed"
    assert eligibility.native_decline_code == "unsupported_capability"


def test_l9_provider_blocks_unsafe_payloads() -> None:
    eligibility = evaluate_provider_fallback_eligibility(
        request_id="req-unsafe",
        route_family="generic_provider",
        native_route_candidates=(),
        native_route_winner="",
        native_route_state="declined",
        provider_fallback_enabled=True,
        config_allows_provider=True,
        payload_safe_for_provider=False,
        user_requested_open_ended_reasoning=True,
    )

    assert eligibility.provider_fallback_allowed is False
    assert eligibility.provider_fallback_blocked_reason == "provider_payload_not_safe"
    assert eligibility.payload_safe_for_provider is False
