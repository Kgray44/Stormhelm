from __future__ import annotations

from stormhelm.core.voice.speech_renderer import SpokenResponseRenderer
from stormhelm.core.voice.speech_renderer import SpokenResponseRequest


def test_spoken_response_renderer_uses_core_spoken_summary() -> None:
    result = SpokenResponseRenderer().render(
        SpokenResponseRequest(
            source_result_state="completed",
            spoken_summary="Bearing acquired. Opening Downloads.",
            visual_text="Downloads opened.",
            speak_allowed=True,
            spoken_responses_enabled=True,
        )
    )

    assert result.should_speak is True
    assert result.spoken_text == "Bearing acquired. Opening Downloads."
    assert result.visual_text == "Downloads opened."


def test_spoken_response_renderer_does_not_invent_completion_wording() -> None:
    result = SpokenResponseRenderer().render(
        SpokenResponseRequest(
            source_result_state="planned",
            spoken_summary="",
            visual_text="Install plan prepared. Approval is still required.",
            speak_allowed=True,
            spoken_responses_enabled=True,
        )
    )

    assert result.should_speak is True
    assert "done" not in result.spoken_text.lower()
    assert "completed" not in result.spoken_text.lower()
    assert "planned" in result.spoken_text.lower()


def test_spoken_response_renderer_stays_silent_when_spoken_responses_disabled() -> None:
    result = SpokenResponseRenderer().render(
        SpokenResponseRequest(
            source_result_state="completed",
            spoken_summary="Bearing acquired.",
            visual_text="Downloads opened.",
            speak_allowed=True,
            spoken_responses_enabled=False,
        )
    )

    assert result.should_speak is False
    assert result.reason_if_not_speaking == "spoken_responses_disabled"
    assert result.spoken_text == ""
