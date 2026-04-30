from __future__ import annotations

import re

from stormhelm.core.camera_awareness.helpers import build_default_camera_helper_registry
from stormhelm.core.camera_awareness.models import (
    CameraComparisonClassification,
    CameraComparisonMode,
    CameraConfidenceLevel,
    CameraHelperCategory,
)


def classify_camera_comparison_request(user_question: str) -> CameraComparisonClassification:
    text = _normalize(user_question)
    if not text or _educational_or_nonvisual(text):
        return CameraComparisonClassification()
    mode = _comparison_mode(text)
    if mode is None:
        return CameraComparisonClassification()
    helper = build_default_camera_helper_registry().classify(
        user_question=user_question,
        vision_answer=None,
    )
    helper_category: str | None = None
    helper_family: str | None = None
    if helper.applicable:
        helper_category = helper.category.value
        helper_family = helper.helper_family.value
    return CameraComparisonClassification(
        applicable=True,
        comparison_mode=mode,
        helper_category=helper_category,
        helper_family=helper_family,
        slot_ids=_slot_ids_for_mode(mode),
        confidence=CameraConfidenceLevel.MEDIUM,
        reasons=["visual_comparison_request"],
    )


def default_slot_ids_for_mode(mode: CameraComparisonMode | str) -> list[str]:
    return _slot_ids_for_mode(CameraComparisonMode(mode))


def infer_comparison_mode(user_question: str) -> CameraComparisonMode:
    classification = classify_camera_comparison_request(user_question)
    return classification.comparison_mode if classification.applicable else CameraComparisonMode.GENERAL_COMPARE


def _comparison_mode(text: str) -> CameraComparisonMode | None:
    if re.search(r"\bfront\b.{0,40}\bback\b|\bback\b.{0,40}\bfront\b", text):
        return CameraComparisonMode.FRONT_BACK
    if re.search(r"\bbefore\b.{0,48}\bafter\b|\bafter\b.{0,48}\bbefore\b", text):
        return CameraComparisonMode.BEFORE_AFTER
    if re.search(r"\bold\b.{0,40}\bnew\b|\bnew\b.{0,40}\bold\b|replacement part", text):
        return CameraComparisonMode.OLD_NEW
    if re.search(r"\bclose[ -]?up\b.{0,48}\b(?:context|full view|whole|wide)\b|\b(?:context|full view|whole|wide)\b.{0,48}\bclose[ -]?up\b", text):
        return CameraComparisonMode.CLOSEUP_CONTEXT
    if re.search(r"\b(?:option a|option b|a/b|which image|which photo|clearer|clearest|less blurry|better photo)\b", text):
        return CameraComparisonMode.QUALITY_COMPARE
    if re.search(r"\b(?:two images|two photos|two pictures|these images|these photos|these pictures|side by side)\b", text):
        return CameraComparisonMode.SIDE_BY_SIDE
    if re.search(r"\bcompare\b", text) and _visual_comparison_target(text):
        return CameraComparisonMode.GENERAL_COMPARE
    if re.search(r"\bi(?:'|’)??ll show you\b", text) and _visual_comparison_target(text):
        return CameraComparisonMode.GENERAL_COMPARE
    return None


def _slot_ids_for_mode(mode: CameraComparisonMode) -> list[str]:
    return {
        CameraComparisonMode.BEFORE_AFTER: ["before", "after"],
        CameraComparisonMode.FRONT_BACK: ["front", "back"],
        CameraComparisonMode.CLOSEUP_CONTEXT: ["context", "close_up"],
        CameraComparisonMode.OPTION_A_B: ["option_a", "option_b"],
        CameraComparisonMode.OLD_NEW: ["old", "new"],
        CameraComparisonMode.QUALITY_COMPARE: ["option_a", "option_b"],
        CameraComparisonMode.SIDE_BY_SIDE: ["option_a", "option_b"],
    }.get(mode, ["option_a", "option_b"])


def _visual_comparison_target(text: str) -> bool:
    return bool(
        re.search(
            r"\b(?:image|images|photo|photos|picture|pictures|camera|capture|captures|"
            r"pcb|board|connector|connectors|solder|joint|part|parts|label|close[ -]?up|full view|front|back|before|after)\b",
            text,
        )
    )


def _educational_or_nonvisual(text: str) -> bool:
    if re.search(r"\b(?:how does|how do|what is|what are|explain)\b", text):
        return True
    if re.search(r"\bcompare\b", text) and not _visual_comparison_target(text):
        return True
    if re.search(r"\bcost|price|plans?|react|vue|framework|policy|study\b", text) and not _visual_comparison_target(text):
        return True
    return False


def _normalize(text: str) -> str:
    return " ".join(str(text or "").lower().split())
