from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from stormhelm.core.screen_awareness.models import ScreenIntentType
from stormhelm.core.screen_awareness.models import ScreenResponse


def _lookup_path(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in (segment for segment in str(path or "").split(".") if segment):
        if isinstance(current, dict):
            current = current.get(part)
            continue
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
            continue
        return None
    return current


@dataclass(slots=True)
class ScreenScenarioExpectation:
    name: str
    evidence_path: str
    equals: Any | None = None
    contains: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "evidence_path": self.evidence_path,
            "equals": self.equals,
            "contains": self.contains,
        }


@dataclass(slots=True)
class ScreenScenarioDefinition:
    scenario_id: str
    title: str
    intent: ScreenIntentType
    expectations: list[ScreenScenarioExpectation] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "title": self.title,
            "intent": self.intent.value,
            "expectations": [item.to_dict() for item in self.expectations],
        }


@dataclass(slots=True)
class ScreenScenarioCheckResult:
    name: str
    passed: bool
    evidence_path: str
    expected: Any
    actual: Any
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "evidence_path": self.evidence_path,
            "expected": self.expected,
            "actual": self.actual,
            "detail": self.detail,
        }


@dataclass(slots=True)
class ScreenScenarioEvaluationResult:
    scenario_id: str
    title: str
    passed: bool
    trace_id: str | None = None
    checks: list[ScreenScenarioCheckResult] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "title": self.title,
            "passed": self.passed,
            "trace_id": self.trace_id,
            "checks": [item.to_dict() for item in self.checks],
            "summary": self.summary,
        }


class ScreenScenarioEvaluator:
    def evaluate(
        self,
        *,
        definition: ScreenScenarioDefinition,
        response: ScreenResponse,
    ) -> ScreenScenarioEvaluationResult:
        payload = {
            "analysis": response.analysis.to_dict(),
            "telemetry": dict(response.telemetry),
            "response_contract": dict(response.response_contract),
            "assistant_response": response.assistant_response,
        }
        checks: list[ScreenScenarioCheckResult] = []
        for expectation in definition.expectations:
            actual = _lookup_path(payload, expectation.evidence_path)
            if expectation.contains is not None:
                actual_text = "" if actual is None else str(actual)
                passed = expectation.contains in actual_text
                detail = (
                    f"Expected {expectation.evidence_path} to contain {expectation.contains!r}; "
                    f"got {actual_text!r}."
                )
                expected: Any = {"contains": expectation.contains}
            else:
                passed = actual == expectation.equals
                detail = (
                    f"Expected {expectation.evidence_path} to equal {expectation.equals!r}; "
                    f"got {actual!r}."
                )
                expected = expectation.equals
            checks.append(
                ScreenScenarioCheckResult(
                    name=expectation.name,
                    passed=passed,
                    evidence_path=expectation.evidence_path,
                    expected=expected,
                    actual=actual,
                    detail=detail,
                )
            )

        passed = all(check.passed for check in checks)
        summary = (
            f"Scenario {definition.scenario_id} passed with {len(checks)} checks."
            if passed
            else f"Scenario {definition.scenario_id} failed {sum(1 for check in checks if not check.passed)} of {len(checks)} checks."
        )
        return ScreenScenarioEvaluationResult(
            scenario_id=definition.scenario_id,
            title=definition.title,
            passed=passed,
            trace_id=response.analysis.trace_id,
            checks=checks,
            summary=summary,
        )
