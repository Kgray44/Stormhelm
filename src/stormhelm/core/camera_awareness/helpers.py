from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Protocol

from stormhelm.core.camera_awareness.models import (
    CameraConfidenceLevel,
    CameraEngineeringHelperResult,
    CameraHelperCategory,
    CameraHelperClassification,
    CameraHelperFamily,
    CameraVisionAnswer,
)


class CameraAwarenessHelper(Protocol):
    category: CameraHelperCategory

    def classify(
        self,
        *,
        user_question: str,
        vision_answer: CameraVisionAnswer | None,
    ) -> CameraHelperClassification:
        ...

    def build_result(
        self,
        *,
        user_question: str,
        vision_answer: CameraVisionAnswer,
    ) -> CameraEngineeringHelperResult | None:
        ...


@dataclass(slots=True)
class CameraAwarenessHelperRegistry:
    helpers: tuple[CameraAwarenessHelper, ...]

    def classify(
        self,
        *,
        user_question: str,
        vision_answer: CameraVisionAnswer | None = None,
    ) -> CameraHelperClassification:
        for helper in self.helpers:
            classification = helper.classify(
                user_question=user_question,
                vision_answer=vision_answer,
            )
            if classification.applicable:
                return classification
        return CameraHelperClassification()

    def build_result(
        self,
        *,
        user_question: str,
        vision_answer: CameraVisionAnswer,
    ) -> CameraEngineeringHelperResult | None:
        classification = self.classify(
            user_question=user_question,
            vision_answer=vision_answer,
        )
        if not classification.applicable:
            return None
        for helper in self.helpers:
            if helper.category == classification.category:
                return helper.build_result(
                    user_question=user_question,
                    vision_answer=vision_answer,
                )
        return None


class EngineeringInspectionHelper:
    category = CameraHelperCategory.ENGINEERING_INSPECTION

    def classify(
        self,
        *,
        user_question: str,
        vision_answer: CameraVisionAnswer | None,
    ) -> CameraHelperClassification:
        hinted_family = _helper_family_from_hints(_helper_hints(vision_answer))
        if hinted_family not in {CameraHelperFamily.UNKNOWN, CameraHelperFamily.ENGINEERING_UNKNOWN}:
            return CameraHelperClassification(
                category=self.category,
                helper_family=hinted_family,
                applicable=True,
                confidence=CameraConfidenceLevel.MEDIUM,
                reasons=["provider_helper_hint"],
            )

        text = _normalize(user_question)
        if not text or _educational_or_catalog_request(text):
            return CameraHelperClassification()

        family, reason = _classify_engineering_text(text)
        if family == CameraHelperFamily.UNKNOWN:
            return CameraHelperClassification()
        return CameraHelperClassification(
            category=self.category,
            helper_family=family,
            applicable=True,
            confidence=CameraConfidenceLevel.MEDIUM,
            reasons=[reason],
        )

    def build_result(
        self,
        *,
        user_question: str,
        vision_answer: CameraVisionAnswer,
    ) -> CameraEngineeringHelperResult | None:
        classification = self.classify(
            user_question=user_question,
            vision_answer=vision_answer,
        )
        if not classification.applicable:
            return None
        hints = _helper_hints(vision_answer)
        family = classification.helper_family
        if family == CameraHelperFamily.ENGINEERING_RESISTOR_COLOR_BANDS:
            return _resistor_result(vision_answer, hints)
        if family == CameraHelperFamily.ENGINEERING_CONNECTOR_IDENTIFICATION:
            return _connector_result(vision_answer, hints)
        if family in {
            CameraHelperFamily.ENGINEERING_COMPONENT_MARKING,
            CameraHelperFamily.ENGINEERING_LABEL_READING,
        }:
            return _marking_result(vision_answer, hints)
        if family == CameraHelperFamily.ENGINEERING_SOLDER_JOINT_INSPECTION:
            return _solder_result(vision_answer, hints)
        if family == CameraHelperFamily.ENGINEERING_PCB_VISUAL_INSPECTION:
            return _pcb_result(vision_answer, hints)
        if family == CameraHelperFamily.ENGINEERING_PHOTO_QUALITY_GUIDANCE:
            return _photo_quality_result(vision_answer, hints)
        if family == CameraHelperFamily.ENGINEERING_MECHANICAL_PART_INSPECTION:
            return _mechanical_result(vision_answer, hints)
        if family == CameraHelperFamily.ENGINEERING_PHYSICAL_TROUBLESHOOTING:
            return _physical_troubleshooting_result(vision_answer, hints)
        return _generic_engineering_result(vision_answer, hints, family)


def build_default_camera_helper_registry() -> CameraAwarenessHelperRegistry:
    return CameraAwarenessHelperRegistry(helpers=(EngineeringInspectionHelper(),))


def _classify_engineering_text(text: str) -> tuple[CameraHelperFamily, str]:
    if re.search(r"\b(?:resistor|resistance|ohm|colour bands?|color bands?|bands?)\b", text):
        return CameraHelperFamily.ENGINEERING_RESISTOR_COLOR_BANDS, "resistor_visual_request"
    if re.search(r"\b(?:connector|jst|plug|socket|header|pinout)\b", text):
        return CameraHelperFamily.ENGINEERING_CONNECTOR_IDENTIFICATION, "connector_visual_request"
    if re.search(r"\b(?:blur|blurry|glare|lighting|framing|retake|photo quality|scale reference|too dark|out of focus)\b", text):
        return CameraHelperFamily.ENGINEERING_PHOTO_QUALITY_GUIDANCE, "photo_quality_request"
    if re.search(r"\b(?:ic marking|chip marking|component marking|marking|part number|label|readable text)\b", text):
        return CameraHelperFamily.ENGINEERING_COMPONENT_MARKING, "marking_visual_request"
    if re.search(r"\b(?:what does|what's|read|say)\b.{0,32}\b(?:ic|chip|component)\b", text):
        return CameraHelperFamily.ENGINEERING_COMPONENT_MARKING, "marking_visual_request"
    if re.search(r"\b(?:solder|cold joint|solder joint|joint|bridge|bridged)\b", text):
        return CameraHelperFamily.ENGINEERING_SOLDER_JOINT_INSPECTION, "solder_visual_request"
    if re.search(r"\b(?:pcb|circuit board|board|trace|pads?)\b", text):
        return CameraHelperFamily.ENGINEERING_PCB_VISUAL_INSPECTION, "pcb_visual_request"
    if re.search(r"\b(?:screw|bolt|nut|washer|gear|bearing|bracket|fastener|thread|countersunk)\b", text):
        return CameraHelperFamily.ENGINEERING_MECHANICAL_PART_INSPECTION, "mechanical_visual_request"
    if re.search(r"\b(?:warning light|indicator|status light|led|fault light|front panel)\b", text):
        return CameraHelperFamily.ENGINEERING_PHYSICAL_TROUBLESHOOTING, "physical_troubleshooting_request"
    return CameraHelperFamily.UNKNOWN, ""


def _educational_or_catalog_request(text: str) -> bool:
    educational = re.search(
        r"\b(?:how do|how does|explain|show examples?|show me examples?|examples? of|what is a|what is an|what is the)\b",
        text,
    )
    if not educational:
        return False
    deictic_visual = re.search(r"\b(?:this|that|these|those|holding|in front of me|with the camera|camera)\b", text)
    return not bool(deictic_visual)


def _resistor_result(
    vision_answer: CameraVisionAnswer,
    hints: dict[str, Any],
) -> CameraEngineeringHelperResult:
    bands = _string_list(hints.get("visible_bands") or hints.get("bands"))
    decoded = _decode_resistor_bands(bands)
    visual_estimate = decoded.get("estimate", "") if decoded else ""
    deterministic = bool(decoded)
    evidence = [f"Visible band sequence: {', '.join(bands)}"] if bands else []
    if vision_answer.evidence_summary:
        evidence.append(vision_answer.evidence_summary)
    if not visual_estimate:
        visual_estimate = _safe_text(hints.get("visual_estimate")) or "Band sequence is unclear from the still."
    return _base_result(
        vision_answer,
        family=CameraHelperFamily.ENGINEERING_RESISTOR_COLOR_BANDS,
        title="Resistor Estimate",
        visual_estimate=visual_estimate,
        visual_evidence=evidence,
        caveats=[
            "Visual estimate only; confirm the part out of circuit when accuracy matters.",
            "Band colors can shift with glare, aging, or camera white balance.",
        ],
        suggested_measurements=[
            "Confirm resistance with a multimeter.",
            "Lift one leg or isolate the circuit if parallel paths may affect the reading.",
        ],
        suggested_next_capture=vision_answer.suggested_next_capture
        or "Retake square-on with brighter light if any band color is uncertain.",
        deterministic_calculation_used=deterministic,
        calculation_trace_id=decoded.get("trace_id") if decoded else None,
    )


def _connector_result(
    vision_answer: CameraVisionAnswer,
    hints: dict[str, Any],
) -> CameraEngineeringHelperResult:
    family = _safe_text(hints.get("likely_connector_family")) or "Uncertain connector family"
    scale_present = _bool(hints.get("scale_reference_present"))
    return _base_result(
        vision_answer,
        family=CameraHelperFamily.ENGINEERING_CONNECTOR_IDENTIFICATION,
        title="Connector Visual ID",
        visual_estimate=family,
        visual_evidence=_evidence(vision_answer, [f"Likely family: {family}"]),
        caveats=[
            "Pitch and scale are uncertain without a ruler, calipers, or known reference.",
            "Similar connector families can look alike from one still.",
        ],
        suggested_measurements=[
            "Measure pin pitch with calipers.",
            "Count pins and compare latch/keying from another angle.",
        ],
        suggested_next_capture=(
            None
            if scale_present
            else "Retake with a ruler or known-size part next to the connector."
        ),
    )


def _marking_result(
    vision_answer: CameraVisionAnswer,
    hints: dict[str, Any],
) -> CameraEngineeringHelperResult:
    readable = _safe_text(hints.get("readable_text")) or "No confident marking read."
    uncertain = _safe_text(hints.get("uncertain_text"))
    caveats = [
        "Marking read is visual only; uncertain characters should be checked against the package.",
        "Do not infer a datasheet or exact variant from a partial marking alone.",
    ]
    evidence = _evidence(vision_answer, [f"Readable text: {readable}"])
    if uncertain:
        evidence.append(f"Uncertain text: {uncertain}")
    return _base_result(
        vision_answer,
        family=CameraHelperFamily.ENGINEERING_COMPONENT_MARKING,
        title="Component Marking Read",
        visual_estimate=readable,
        visual_evidence=evidence,
        caveats=caveats,
        suggested_measurements=["Cross-check the marking against the board silkscreen or known BOM."],
        suggested_next_capture="Retake with the marking flat, sharp, and glare-free if any character is uncertain.",
    )


def _solder_result(
    vision_answer: CameraVisionAnswer,
    hints: dict[str, Any],
) -> CameraEngineeringHelperResult:
    issue = _safe_text(hints.get("visible_issue")) or "No single defect confidently identified."
    return _base_result(
        vision_answer,
        family=CameraHelperFamily.ENGINEERING_SOLDER_JOINT_INSPECTION,
        title="Solder Joint Visual Check",
        visual_estimate=issue,
        visual_evidence=_evidence(vision_answer, [f"Visible issue: {issue}"]),
        caveats=[
            "Visual evidence can flag suspect joints but cannot prove electrical continuity.",
            "Electrically verify continuity and inspect under magnification before treating this as confirmed.",
        ],
        suggested_measurements=[
            "Use continuity or resistance checks where safe.",
            "Inspect under magnification with side lighting.",
        ],
        suggested_next_capture="Retake closer with angled light across the solder fillet.",
    )


def _pcb_result(
    vision_answer: CameraVisionAnswer,
    hints: dict[str, Any],
) -> CameraEngineeringHelperResult:
    issue = _safe_text(hints.get("visible_issue")) or "No single PCB fault confidently identified."
    return _base_result(
        vision_answer,
        family=CameraHelperFamily.ENGINEERING_PCB_VISUAL_INSPECTION,
        title="PCB Visual Inspection",
        visual_estimate=issue,
        visual_evidence=_evidence(vision_answer, [f"Visible observation: {issue}"]),
        caveats=[
            "A still image can suggest visible defects only; it cannot verify the circuit state.",
            "A closer capture may be needed for bridges, cracks, lifted pads, or residue.",
        ],
        suggested_measurements=[
            "Check suspected shorts or opens with a meter after power is removed.",
        ],
        suggested_next_capture="Retake closer and sharper with the suspected area centered.",
    )


def _photo_quality_result(
    vision_answer: CameraVisionAnswer,
    hints: dict[str, Any],
) -> CameraEngineeringHelperResult:
    warnings = _string_list(hints.get("quality_warnings"))
    if not warnings:
        warnings = list(vision_answer.uncertainty_reasons)
    estimate = ", ".join(warnings) if warnings else "Photo quality limits are not specified."
    return _base_result(
        vision_answer,
        family=CameraHelperFamily.ENGINEERING_PHOTO_QUALITY_GUIDANCE,
        title="Retake Guidance",
        visual_estimate=estimate,
        visual_evidence=_evidence(vision_answer, [f"Quality limits: {estimate}"]),
        caveats=[
            "Retake guidance does not analyze a new image by itself.",
            "No capture, upload, or save is triggered by this helper result.",
        ],
        suggested_measurements=["Add a ruler, calipers, or known-size reference if dimensions matter."],
        suggested_next_capture=(
            "Retake with sharper focus, less glare, brighter even lighting, centered framing, "
            "visible labels, and a scale reference."
        ),
    )


def _mechanical_result(
    vision_answer: CameraVisionAnswer,
    hints: dict[str, Any],
) -> CameraEngineeringHelperResult:
    part = _safe_text(hints.get("visible_part")) or "Uncertain mechanical part."
    return _base_result(
        vision_answer,
        family=CameraHelperFamily.ENGINEERING_MECHANICAL_PART_INSPECTION,
        title="Mechanical Part Visual Check",
        visual_estimate=part,
        visual_evidence=_evidence(vision_answer, [f"Visible part: {part}"]),
        caveats=[
            "Dimensions, thread pitch, material, and fit cannot be confirmed from the still alone.",
            "Visual similarity is not proof of compatibility.",
        ],
        suggested_measurements=[
            "Measure diameter, length, pitch, and head shape with the appropriate tools.",
        ],
        suggested_next_capture="Retake beside a ruler and include side/profile views if geometry matters.",
    )


def _physical_troubleshooting_result(
    vision_answer: CameraVisionAnswer,
    hints: dict[str, Any],
) -> CameraEngineeringHelperResult:
    symptom = _safe_text(hints.get("visible_issue") or hints.get("indicator_state")) or "Visible physical symptom."
    return _base_result(
        vision_answer,
        family=CameraHelperFamily.ENGINEERING_PHYSICAL_TROUBLESHOOTING,
        title="Physical Symptom Visual Check",
        visual_estimate=symptom,
        visual_evidence=_evidence(vision_answer, [f"Visible symptom: {symptom}"]),
        caveats=[
            "A visible indicator is evidence only; it does not confirm root cause.",
            "Do not treat the image as a verified repair or safe operating state.",
        ],
        suggested_measurements=[
            "Check the device manual, status codes, and safe electrical measurements if applicable.",
        ],
        suggested_next_capture="Retake with labels and the whole indicator area visible.",
    )


def _generic_engineering_result(
    vision_answer: CameraVisionAnswer,
    hints: dict[str, Any],
    family: CameraHelperFamily,
) -> CameraEngineeringHelperResult:
    return _base_result(
        vision_answer,
        family=family,
        title="Engineering Visual Helper",
        visual_estimate=_safe_text(hints.get("visual_estimate")) or vision_answer.concise_answer,
        visual_evidence=_evidence(vision_answer, []),
        caveats=["Visual helper output is evidence only and not a measurement or verification."],
        suggested_measurements=["Use the appropriate instrument or datasheet before relying on the observation."],
        suggested_next_capture=vision_answer.suggested_next_capture,
    )


def _base_result(
    vision_answer: CameraVisionAnswer,
    *,
    family: CameraHelperFamily,
    title: str,
    visual_estimate: str,
    visual_evidence: list[str],
    caveats: list[str],
    suggested_measurements: list[str],
    suggested_next_capture: str | None,
    deterministic_calculation_used: bool = False,
    calculation_trace_id: str | None = None,
) -> CameraEngineeringHelperResult:
    return CameraEngineeringHelperResult(
        vision_answer_id=vision_answer.vision_answer_id,
        artifact_id=vision_answer.image_artifact_id,
        helper_family=family,
        title=title,
        concise_answer=_helper_concise_answer(title, visual_estimate),
        detailed_answer=vision_answer.detailed_answer or vision_answer.answer_text,
        confidence_kind=vision_answer.confidence,
        source_provenance=str(vision_answer.provenance.get("source") or "camera_unavailable"),
        provider_kind=vision_answer.provider_kind,
        visual_estimate=_safe_text(visual_estimate),
        visual_evidence=[_safe_text(item) for item in visual_evidence if _safe_text(item)][:6],
        uncertainty_reasons=[_safe_text(item) for item in vision_answer.uncertainty_reasons if _safe_text(item)][:6],
        caveats=[_safe_text(item) for item in caveats if _safe_text(item)][:6],
        suggested_next_capture=_safe_text(suggested_next_capture),
        suggested_measurements=[_safe_text(item) for item in suggested_measurements if _safe_text(item)][:6],
        suggested_user_actions=[
            "Treat this as visual evidence, not command authority.",
            "Verify with measurement or a trusted reference before acting on critical decisions.",
        ],
        deterministic_calculation_used=deterministic_calculation_used,
        calculation_trace_id=calculation_trace_id,
        mock_analysis=vision_answer.mock_answer,
        cloud_analysis_performed=vision_answer.cloud_analysis_performed,
        verified_measurement=False,
        action_executed=False,
        trust_approved=False,
        task_mutation_performed=False,
        raw_image_included=False,
    )


def _decode_resistor_bands(bands: list[str]) -> dict[str, str] | None:
    if len(bands) < 4:
        return None
    normalized = [_normalize_color(band) for band in bands[:4]]
    digits = {
        "black": 0,
        "brown": 1,
        "red": 2,
        "orange": 3,
        "yellow": 4,
        "green": 5,
        "blue": 6,
        "violet": 7,
        "gray": 8,
        "white": 9,
    }
    multipliers = {
        "black": 1.0,
        "brown": 10.0,
        "red": 100.0,
        "orange": 1000.0,
        "yellow": 10000.0,
        "green": 100000.0,
        "blue": 1000000.0,
        "violet": 10000000.0,
        "gray": 100000000.0,
        "white": 1000000000.0,
        "gold": 0.1,
        "silver": 0.01,
    }
    tolerances = {
        "brown": "1%",
        "red": "2%",
        "green": "0.5%",
        "blue": "0.25%",
        "violet": "0.1%",
        "gray": "0.05%",
        "gold": "5%",
        "silver": "10%",
    }
    first, second, multiplier, tolerance = normalized
    if first not in digits or second not in digits or multiplier not in multipliers:
        return None
    value = ((digits[first] * 10) + digits[second]) * multipliers[multiplier]
    tolerance_text = tolerances.get(tolerance, "unknown tolerance")
    return {
        "estimate": f"{_format_ohms(value)} +/-{tolerance_text}",
        "trace_id": f"resistor-bands:{'-'.join(normalized)}",
    }


def _format_ohms(value: float) -> str:
    if value >= 1_000_000:
        amount = value / 1_000_000
        suffix = "MOhm"
    elif value >= 1_000:
        amount = value / 1_000
        suffix = "kOhm"
    else:
        amount = value
        suffix = "Ohm"
    if amount == int(amount):
        return f"{int(amount)} {suffix}"
    return f"{amount:g} {suffix}"


def _helper_hints(vision_answer: CameraVisionAnswer | None) -> dict[str, Any]:
    if vision_answer is None:
        return {}
    hints = vision_answer.helper_hints
    return dict(hints) if isinstance(hints, dict) else {}


def _helper_family_from_hints(hints: dict[str, Any]) -> CameraHelperFamily:
    value = _safe_text(hints.get("helper_family") or hints.get("family"))
    if not value:
        return CameraHelperFamily.UNKNOWN
    try:
        return CameraHelperFamily(value)
    except ValueError:
        return CameraHelperFamily.UNKNOWN


def _evidence(vision_answer: CameraVisionAnswer, extra: list[str]) -> list[str]:
    evidence = list(extra)
    if vision_answer.evidence_summary:
        evidence.append(vision_answer.evidence_summary)
    return evidence


def _helper_concise_answer(title: str, visual_estimate: str) -> str:
    estimate = _safe_text(visual_estimate)
    return f"{title}: {estimate}" if estimate else title


def _string_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [_safe_text(item).lower() for item in value if _safe_text(item)]
    text = _safe_text(value)
    return [text.lower()] if text else []


def _safe_text(value: Any) -> str:
    text = str(value or "").strip()
    lowered = text.lower()
    if any(token in lowered for token in ("data:image", "base64,", "sk-")):
        return "[redacted]"
    return text[:360]


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "present", "available"}


def _normalize(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def _normalize_color(value: str) -> str:
    color = re.sub(r"[^a-z]", "", str(value or "").lower())
    aliases = {
        "grey": "gray",
        "purple": "violet",
    }
    return aliases.get(color, color)
