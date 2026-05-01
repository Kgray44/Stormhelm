from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import ctypes
import platform
import re
import time
from typing import Any

from stormhelm.config.models import ScreenAwarenessConfig
from stormhelm.core.screen_awareness.interfaces import ActionExecutor
from stormhelm.core.screen_awareness.models import (
    ActionExecutionAttempt,
    ActionExecutionRequest,
    ActionExecutionResult,
    ActionExecutionStatus,
    ActionGateDecision,
    ActionIntent,
    ActionPlan,
    ActionPolicyMode,
    ActionRiskLevel,
    ActionTarget,
    ActionVerificationLink,
    CompletionStatus,
    CurrentScreenContext,
    GroundedTarget,
    GroundingEvidenceChannel,
    GroundingOutcome,
    GroundingProvenance,
    GroundingCandidateRole,
    NavigationOutcome,
    PlannerActionResult,
    ScreenConfidence,
    ScreenIntentType,
    ScreenInterpretation,
    ScreenObservation,
    ScreenSensitivityLevel,
    ScreenSourceType,
    VerificationOutcome,
    confidence_level_for_score,
)


_ACTION_STOP_WORDS = {
    "click",
    "press",
    "type",
    "enter",
    "fill",
    "put",
    "write",
    "focus",
    "select",
    "scroll",
    "open",
    "hover",
    "the",
    "a",
    "an",
    "that",
    "this",
    "it",
    "button",
    "field",
    "dropdown",
    "here",
    "into",
    "in",
    "to",
    "my",
    "me",
    "go",
    "ahead",
    "and",
    "do",
    "down",
    "up",
    "bit",
}
_CONFIRMATION_HINTS = {
    "go ahead",
    "do it",
    "go ahead and do it",
    "yes do it",
    "yes click it",
    "proceed",
    "confirm it",
}
_TYPE_HINTS = ("type ", "enter ", "fill ", "put ")
_FOCUS_HINTS = ("focus ", "select ")
_HOVER_HINTS = ("hover ",)
_SENSITIVE_TARGET_TOKENS = {
    "password",
    "passcode",
    "secret",
    "token",
    "security",
    "billing",
    "payment",
    "purchase",
    "delete",
    "remove",
    "bank",
    "credit",
    "account",
}
_HIGH_RISK_TARGET_TOKENS = {"purchase", "delete", "remove", "billing", "payment"}
_KEY_NAME_MAP = {
    "enter": "enter",
    "return": "enter",
    "tab": "tab",
    "escape": "escape",
    "esc": "escape",
    "space": "space",
    "left": "left",
    "right": "right",
    "up": "up",
    "down": "down",
    "page down": "pagedown",
    "page up": "pageup",
    "home": "home",
    "end": "end",
}
_KEYBOARD_INTENTS = {"press", "hit", "tap"}
_SCROLL_DIRECTION_HINTS = {"down": 1, "up": -1}


def _normalize_text(value: str | None) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _tokenize(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", _normalize_text(value))


def _parse_typed_text(operator_text: str) -> str | None:
    quoted = re.search(r'"([^"]+)"', operator_text)
    if quoted:
        return quoted.group(1)
    lowered = _normalize_text(operator_text)
    for prefix in _TYPE_HINTS:
        if lowered.startswith(prefix):
            remainder = operator_text[len(prefix) :].strip()
            for marker in (" into ", " in ", " on "):
                lowered_remainder = remainder.lower()
                if marker in lowered_remainder:
                    return remainder[: lowered_remainder.index(marker)].strip()
            return remainder.strip() or None
    return None


def _parse_key_name(operator_text: str) -> str | None:
    lowered = _normalize_text(operator_text)
    for phrase, key_name in _KEY_NAME_MAP.items():
        if phrase in lowered:
            return key_name
    return None


def _parse_hotkey_sequence(operator_text: str) -> list[str]:
    lowered = _normalize_text(operator_text)
    if not any(trigger in lowered for trigger in ("ctrl", "alt", "shift", "win", "windows")):
        return []
    parts = [token for token in re.split(r"[\+\s]+", lowered) if token]
    hotkey = [token for token in parts if token in {"ctrl", "alt", "shift", "win", "windows"} or len(token) == 1]
    return ["win" if token == "windows" else token for token in hotkey]


def _parse_scroll_amount(operator_text: str) -> int:
    lowered = _normalize_text(operator_text)
    amount = 1
    numeric_match = re.search(r"scroll\s+(?:up|down)\s+(\d+)", lowered)
    if numeric_match:
        amount = max(1, min(int(numeric_match.group(1)), 10))
    elif "more" in lowered or "further" in lowered:
        amount = 3
    return amount


def _scroll_direction(operator_text: str) -> str:
    lowered = _normalize_text(operator_text)
    if "up" in lowered:
        return "up"
    return "down"


def _extract_target_tokens(operator_text: str) -> list[str]:
    return [token for token in _tokenize(operator_text) if token not in _ACTION_STOP_WORDS]


def _looks_like_confirmation(operator_text: str) -> bool:
    lowered = _normalize_text(operator_text)
    return any(hint in lowered for hint in _CONFIRMATION_HINTS)


def _bounds_from_mapping(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    if isinstance(payload.get("bounds"), dict):
        return dict(payload["bounds"])
    bounds: dict[str, Any] = {}
    for key in ("left", "top", "width", "height", "x", "y"):
        value = payload.get(key)
        if isinstance(value, (int, float)):
            bounds[key] = int(value)
    return bounds


def _center_point(bounds: dict[str, Any]) -> tuple[int, int] | None:
    if not bounds:
        return None
    left = bounds.get("left", bounds.get("x"))
    top = bounds.get("top", bounds.get("y"))
    width = bounds.get("width")
    height = bounds.get("height")
    if not all(isinstance(value, (int, float)) for value in (left, top, width, height)):
        return None
    return int(left + width / 2), int(top + height / 2)


def _confidence(score: float, note: str) -> ScreenConfidence:
    bounded = max(0.0, min(score, 1.0))
    return ScreenConfidence(score=bounded, level=confidence_level_for_score(bounded), note=note)


@dataclass(slots=True)
class ActionExecutionEnvelope:
    result: ActionExecutionResult
    observation: ScreenObservation
    interpretation: ScreenInterpretation
    current_context: CurrentScreenContext
    verification: VerificationOutcome | None = None


class WindowsNativeActionExecutor:
    name = "windows_native"

    _MOUSEEVENTF_LEFTDOWN = 0x0002
    _MOUSEEVENTF_LEFTUP = 0x0004
    _MOUSEEVENTF_RIGHTDOWN = 0x0008
    _MOUSEEVENTF_RIGHTUP = 0x0010
    _MOUSEEVENTF_WHEEL = 0x0800
    _KEYEVENTF_KEYUP = 0x0002

    _VK_MAP = {
        "enter": 0x0D,
        "tab": 0x09,
        "escape": 0x1B,
        "space": 0x20,
        "left": 0x25,
        "up": 0x26,
        "right": 0x27,
        "down": 0x28,
        "home": 0x24,
        "end": 0x23,
        "pageup": 0x21,
        "pagedown": 0x22,
        "ctrl": 0x11,
        "alt": 0x12,
        "shift": 0x10,
        "win": 0x5B,
    }

    def execute_plan(self, *, plan: ActionPlan) -> dict[str, Any]:
        if platform.system().strip().lower() != "windows":
            return {"success": False, "reason": "unsupported_platform", "executor_name": self.name}
        try:
            return self._dispatch(plan)
        except Exception as error:
            return {"success": False, "reason": str(error), "executor_name": self.name}

    def _dispatch(self, plan: ActionPlan) -> dict[str, Any]:
        if plan.action_intent in {
            ActionIntent.CLICK,
            ActionIntent.DOUBLE_CLICK,
            ActionIntent.RIGHT_CLICK,
            ActionIntent.FOCUS,
            ActionIntent.SELECT,
            ActionIntent.HOVER,
        }:
            return self._pointer_action(plan)
        if plan.action_intent == ActionIntent.SCROLL:
            return self._scroll_action(plan)
        if plan.action_intent == ActionIntent.TYPE_TEXT:
            return self._type_action(plan)
        if plan.action_intent == ActionIntent.PRESS_KEY:
            return self._press_key_action(plan)
        if plan.action_intent == ActionIntent.HOTKEY:
            return self._press_hotkey_action(plan)
        return {"success": False, "reason": "unsupported_action", "executor_name": self.name}

    def _user32(self) -> Any:
        return ctypes.windll.user32  # type: ignore[attr-defined]

    def _move_pointer(self, x: int, y: int) -> None:
        self._user32().SetCursorPos(int(x), int(y))
        time.sleep(0.03)

    def _mouse_click(self, *, button: str, count: int) -> None:
        down_flag = self._MOUSEEVENTF_RIGHTDOWN if button == "right" else self._MOUSEEVENTF_LEFTDOWN
        up_flag = self._MOUSEEVENTF_RIGHTUP if button == "right" else self._MOUSEEVENTF_LEFTUP
        for _ in range(max(1, count)):
            self._user32().mouse_event(down_flag, 0, 0, 0, 0)
            time.sleep(0.02)
            self._user32().mouse_event(up_flag, 0, 0, 0, 0)
            time.sleep(0.05)

    def _key_down(self, key_name: str) -> None:
        vk = self._VK_MAP.get(key_name)
        if vk is None:
            raise ValueError(f"unsupported_key:{key_name}")
        self._user32().keybd_event(vk, 0, 0, 0)

    def _key_up(self, key_name: str) -> None:
        vk = self._VK_MAP.get(key_name)
        if vk is None:
            raise ValueError(f"unsupported_key:{key_name}")
        self._user32().keybd_event(vk, 0, self._KEYEVENTF_KEYUP, 0)

    def _press_key(self, key_name: str) -> None:
        normalized = str(key_name or "").strip().lower()
        self._key_down(normalized)
        time.sleep(0.02)
        self._key_up(normalized)

    def _press_character_or_key(self, value: str) -> None:
        normalized = str(value or "").strip().lower()
        if normalized in self._VK_MAP:
            self._press_key(normalized)
            return
        vk_scan = self._user32().VkKeyScanW(ord(str(value)[0]))
        vk_code = vk_scan & 0xFF
        shift_state = (vk_scan >> 8) & 0xFF
        if vk_code == 0xFF:
            raise ValueError(f"unsupported_character:{value}")
        if shift_state & 1:
            self._key_down("shift")
        self._user32().keybd_event(vk_code, 0, 0, 0)
        time.sleep(0.01)
        self._user32().keybd_event(vk_code, 0, self._KEYEVENTF_KEYUP, 0)
        if shift_state & 1:
            time.sleep(0.01)
            self._key_up("shift")

    def _press_hotkey(self, sequence: list[str]) -> None:
        normalized = [str(token).strip().lower() for token in sequence if str(token).strip()]
        modifiers = [token for token in normalized if token in {"ctrl", "alt", "shift", "win"}]
        primary = next((token for token in reversed(normalized) if token not in {"ctrl", "alt", "shift", "win"}), None)
        if primary is None:
            raise ValueError("missing_hotkey_primary")
        for modifier in modifiers:
            self._key_down(modifier)
            time.sleep(0.01)
        self._press_character_or_key(primary)
        for modifier in reversed(modifiers):
            time.sleep(0.01)
            self._key_up(modifier)

    def _pointer_action(self, plan: ActionPlan) -> dict[str, Any]:
        point = _center_point(plan.target.bounds if plan.target is not None else {})
        if point is None:
            return {"success": False, "reason": "missing_target_bounds", "executor_name": self.name}
        self._move_pointer(*point)
        if plan.action_intent == ActionIntent.HOVER:
            return {"success": True, "executor_name": self.name, "point": {"x": point[0], "y": point[1]}}
        button = "right" if plan.action_intent == ActionIntent.RIGHT_CLICK else "left"
        count = 2 if plan.action_intent in {ActionIntent.DOUBLE_CLICK, ActionIntent.SELECT} else 1
        self._mouse_click(button=button, count=count)
        return {"success": True, "executor_name": self.name, "point": {"x": point[0], "y": point[1]}, "count": count}

    def _scroll_action(self, plan: ActionPlan) -> dict[str, Any]:
        direction = str(plan.parameters.get("direction") or "down")
        amount = int(plan.parameters.get("amount") or 1)
        delta = 120 * max(1, amount) * (_SCROLL_DIRECTION_HINTS.get(direction, 1))
        self._user32().mouse_event(self._MOUSEEVENTF_WHEEL, 0, 0, int(-delta), 0)
        return {"success": True, "executor_name": self.name, "direction": direction, "amount": amount}

    def _type_action(self, plan: ActionPlan) -> dict[str, Any]:
        point = _center_point(plan.target.bounds if plan.target is not None else {})
        if point is not None:
            self._move_pointer(*point)
            self._mouse_click(button="left", count=1)
        for character in str(plan.parameters.get("text") or ""):
            self._press_character_or_key(character)
            time.sleep(0.01)
        return {"success": True, "executor_name": self.name, "typed": True}

    def _press_key_action(self, plan: ActionPlan) -> dict[str, Any]:
        key_name = str(plan.parameters.get("key_name") or "")
        self._press_key(key_name)
        return {"success": True, "executor_name": self.name, "key_name": key_name}

    def _press_hotkey_action(self, plan: ActionPlan) -> dict[str, Any]:
        sequence = [str(token) for token in plan.parameters.get("hotkey_sequence", []) if str(token).strip()]
        self._press_hotkey(sequence)
        return {"success": True, "executor_name": self.name, "hotkey_sequence": sequence}


@dataclass(slots=True)
class DeterministicActionEngine:
    config: ScreenAwarenessConfig
    observer: Any
    interpreter: Any
    context_synthesizer: Any
    verification_engine: Any
    executor: ActionExecutor | None = None

    def execute(
        self,
        *,
        session_id: str,
        operator_text: str,
        observation: ScreenObservation,
        interpretation: ScreenInterpretation,
        current_context: CurrentScreenContext,
        grounding_result: GroundingOutcome | None,
        navigation_result: NavigationOutcome | None,
        active_context: dict[str, Any] | None,
        surface_mode: str,
        active_module: str,
        workspace_context: dict[str, Any],
    ) -> ActionExecutionEnvelope:
        request = self._build_request(operator_text=operator_text, active_context=active_context)
        prior_plan = self._prior_action_plan(active_context) if request.follow_up_confirmation else None
        plan = self._build_plan(
            request=request,
            observation=observation,
            grounding_result=grounding_result,
            navigation_result=navigation_result,
            prior_plan=prior_plan,
        )
        gate = self._gate(
            request=request,
            plan=plan,
            observation=observation,
            navigation_result=navigation_result,
        )
        if gate.confirmation_required:
            result = self._result(
                request=request,
                plan=plan,
                gate=gate,
                status=ActionExecutionStatus.PLANNED,
                explanation_summary=f"{plan.preview_summary} Confirmation is required before Stormhelm executes it.",
                provenance_channels=self._provenance_channels(grounding_result=grounding_result, navigation_result=navigation_result),
            )
            return ActionExecutionEnvelope(result=result, observation=observation, interpretation=interpretation, current_context=current_context)
        if not gate.allowed:
            status = ActionExecutionStatus.GATED
            if gate.outcome == "ambiguous":
                status = ActionExecutionStatus.AMBIGUOUS
            elif gate.outcome == "blocked":
                status = ActionExecutionStatus.BLOCKED
            result = self._result(
                request=request,
                plan=plan,
                gate=gate,
                status=status,
                explanation_summary=gate.reason,
                provenance_channels=self._provenance_channels(grounding_result=grounding_result, navigation_result=navigation_result),
            )
            return ActionExecutionEnvelope(result=result, observation=observation, interpretation=interpretation, current_context=current_context)
        raw_attempt = self.executor.execute_plan(plan=plan) if self.executor is not None else {
            "success": False,
            "reason": "executor_unavailable",
            "executor_name": "unavailable",
        }
        attempt = ActionExecutionAttempt(
            action_intent=plan.action_intent,
            target_candidate_id=plan.target.candidate_id if plan.target is not None else None,
            success=bool(raw_attempt.get("success", False)),
            executor_name=str(raw_attempt.get("executor_name") or raw_attempt.get("driver") or getattr(self.executor, "name", "unknown")),
            details={str(key): value for key, value in raw_attempt.items() if str(key) != "success"},
            typed_text_redacted=plan.text_payload_redacted,
        )
        if not attempt.success:
            result = self._result(
                request=request,
                plan=plan,
                gate=gate,
                attempt=attempt,
                status=ActionExecutionStatus.FAILED,
                explanation_summary="Stormhelm attempted the UI action, but the native execution layer reported a failure.",
                provenance_channels=self._provenance_channels(grounding_result=grounding_result, navigation_result=navigation_result),
            )
            return ActionExecutionEnvelope(result=result, observation=observation, interpretation=interpretation, current_context=current_context)

        post_observation = self.observer.observe(
            session_id=session_id,
            surface_mode=surface_mode,
            active_module=active_module,
            active_context=active_context or {},
            workspace_context=workspace_context,
        )
        post_interpretation = self.interpreter.interpret(post_observation, operator_text=operator_text)
        post_context = self.context_synthesizer.synthesize(post_observation, post_interpretation)
        post_verification = self._post_action_verification(
            session_id=session_id,
            pre_observation=observation,
            pre_interpretation=interpretation,
            pre_context=current_context,
            post_observation=post_observation,
            post_interpretation=post_interpretation,
            post_context=post_context,
            grounding_result=grounding_result,
            navigation_result=navigation_result,
            active_context=active_context,
            surface_mode=surface_mode,
            active_module=active_module,
        )
        status = (
            ActionExecutionStatus.VERIFIED_SUCCESS
            if post_verification is not None and post_verification.completion_status == CompletionStatus.COMPLETED
            else ActionExecutionStatus.ATTEMPTED_UNVERIFIED
        )
        explanation_summary = (
            "Stormhelm executed the planned UI action and the follow-up verification bearing supports success."
            if status == ActionExecutionStatus.VERIFIED_SUCCESS
            else "Stormhelm executed the planned UI action, but the follow-up bearing does not justify a verified success claim yet."
        )
        result = self._result(
            request=request,
            plan=plan,
            gate=gate,
            attempt=attempt,
            post_action_verification=post_verification,
            status=status,
            explanation_summary=explanation_summary,
            provenance_channels=self._provenance_channels(grounding_result=grounding_result, navigation_result=navigation_result),
        )
        return ActionExecutionEnvelope(
            result=result,
            observation=post_observation,
            interpretation=post_interpretation,
            current_context=post_context,
            verification=post_verification,
        )

    def _build_request(self, *, operator_text: str, active_context: dict[str, Any] | None) -> ActionExecutionRequest:
        lowered = _normalize_text(operator_text)
        follow_up_confirmation = _looks_like_confirmation(lowered) and self._prior_action_plan(active_context) is not None
        if follow_up_confirmation:
            prior_plan = self._prior_action_plan(active_context) or {}
            intent_value = str(prior_plan.get("action_intent") or ActionIntent.CLICK.value)
            try:
                action_intent = ActionIntent(intent_value)
            except ValueError:
                action_intent = ActionIntent.CLICK
            return ActionExecutionRequest(
                utterance=operator_text,
                intent=action_intent,
                target_tokens=[],
                follow_up_confirmation=True,
                mode_flags=["follow_up_confirmation"],
            )
        hotkey_sequence = _parse_hotkey_sequence(operator_text)
        if hotkey_sequence:
            return ActionExecutionRequest(utterance=operator_text, intent=ActionIntent.HOTKEY, hotkey_sequence=hotkey_sequence)
        key_name = _parse_key_name(operator_text)
        lowered_tokens = _tokenize(lowered)
        if key_name is not None and lowered_tokens[:1] and lowered_tokens[0] in _KEYBOARD_INTENTS:
            return ActionExecutionRequest(utterance=operator_text, intent=ActionIntent.PRESS_KEY, key_name=key_name)
        typed_text = _parse_typed_text(operator_text)
        if typed_text is not None:
            return ActionExecutionRequest(
                utterance=operator_text,
                intent=ActionIntent.TYPE_TEXT,
                target_tokens=_extract_target_tokens(operator_text),
                typed_text=typed_text,
            )
        if lowered.startswith("scroll "):
            return ActionExecutionRequest(
                utterance=operator_text,
                intent=ActionIntent.SCROLL,
                scroll_direction=_scroll_direction(operator_text),
                scroll_amount=_parse_scroll_amount(operator_text),
            )
        if lowered.startswith(_FOCUS_HINTS):
            return ActionExecutionRequest(
                utterance=operator_text,
                intent=ActionIntent.FOCUS if lowered.startswith("focus ") else ActionIntent.SELECT,
                target_tokens=_extract_target_tokens(operator_text),
            )
        if lowered.startswith(_HOVER_HINTS):
            return ActionExecutionRequest(
                utterance=operator_text,
                intent=ActionIntent.HOVER,
                target_tokens=_extract_target_tokens(operator_text),
            )
        return ActionExecutionRequest(
            utterance=operator_text,
            intent=ActionIntent.CLICK,
            target_tokens=_extract_target_tokens(operator_text),
        )

    def _build_plan(
        self,
        *,
        request: ActionExecutionRequest,
        observation: ScreenObservation,
        grounding_result: GroundingOutcome | None,
        navigation_result: NavigationOutcome | None,
        prior_plan: dict[str, Any] | None,
    ) -> ActionPlan:
        if prior_plan is not None:
            target = self._target_from_prior_plan(prior_plan)
            parameters = dict(prior_plan.get("parameters") or {})
            return ActionPlan(
                request=request,
                action_intent=request.intent,
                target=target,
                parameters=parameters,
                preview_summary=str(prior_plan.get("preview_summary") or "Stormhelm has a pending action plan ready."),
                verification_link=ActionVerificationLink(
                    verification_ready=True,
                    expectation_summary=str(((prior_plan.get("verification_link") or {}).get("expectation_summary") or "").strip()),
                    comparison_basis="prior_screen_bearing",
                    prior_bearing_injected=True,
                ),
                grounding_reused=bool(prior_plan.get("grounding_reused", target.candidate_id if target is not None else False)),
                navigation_reused=bool(prior_plan.get("navigation_reused", False)),
                verification_reused=True,
                text_payload_redacted=bool(prior_plan.get("text_payload_redacted", False)),
            )

        target: ActionTarget | None = None
        grounding_reused = False
        navigation_reused = False
        if grounding_result is not None and grounding_result.winning_target is not None:
            target = self._target_from_grounded(grounding_result.winning_target)
            grounding_reused = True
        elif request.intent in {ActionIntent.TYPE_TEXT, ActionIntent.FOCUS, ActionIntent.SELECT}:
            target = self._focused_field_target(observation)
        if target is None and navigation_result is not None and navigation_result.winning_candidate is not None:
            target = ActionTarget(
                candidate_id=navigation_result.winning_candidate.candidate_id,
                label=navigation_result.winning_candidate.label,
                role=navigation_result.winning_candidate.role,
                source_channel=navigation_result.winning_candidate.source_channel,
                source_type=navigation_result.winning_candidate.source_type,
                enabled=navigation_result.winning_candidate.enabled,
                bounds=dict(navigation_result.winning_candidate.bounds),
                semantic_metadata=dict(navigation_result.winning_candidate.semantic_metadata),
            )
            navigation_reused = True

        parameters: dict[str, Any] = {}
        text_payload_redacted = False
        if request.intent == ActionIntent.TYPE_TEXT:
            parameters["text"] = request.typed_text or ""
        elif request.intent == ActionIntent.PRESS_KEY:
            parameters["key_name"] = request.key_name
        elif request.intent == ActionIntent.HOTKEY:
            parameters["hotkey_sequence"] = list(request.hotkey_sequence)
        elif request.intent == ActionIntent.SCROLL:
            parameters["direction"] = request.scroll_direction or "down"
            parameters["amount"] = request.scroll_amount or 1
        if request.intent == ActionIntent.TYPE_TEXT and self._is_sensitive_target(target=target, observation=observation):
            text_payload_redacted = True

        preview_target = "the current focus" if target is None else f'the {target.role.value} "{target.label}"'
        preview_summary = f"Stormhelm can {request.intent.value.replace('_', ' ')} on {preview_target}."
        return ActionPlan(
            request=request,
            action_intent=request.intent,
            target=target,
            parameters=parameters,
            preview_summary=preview_summary,
            verification_link=ActionVerificationLink(
                verification_ready=bool(self.config.verification_enabled),
                expectation_summary="Check the next visible state after the action attempt.",
                comparison_basis="prior_screen_bearing",
                prior_bearing_injected=bool(self.config.verification_enabled),
            ),
            grounding_reused=grounding_reused,
            navigation_reused=navigation_reused,
            verification_reused=True,
            text_payload_redacted=text_payload_redacted,
        )

    def _gate(
        self,
        *,
        request: ActionExecutionRequest,
        plan: ActionPlan,
        observation: ScreenObservation,
        navigation_result: NavigationOutcome | None,
    ) -> ActionGateDecision:
        policy_mode = self._policy_mode()
        risk_level = self._risk_level(request=request, plan=plan, observation=observation)
        target_required = request.intent not in {ActionIntent.SCROLL, ActionIntent.PRESS_KEY, ActionIntent.HOTKEY}
        if policy_mode in {ActionPolicyMode.OBSERVE_ONLY, ActionPolicyMode.GUIDE}:
            return ActionGateDecision(
                allowed=False,
                outcome="gated",
                reason="Direct UI execution is disabled by the current action policy.",
                policy_mode=policy_mode,
                risk_level=risk_level,
                verification_ready=plan.verification_link.verification_ready,
            )
        if risk_level == ActionRiskLevel.RESTRICTED:
            return ActionGateDecision(
                allowed=False,
                outcome="gated",
                reason="The requested action touches a sensitive or restricted surface, so Stormhelm will not execute it automatically.",
                policy_mode=policy_mode,
                risk_level=risk_level,
                verification_ready=plan.verification_link.verification_ready,
            )
        if target_required and plan.target is None:
            return ActionGateDecision(
                allowed=False,
                outcome="ambiguous",
                reason="I can't justify a single grounded target for this action from the current evidence.",
                policy_mode=policy_mode,
                risk_level=risk_level,
                ambiguity_present=True,
                verification_ready=plan.verification_link.verification_ready,
            )
        if plan.target is not None and plan.target.enabled is False:
            return ActionGateDecision(
                allowed=False,
                outcome="blocked",
                reason=f'The target "{plan.target.label}" is visible but currently disabled.',
                policy_mode=policy_mode,
                risk_level=risk_level,
                blocker_present=True,
                verification_ready=plan.verification_link.verification_ready,
            )
        if navigation_result is not None and navigation_result.blocker is not None and target_required and plan.target is None:
            return ActionGateDecision(
                allowed=False,
                outcome="blocked",
                reason=navigation_result.blocker.summary,
                policy_mode=policy_mode,
                risk_level=risk_level,
                blocker_present=True,
                verification_ready=plan.verification_link.verification_ready,
            )
        if policy_mode == ActionPolicyMode.CONFIRM_BEFORE_ACT and not request.follow_up_confirmation:
            return ActionGateDecision(
                allowed=False,
                outcome="planned",
                reason="Stormhelm is waiting for explicit confirmation before it executes this UI action.",
                policy_mode=policy_mode,
                risk_level=risk_level,
                confirmation_required=True,
                verification_ready=plan.verification_link.verification_ready,
            )
        return ActionGateDecision(
            allowed=True,
            outcome="allowed",
            reason="The current grounding, policy, and blocker checks support a bounded action attempt.",
            policy_mode=policy_mode,
            risk_level=risk_level,
            verification_ready=plan.verification_link.verification_ready,
        )

    def _policy_mode(self) -> ActionPolicyMode:
        candidate = str(self.config.action_policy_mode or ActionPolicyMode.CONFIRM_BEFORE_ACT.value).strip().lower()
        try:
            return ActionPolicyMode(candidate)
        except ValueError:
            return ActionPolicyMode.CONFIRM_BEFORE_ACT

    def _risk_level(
        self,
        *,
        request: ActionExecutionRequest,
        plan: ActionPlan,
        observation: ScreenObservation,
    ) -> ActionRiskLevel:
        if self._is_sensitive_target(target=plan.target, observation=observation):
            return ActionRiskLevel.RESTRICTED
        label = _normalize_text(plan.target.label if plan.target is not None else "")
        if any(token in label for token in _HIGH_RISK_TARGET_TOKENS):
            return ActionRiskLevel.HIGH
        if request.intent in {ActionIntent.TYPE_TEXT, ActionIntent.HOTKEY}:
            return ActionRiskLevel.MODERATE
        return ActionRiskLevel.LOW

    def _is_sensitive_target(self, *, target: ActionTarget | None, observation: ScreenObservation) -> bool:
        if observation.sensitivity in {ScreenSensitivityLevel.SENSITIVE, ScreenSensitivityLevel.RESTRICTED}:
            return True
        label = _normalize_text(target.label if target is not None else "")
        return any(token in label for token in _SENSITIVE_TARGET_TOKENS)

    def _post_action_verification(
        self,
        *,
        session_id: str,
        pre_observation: ScreenObservation,
        pre_interpretation: ScreenInterpretation,
        pre_context: CurrentScreenContext,
        post_observation: ScreenObservation,
        post_interpretation: ScreenInterpretation,
        post_context: CurrentScreenContext,
        grounding_result: GroundingOutcome | None,
        navigation_result: NavigationOutcome | None,
        active_context: dict[str, Any] | None,
        surface_mode: str,
        active_module: str,
    ) -> VerificationOutcome | None:
        if not self.config.verification_enabled or self.verification_engine is None:
            return None
        synthetic_prior = {
            "kind": "screen_awareness",
            "intent": ScreenIntentType.EXECUTE_UI_ACTION.value,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "analysis_result": {
                "observation": pre_observation.to_dict(),
                "interpretation": pre_interpretation.to_dict(),
                "current_screen_context": pre_context.to_dict(),
                "grounding_result": grounding_result.to_dict() if grounding_result is not None else None,
                "navigation_result": navigation_result.to_dict() if navigation_result is not None else None,
            },
        }
        augmented_context = dict(active_context or {})
        recent_resolutions = []
        current_recent = augmented_context.get("recent_context_resolutions")
        if isinstance(current_recent, list):
            recent_resolutions = [dict(item) for item in current_recent if isinstance(item, dict)]
        augmented_context["recent_context_resolutions"] = [synthetic_prior, *recent_resolutions[:3]]
        return self.verification_engine.verify(
            session_id=session_id,
            operator_text="did that work?",
            intent=ScreenIntentType.VERIFY_SCREEN_STATE,
            surface_mode=surface_mode,
            active_module=active_module,
            observation=post_observation,
            interpretation=post_interpretation,
            current_context=post_context,
            grounding_result=grounding_result,
            navigation_result=navigation_result,
            active_context=augmented_context,
        )

    def _focused_field_target(self, observation: ScreenObservation) -> ActionTarget | None:
        active_item = observation.workspace_snapshot.get("active_item")
        if not isinstance(active_item, dict):
            return None
        kind = _normalize_text(str(active_item.get("kind") or active_item.get("viewer") or ""))
        if "field" not in kind and "input" not in kind and "text" not in kind:
            return None
        return ActionTarget(
            candidate_id=str(active_item.get("itemId") or active_item.get("id") or "").strip() or None,
            label=str(active_item.get("title") or active_item.get("name") or "Focused field").strip() or "Focused field",
            role=GroundingCandidateRole.FIELD,
            source_channel=GroundingEvidenceChannel.WORKSPACE_CONTEXT,
            source_type=ScreenSourceType.WORKSPACE_CONTEXT,
            enabled=active_item.get("enabled") if isinstance(active_item.get("enabled"), bool) else True,
            bounds=_bounds_from_mapping(active_item),
            semantic_metadata=dict(active_item),
            equivalent_execution_basis="focused_field",
        )

    def _target_from_grounded(self, grounded_target: GroundedTarget) -> ActionTarget:
        return ActionTarget(
            candidate_id=grounded_target.candidate_id,
            label=grounded_target.label,
            role=grounded_target.role,
            source_channel=grounded_target.source_channel,
            source_type=grounded_target.source_type,
            enabled=grounded_target.enabled,
            bounds=dict(grounded_target.bounds),
            semantic_metadata=dict(grounded_target.semantic_metadata),
        )

    def _prior_action_plan(self, active_context: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(active_context, dict):
            return None
        recent_resolutions = active_context.get("recent_context_resolutions")
        if not isinstance(recent_resolutions, list):
            return None
        for entry in recent_resolutions:
            if not isinstance(entry, dict) or str(entry.get("kind") or "").strip() != "screen_awareness":
                continue
            analysis = entry.get("analysis_result")
            if not isinstance(analysis, dict):
                continue
            action_result = analysis.get("action_result")
            if not isinstance(action_result, dict):
                continue
            gate = action_result.get("gate")
            if not isinstance(gate, dict) or not gate.get("confirmation_required"):
                continue
            plan = action_result.get("plan")
            if isinstance(plan, dict):
                return dict(plan)
        return None

    def _target_from_prior_plan(self, prior_plan: dict[str, Any]) -> ActionTarget | None:
        raw_target = prior_plan.get("target")
        if not isinstance(raw_target, dict):
            return None
        role_value = str(raw_target.get("role") or GroundingCandidateRole.UNKNOWN.value)
        try:
            role = GroundingCandidateRole(role_value)
        except ValueError:
            role = GroundingCandidateRole.UNKNOWN
        source_channel_value = raw_target.get("source_channel")
        source_type_value = raw_target.get("source_type")
        return ActionTarget(
            candidate_id=str(raw_target.get("candidate_id") or "").strip() or None,
            label=str(raw_target.get("label") or "").strip() or None,
            role=role,
            source_channel=GroundingEvidenceChannel(str(source_channel_value))
            if isinstance(source_channel_value, str) and source_channel_value
            else None,
            source_type=ScreenSourceType(str(source_type_value))
            if isinstance(source_type_value, str) and source_type_value
            else None,
            enabled=raw_target.get("enabled") if isinstance(raw_target.get("enabled"), bool) else None,
            bounds=dict(raw_target.get("bounds") or {}),
            semantic_metadata=dict(raw_target.get("semantic_metadata") or {}),
            equivalent_execution_basis=str(raw_target.get("equivalent_execution_basis") or "").strip() or None,
        )

    def _provenance_channels(
        self,
        *,
        grounding_result: GroundingOutcome | None,
        navigation_result: NavigationOutcome | None,
    ) -> list[GroundingEvidenceChannel]:
        channels: list[GroundingEvidenceChannel] = []
        if grounding_result is not None:
            channels.extend(channel for channel in grounding_result.provenance.channels_used if channel not in channels)
        if navigation_result is not None:
            channels.extend(channel for channel in navigation_result.provenance.channels_used if channel not in channels)
        return channels

    def result_from_browser_semantic_execution(self, browser_result: Any) -> ActionExecutionResult:
        """Represent provider-specific browser execution in the canonical action-result language."""
        action_kind = _normalize_text(str(getattr(browser_result, "action_kind", "") or "click"))
        try:
            intent = ActionIntent(action_kind)
        except ValueError:
            intent = ActionIntent.CLICK
        target_summary = dict(getattr(browser_result, "target_summary", {}) or {})
        label = str(target_summary.get("name") or target_summary.get("label") or target_summary.get("candidate_id") or "browser target").strip()
        role = self._browser_target_role(target_summary.get("role"))
        status = self._browser_execution_status(getattr(browser_result, "status", "blocked"))
        request = ActionExecutionRequest(
            utterance=f"playwright {intent.value.replace('_', ' ')} {label}".strip(),
            intent=intent,
            target_tokens=_tokenize(label),
            mode_flags=["playwright_browser_semantic_execution"],
        )
        target = ActionTarget(
            candidate_id=str(target_summary.get("candidate_id") or "").strip() or None,
            label=label,
            role=role,
            source_channel=GroundingEvidenceChannel.ADAPTER_SEMANTICS,
            source_type=ScreenSourceType.APP_ADAPTER,
            enabled=target_summary.get("enabled") if isinstance(target_summary.get("enabled"), bool) else None,
            semantic_metadata={
                "provider": str(getattr(browser_result, "provider", "") or "playwright"),
                "claim_ceiling": str(getattr(browser_result, "claim_ceiling", "") or "browser_semantic_action_execution"),
                "browser_result_id": str(getattr(browser_result, "result_id", "") or ""),
                "browser_status": str(getattr(browser_result, "status", "") or ""),
                "verification_status": str(getattr(browser_result, "verification_status", "") or ""),
            },
        )
        plan = ActionPlan(
            request=request,
            action_intent=intent,
            target=target,
            parameters={
                "provider": str(getattr(browser_result, "provider", "") or "playwright"),
                "browser_result_id": str(getattr(browser_result, "result_id", "") or ""),
                "browser_status": str(getattr(browser_result, "status", "") or ""),
                "claim_ceiling": str(getattr(browser_result, "claim_ceiling", "") or "browser_semantic_action_execution"),
            },
            preview_summary=f'Playwright browser {intent.value.replace("_", " ")} target: "{label}".',
            verification_link=ActionVerificationLink(
                verification_ready=bool(getattr(browser_result, "verification_attempted", False)),
                expectation_summary="Compare bounded Playwright browser semantic observations before and after execution.",
                comparison_basis="playwright_browser_semantic_observation",
                prior_bearing_injected=bool(getattr(browser_result, "before_observation_id", "") and getattr(browser_result, "after_observation_id", "")),
            ),
            grounding_reused=True,
            navigation_reused=False,
            verification_reused=True,
        )
        raw_status = str(getattr(browser_result, "status", "") or "").strip()
        raw_status_key = raw_status.lower()
        raw_error_code = str(getattr(browser_result, "error_code", "") or "").strip()
        blocker_present = (
            raw_status_key
            in {
                "blocked",
                "unsupported",
                "approval_required",
                "approval_invalid",
                "approval_denied",
                "denied",
            }
            or raw_status_key.startswith("blocked_")
        )
        gate = ActionGateDecision(
            allowed=bool(getattr(browser_result, "action_attempted", False)),
            outcome=self._browser_gate_outcome(raw_status),
            reason=str(
                getattr(browser_result, "user_message", "")
                or getattr(browser_result, "bounded_error_message", "")
                or raw_error_code
                or raw_status
                or "Playwright browser execution returned a bounded result."
            ),
            policy_mode=self._policy_mode(),
            risk_level=self._browser_risk_level(getattr(browser_result, "risk_level", "")),
            confirmation_required=raw_status_key == "approval_required",
            ambiguity_present=raw_status_key == "ambiguous",
            blocker_present=blocker_present,
            verification_ready=bool(getattr(browser_result, "verification_attempted", False)),
        )
        attempt = None
        if getattr(browser_result, "action_attempted", False):
            attempt = ActionExecutionAttempt(
                action_intent=intent,
                target_candidate_id=target.candidate_id,
                success=bool(getattr(browser_result, "action_completed", False)),
                executor_name="playwright_browser_adapter",
                details={
                    "provider": str(getattr(browser_result, "provider", "") or "playwright"),
                    "browser_status": raw_status,
                    "verification_status": str(getattr(browser_result, "verification_status", "") or ""),
                    "before_observation_id": str(getattr(browser_result, "before_observation_id", "") or ""),
                    "after_observation_id": str(getattr(browser_result, "after_observation_id", "") or ""),
                    "comparison_result_id": str(getattr(browser_result, "comparison_result_id", "") or ""),
                    "cleanup_status": str(getattr(browser_result, "cleanup_status", "") or ""),
                },
            )
        return self._result(
            request=request,
            plan=plan,
            gate=gate,
            attempt=attempt,
            status=status,
            explanation_summary=str(getattr(browser_result, "user_message", "") or "Playwright browser execution was mapped into the canonical Screen Awareness action result."),
            provenance_channels=[GroundingEvidenceChannel.ADAPTER_SEMANTICS],
        )

    def _browser_execution_status(self, value: Any) -> ActionExecutionStatus:
        raw = str(value or "").strip().lower()
        if raw == "verified_supported":
            return ActionExecutionStatus.VERIFIED_SUCCESS
        if raw in {"completed_unverified", "attempted", "verified_unsupported", "partial"}:
            return ActionExecutionStatus.ATTEMPTED_UNVERIFIED
        if raw == "ambiguous":
            return ActionExecutionStatus.AMBIGUOUS
        if raw == "failed":
            return ActionExecutionStatus.FAILED
        if raw in {"approval_required", "approved"}:
            return ActionExecutionStatus.PLANNED
        if raw in {"blocked", "unsupported", "approval_invalid", "approval_denied", "denied"} or raw.startswith("blocked_"):
            return ActionExecutionStatus.BLOCKED
        return ActionExecutionStatus.GATED

    def _browser_gate_outcome(self, value: str) -> str:
        raw = str(value or "").strip().lower()
        if raw == "ambiguous":
            return "ambiguous"
        if raw in {"blocked", "unsupported", "approval_invalid", "approval_denied", "denied"} or raw.startswith("blocked_"):
            return "blocked"
        if raw == "approval_required":
            return "planned"
        if raw in {"verified_supported", "completed_unverified", "verified_unsupported", "partial", "failed"}:
            return "allowed"
        return raw or "gated"

    def _browser_target_role(self, value: Any) -> GroundingCandidateRole:
        raw = _normalize_text(str(value or ""))
        if raw == "button":
            return GroundingCandidateRole.BUTTON
        if raw in {"textbox", "field", "input", "combobox", "select", "radio"}:
            return GroundingCandidateRole.FIELD
        if raw == "checkbox":
            return GroundingCandidateRole.CHECKBOX
        if raw in {"alert", "warning"}:
            return GroundingCandidateRole.WARNING
        if raw in {"dialog", "popup"}:
            return GroundingCandidateRole.POPUP
        if raw == "link":
            return GroundingCandidateRole.ITEM
        return GroundingCandidateRole.UNKNOWN

    def _browser_risk_level(self, value: Any) -> ActionRiskLevel:
        raw = str(value or "").strip().lower()
        if raw == ActionRiskLevel.RESTRICTED.value:
            return ActionRiskLevel.RESTRICTED
        if raw == ActionRiskLevel.HIGH.value:
            return ActionRiskLevel.HIGH
        if raw in {ActionRiskLevel.MODERATE.value, "medium"}:
            return ActionRiskLevel.MODERATE
        return ActionRiskLevel.LOW

    def _result(
        self,
        *,
        request: ActionExecutionRequest,
        plan: ActionPlan,
        gate: ActionGateDecision,
        status: ActionExecutionStatus,
        explanation_summary: str,
        provenance_channels: list[GroundingEvidenceChannel],
        attempt: ActionExecutionAttempt | None = None,
        post_action_verification: VerificationOutcome | None = None,
    ) -> ActionExecutionResult:
        if plan.text_payload_redacted:
            request = ActionExecutionRequest(
                utterance=request.utterance,
                intent=request.intent,
                target_tokens=list(request.target_tokens),
                typed_text=None,
                key_name=request.key_name,
                hotkey_sequence=list(request.hotkey_sequence),
                scroll_direction=request.scroll_direction,
                scroll_amount=request.scroll_amount,
                follow_up_confirmation=request.follow_up_confirmation,
                mode_flags=list(request.mode_flags),
            )
            plan = ActionPlan(
                request=request,
                action_intent=plan.action_intent,
                target=plan.target,
                parameters={**plan.parameters, "text": "[redacted]"} if "text" in plan.parameters else dict(plan.parameters),
                preview_summary=plan.preview_summary,
                verification_link=plan.verification_link,
                grounding_reused=plan.grounding_reused,
                navigation_reused=plan.navigation_reused,
                verification_reused=plan.verification_reused,
                text_payload_redacted=True,
            )
        confidence_score = 0.82 if status == ActionExecutionStatus.VERIFIED_SUCCESS else 0.68 if status == ActionExecutionStatus.PLANNED else 0.55 if gate.allowed else 0.22
        confidence = _confidence(confidence_score, explanation_summary)
        planner_result = PlannerActionResult(
            resolved=status in {ActionExecutionStatus.VERIFIED_SUCCESS, ActionExecutionStatus.ATTEMPTED_UNVERIFIED, ActionExecutionStatus.PLANNED},
            execution_status=status,
            target_candidate_id=plan.target.candidate_id if plan.target is not None else None,
            confidence=confidence,
            risk_level=gate.risk_level,
            explanation_summary=explanation_summary,
            provenance_channels=list(provenance_channels),
            confirmation_required=gate.confirmation_required,
            grounding_reused=plan.grounding_reused,
            navigation_reused=plan.navigation_reused,
            verification_ready=gate.verification_ready,
        )
        provenance = GroundingProvenance(
            channels_used=list(provenance_channels),
            dominant_channel=provenance_channels[0] if provenance_channels else None,
            signal_names=[token for token in (plan.target.label if plan.target is not None else "", explanation_summary) if token],
        )
        return ActionExecutionResult(
            request=request,
            plan=plan,
            gate=gate,
            attempt=attempt,
            post_action_verification=post_action_verification,
            status=status,
            explanation_summary=explanation_summary,
            planner_result=planner_result,
            provenance=provenance,
            confidence=confidence,
        )
