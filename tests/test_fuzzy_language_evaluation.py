from __future__ import annotations

from stormhelm.config.models import SoftwareControlConfig
from stormhelm.core.orchestrator.fuzzy_eval import ClarificationExpectation
from stormhelm.core.orchestrator.fuzzy_eval import ClarificationQualityClass
from stormhelm.core.orchestrator.fuzzy_eval import CoverageTier
from stormhelm.core.orchestrator.fuzzy_eval import EvaluationExpectation
from stormhelm.core.orchestrator.fuzzy_eval import FuzzyDecisionObservation
from stormhelm.core.orchestrator.fuzzy_eval import FuzzyEvaluationRunner
from stormhelm.core.orchestrator.fuzzy_eval import NativeUtilizationClass
from stormhelm.core.orchestrator.fuzzy_eval import RouteHitClass
from stormhelm.core.orchestrator.fuzzy_eval import SupportAugmentationClass
from stormhelm.core.orchestrator.fuzzy_eval import build_fuzzy_language_corpus
from stormhelm.core.orchestrator.fuzzy_eval import classify_route_hit
from stormhelm.core.orchestrator.planner import DeterministicPlanner


def test_fuzzy_corpus_defines_required_route_suites_and_doctrine_tiers() -> None:
    corpus = build_fuzzy_language_corpus()

    required_families = {
        "calculations",
        "screen_awareness",
        "software_control",
        "software_recovery",
        "discord_relay",
        "task_continuity",
        "trust_approvals",
        "memory_recall",
        "workspace_operations",
        "lifecycle",
        "watch_runtime",
        "generic_provider",
    }

    assert required_families <= set(corpus.route_family_suites)
    assert corpus.route_family_suites["memory_recall"].coverage_tier == CoverageTier.ACTIVE_DOCTRINE
    assert corpus.route_family_suites["lifecycle"].coverage_tier == CoverageTier.ACTIVE_DOCTRINE

    relay_suite = corpus.route_family_suites["discord_relay"]
    assert relay_suite.coverage_tier == CoverageTier.LANDED_FOUNDATION
    assert relay_suite.required_styles <= relay_suite.covered_styles

    install_family = corpus.paraphrase_families["software_install_firefox"]
    assert install_family.route_family == "software_control"
    assert len(install_family.case_ids) >= 4


def test_route_hit_classifier_distinguishes_provider_punts_and_fabricated_confidence() -> None:
    punt_expectation = EvaluationExpectation(
        expected_route_family="software_control",
        clarification=ClarificationExpectation.none(),
        expected_native_tools=("app_control", "window_control", "system_control"),
    )
    punt_observation = FuzzyDecisionObservation(
        route_family="generic_provider",
        posture="genuine_provider_fallback",
        status="provider_fallback",
        response_mode="summary_result",
    )
    assert classify_route_hit(punt_expectation, punt_observation) == RouteHitClass.PUNT_MISS

    fabricated_expectation = EvaluationExpectation(
        expected_route_family="discord_relay",
        clarification=ClarificationExpectation(required=True, allowed_codes=("ambiguous_relay_payload",)),
        expected_native_tools=("discord_relay",),
    )
    fabricated_observation = FuzzyDecisionObservation(
        route_family="discord_relay",
        posture="clear_winner",
        status="immediate",
        response_mode="action_result",
        ambiguity_live=True,
        runner_up_family="browser_destination",
        planned_tools=("discord_relay",),
        support_systems=("deictic_binding",),
        deictic_source="selection",
    )
    assert classify_route_hit(fabricated_expectation, fabricated_observation) == RouteHitClass.FABRICATED_CONFIDENCE_MISS


def test_fuzzy_runner_evaluates_real_planner_cases_against_live_route_behavior() -> None:
    software_control_config = SoftwareControlConfig(enabled=True, planner_routing_enabled=True)
    runner = FuzzyEvaluationRunner(
        planners={
            "default": DeterministicPlanner(),
            "software_control": DeterministicPlanner(software_control_config=software_control_config),
        }
    )
    corpus = build_fuzzy_language_corpus()

    install_result = runner.evaluate_case(corpus.cases_by_id["software_install_messy_phrase"])
    clarification_result = runner.evaluate_case(corpus.cases_by_id["relay_payload_ambiguity"])
    trust_result = runner.evaluate_case(corpus.cases_by_id["trust_explain_pending_install"])
    activity_result = runner.evaluate_case(corpus.cases_by_id["watch_runtime_recent_activity"])

    assert install_result.route_hit == RouteHitClass.STRONG_HIT
    assert install_result.utilization == NativeUtilizationClass.NATIVE_MATCH
    assert install_result.observation.route_family == "software_control"

    assert clarification_result.route_hit == RouteHitClass.CLARIFIED_HIT
    assert clarification_result.clarification_quality == ClarificationQualityClass.MINIMAL_CANDIDATE_SPECIFIC
    assert clarification_result.observation.clarification_code == "ambiguous_relay_payload"

    assert trust_result.route_hit == RouteHitClass.STRONG_HIT
    assert trust_result.support_augmentation == SupportAugmentationClass.EXPECTED_ENGAGED
    assert "trust" in trust_result.observation.support_systems

    assert activity_result.route_hit == RouteHitClass.STRONG_HIT
    assert activity_result.observation.route_family == "watch_runtime"


def test_fuzzy_runner_evaluates_deictic_follow_up_chain_without_stale_rebinding() -> None:
    runner = FuzzyEvaluationRunner(planners={"default": DeterministicPlanner()})
    corpus = build_fuzzy_language_corpus()

    chain_result = runner.evaluate_chain(corpus.follow_up_chains["relay_preview_then_confirm"], corpus=corpus)

    assert chain_result.turn_results[0].route_hit == RouteHitClass.STRONG_HIT
    assert chain_result.turn_results[1].route_hit == RouteHitClass.STRONG_HIT
    assert chain_result.turn_results[1].observation.deictic_source == "active_preview"
    assert chain_result.turn_results[1].observation.route_family == "discord_relay"
