from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CoverageTier(StrEnum):
    LANDED_FOUNDATION = "landed_foundation"
    ACTIVE_DOCTRINE = "active_doctrine"
    FUTURE_TARGET = "future_target"


class WordingStyle(StrEnum):
    CLEAN_IMPERATIVE = "clean_imperative"
    POLITE_REQUEST = "polite_request"
    SHORTHAND = "shorthand"
    INDIRECT_REQUEST = "indirect_request"
    DEICTIC_REQUEST = "deictic_request"
    FOLLOW_UP_REQUEST = "follow_up_request"
    CORRECTION = "correction"
    COMPLAINT = "complaint"
    NEAR_MISS = "near_miss"
    WRONG_ROUTE_PRESSURE = "wrong_route_pressure"


class AmbiguityClass(StrEnum):
    NONE = "none"
    TARGET = "target"
    ACTION = "action"
    ROUTE_FAMILY = "route_family"
    PROVENANCE = "provenance"
    TEMPORAL = "temporal"
    CORRECTION = "correction"
    SAFETY_SCOPE = "safety_scope"


class RouteHitClass(StrEnum):
    STRONG_HIT = "strong_hit"
    CLARIFIED_HIT = "clarified_hit"
    WEAK_HIT = "weak_hit"
    WRONG_ROUTE_MISS = "wrong_route_miss"
    PUNT_MISS = "punt_miss"
    FABRICATED_CONFIDENCE_MISS = "fabricated_confidence_miss"


class ClarificationQualityClass(StrEnum):
    NOT_NEEDED = "not_needed"
    MINIMAL_CANDIDATE_SPECIFIC = "minimal_candidate_specific"
    BROAD_GENERIC = "broad_generic"
    UNNECESSARY = "unnecessary"
    SPAMMY = "spammy"
    FAILED_TO_REDUCE_UNCERTAINTY = "failed_to_reduce_uncertainty"


class NativeUtilizationClass(StrEnum):
    NATIVE_MATCH = "native_match"
    NATIVE_BYPASS = "native_bypass"
    PROVIDER_PUNT = "provider_punt"
    NOT_APPLICABLE = "not_applicable"


class SupportAugmentationClass(StrEnum):
    EXPECTED_ENGAGED = "expected_engaged"
    EXPECTED_MISSING = "expected_missing"
    CORRECTLY_QUIET = "correctly_quiet"
    INTRUSIVE = "intrusive"


@dataclass(frozen=True, slots=True)
class ClarificationExpectation:
    required: bool
    allowed_codes: tuple[str, ...] = ()

    @classmethod
    def none(cls) -> "ClarificationExpectation":
        return cls(required=False)

    @classmethod
    def required(cls, *allowed_codes: str) -> "ClarificationExpectation":
        return cls(required=True, allowed_codes=tuple(code for code in allowed_codes if code))


@dataclass(frozen=True, slots=True)
class CaseInput:
    message: str
    surface_mode: str = "ghost"
    active_module: str = "chartroom"
    workspace_context: dict[str, object] | None = None
    active_posture: dict[str, object] | None = None
    active_request_state: dict[str, object] | None = None
    recent_tool_results: list[dict[str, object]] | None = None
    active_context: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class UtteranceCase:
    case_id: str
    route_family: str
    route_sub_intent: str
    canonical_intent_description: str
    utterance_text: str
    paraphrase_family_id: str
    wording_style: WordingStyle
    coverage_tier: CoverageTier
    input: CaseInput
    ambiguity_class: AmbiguityClass = AmbiguityClass.NONE
    deictic_dependence: bool = False
    likely_runner_ups: tuple[str, ...] = ()
    clarification: ClarificationExpectation = ClarificationExpectation(required=False)
    expected_native_tools: tuple[str, ...] = ()
    expected_capabilities: tuple[str, ...] = ()
    expected_support_systems: tuple[str, ...] = ()
    runtime_profile: str = "default"
    expected_result_posture: str | None = None


@dataclass(frozen=True, slots=True)
class ParaphraseFamily:
    family_id: str
    route_family: str
    canonical_intent_description: str
    case_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RouteFamilySuite:
    route_family: str
    coverage_tier: CoverageTier
    case_ids: tuple[str, ...]
    required_styles: frozenset[WordingStyle]
    covered_styles: frozenset[WordingStyle]


@dataclass(frozen=True, slots=True)
class CrossFamilyConfusionSuite:
    suite_id: str
    target_families: tuple[str, ...]
    case_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FollowUpChain:
    chain_id: str
    route_family: str
    case_ids: tuple[str, ...]
    coverage_tier: CoverageTier
    description: str


@dataclass(frozen=True, slots=True)
class FuzzyCorpus:
    cases_by_id: dict[str, UtteranceCase]
    paraphrase_families: dict[str, ParaphraseFamily]
    route_family_suites: dict[str, RouteFamilySuite]
    follow_up_chains: dict[str, FollowUpChain]
    cross_family_confusion_suites: dict[str, CrossFamilyConfusionSuite]


@dataclass(frozen=True, slots=True)
class EvaluationExpectation:
    expected_route_family: str
    clarification: ClarificationExpectation
    expected_native_tools: tuple[str, ...] = ()
    expected_capabilities: tuple[str, ...] = ()
    expected_support_systems: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FuzzyDecisionObservation:
    route_family: str
    posture: str
    status: str
    response_mode: str
    ambiguity_live: bool = False
    runner_up_family: str | None = None
    clarification_code: str | None = None
    clarification_message: str | None = None
    clarification_candidate_specific: bool = False
    planned_tools: tuple[str, ...] = ()
    capability_requirements: tuple[str, ...] = ()
    support_systems: tuple[str, ...] = ()
    deictic_source: str | None = None


@dataclass(frozen=True, slots=True)
class CaseEvaluationResult:
    case: UtteranceCase
    observation: FuzzyDecisionObservation
    route_hit: RouteHitClass
    clarification_quality: ClarificationQualityClass
    utilization: NativeUtilizationClass
    support_augmentation: SupportAugmentationClass


@dataclass(frozen=True, slots=True)
class ChainEvaluationResult:
    chain: FollowUpChain
    turn_results: tuple[CaseEvaluationResult, ...]
