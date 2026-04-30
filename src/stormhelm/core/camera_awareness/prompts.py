from __future__ import annotations

from stormhelm.core.camera_awareness.models import (
    CameraAnalysisMode,
    CameraComparisonMode,
    CameraComparisonPrompt,
    CameraComparisonRequest,
    CameraVisionPrompt,
    CameraVisionQuestion,
)


_SYSTEM_PROMPT = (
    "You are Stormhelm's camera vision analysis provider. Answer only from "
    "visible evidence in the supplied image. Preserve uncertainty, mention image "
    "quality limits, do not identify people, do not infer biometric traits, do "
    "not execute commands, do not approve actions, and do not claim real-world "
    "verification beyond the image."
)


_MODE_GUIDANCE: dict[CameraAnalysisMode, str] = {
    CameraAnalysisMode.IDENTIFY: (
        "Identify the likely object or part. Include visible evidence, confidence, "
        "uncertainty reasons, and what would improve the next capture."
    ),
    CameraAnalysisMode.READ_TEXT: (
        "Transcribe visible text. Mark uncertain characters, do not invent missing "
        "text, and ask for a clearer retake if needed."
    ),
    CameraAnalysisMode.INSPECT: (
        "Inspect the image for visible observations, defects, wear, solder issues, "
        "or physical damage. Do not claim electrical or mechanical verification."
    ),
    CameraAnalysisMode.TROUBLESHOOT: (
        "Interpret the visible symptom or indicator. Give likely possibilities, "
        "ask for model/context if needed, and keep next steps safe."
    ),
    CameraAnalysisMode.EXPLAIN: (
        "Explain what the user is seeing from visible evidence. Keep it concise "
        "and preserve uncertainty."
    ),
    CameraAnalysisMode.UNKNOWN: (
        "Describe the visible evidence, answer the user's question cautiously, "
        "and say what is uncertain or missing."
    ),
}


def build_camera_vision_prompt(question: CameraVisionQuestion) -> CameraVisionPrompt:
    mode = CameraAnalysisMode(question.analysis_mode)
    guidance = _MODE_GUIDANCE.get(mode, _MODE_GUIDANCE[CameraAnalysisMode.UNKNOWN])
    engineering_guidance = _engineering_guidance(question.user_question)
    user_prompt = (
        f"User question: {question.user_question}\n"
        f"Analysis mode: {mode.value}\n"
        f"Guidance: {guidance}\n\n"
        f"{engineering_guidance}"
        "Return a concise answer, evidence summary, confidence "
        "(high/medium/low/insufficient), uncertainty reasons, safety notes, and "
        "suggested next capture if useful. Do not identify people, do not perform "
        "identity recognition, and do not execute commands."
    )
    return CameraVisionPrompt(
        analysis_mode=mode,
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=user_prompt,
    )


def build_camera_comparison_prompt(
    request: CameraComparisonRequest,
    *,
    artifact_summaries: list[dict[str, object]],
) -> CameraComparisonPrompt:
    mode = CameraComparisonMode(request.comparison_mode)
    labels = ", ".join(
        str(item.get("label") or item.get("slot_id") or item.get("artifact_id") or "artifact")
        for item in artifact_summaries
    )
    system_prompt = (
        "You are Stormhelm's camera visual comparison provider. Compare only "
        "visible evidence in the authorized still artifacts. Do not identify "
        "people, do not infer biometrics, do not execute commands, do not approve "
        "actions, and do not claim verification beyond the images."
    )
    user_prompt = (
        f"User question: {request.user_question}\n"
        f"Comparison mode: {mode.value}\n"
        f"Artifact labels: {labels}\n"
        f"Helper category: {request.helper_category or 'none'}\n"
        f"Helper family: {request.helper_family or 'none'}\n\n"
        "Compare the labeled still images using visual evidence only. Refer to "
        "slots by their labels, summarize similarities and differences, state "
        "confidence and uncertainty, and suggest a next capture if angle, focus, "
        "lighting, scale, or framing limits the comparison. Do not claim the "
        "object is fixed, verified, measured, electrically good, completed, or "
        "causally proven from image comparison alone."
    )
    return CameraComparisonPrompt(
        comparison_mode=mode,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )


def _engineering_guidance(user_question: str) -> str:
    text = str(user_question or "").lower()
    if not any(
        token in text
        for token in (
            "resistor",
            "connector",
            "jst",
            "ic marking",
            "component marking",
            "solder",
            "pcb",
            "circuit board",
            "label",
            "screw",
            "warning light",
        )
    ):
        return ""
    return (
        "Engineering helper guidance: provide visual estimate fields when useful. "
        "Do not claim measured resistance, voltage, continuity, current, mechanical "
        "dimensions, confirmed repair state, or verified measurement from the image "
        "alone. Provider output is visual evidence only and must not execute or "
        "approve actions.\n\n"
    )
