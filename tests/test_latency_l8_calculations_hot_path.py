from __future__ import annotations

import pytest

from stormhelm.config.models import CalculationsConfig
from stormhelm.core.calculations import service as calc_service
from stormhelm.core.calculations.helpers import get_cached_helper_registry
from stormhelm.core.calculations.helpers import helper_registry_cache_clear
from stormhelm.core.calculations.helpers import helper_registry_cache_info
from stormhelm.core.calculations.models import CalculationOutputMode
from stormhelm.core.calculations.models import CalculationRequest
from stormhelm.core.calculations.service import CalculationsSubsystem


def test_answer_only_calculation_does_not_generate_explanation(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_if_called(*args: object, **kwargs: object) -> object:
        raise AssertionError("answer-only hot path should not render explanation")

    monkeypatch.setattr(calc_service, "render_direct_explanation", fail_if_called)
    subsystem = CalculationsSubsystem(config=CalculationsConfig())

    response = subsystem.handle_request(
        session_id="s",
        operator_text="2 + 2",
        surface_mode="ghost",
        active_module="chartroom",
        request=CalculationRequest(
            request_id="calc-l8-answer-only",
            source_surface="ghost",
            raw_input="2 + 2",
            user_visible_text="2 + 2",
            extracted_expression="2 + 2",
            requested_mode=CalculationOutputMode.ANSWER_ONLY,
        ),
    )

    assert response.result is not None
    assert response.result.formatted_value == "4"
    assert response.result.explanation is None
    assert response.assistant_response == "4"
    assert response.trace.explanation_mode_used == "answer_only"
    assert response.trace.explanation_source_type == "lazy_skipped"
    assert response.trace.hot_path_name == "direct_deterministic_calculation"
    assert response.trace.provider_fallback_used is False
    assert response.trace.heavy_context_used is False


def test_calculation_helper_registry_is_cached_for_hot_path_reuse() -> None:
    helper_registry_cache_clear()

    first = get_cached_helper_registry()
    second = get_cached_helper_registry()
    info = helper_registry_cache_info()

    assert first is second
    assert info.currsize == 1
    assert info.hits >= 1


def test_engineering_suffix_expression_stays_native_and_fast() -> None:
    subsystem = CalculationsSubsystem(config=CalculationsConfig())

    response = subsystem.handle_request(
        session_id="s",
        operator_text="4.7k + 300",
        surface_mode="ghost",
        active_module="chartroom",
    )

    assert response.result is not None
    assert response.result.formatted_value == "5k"
    assert response.trace.route_selected == "deterministic_local_expression"
    assert response.trace.provider_fallback_used is False
    assert response.trace.heavy_context_used is False
    assert response.trace.cache_policy_id == "calculations_helper_registry_cache"
