from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_stormforge_live_voice_visualizer_ab_probe.py"


def _load_probe_module():
    spec = importlib.util.spec_from_file_location("stormforge_live_voice_ab_probe", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _case(module, case_id: str) -> dict[str, object]:
    return next(item for item in module.CASES if item["case"] == case_id)


def test_live_voice_ab_cases_define_required_env_overrides() -> None:
    module = _load_probe_module()

    assert [item["case"] for item in module.CASES[:6]] == ["A", "B", "C", "D", "E", "F"]

    case_a_env = module.case_env(_case(module, "A"))
    assert case_a_env["STORMHELM_UI_VARIANT"] == "stormforge"
    assert case_a_env["STORMHELM_STORMFORGE_FOG"] == "0"
    assert case_a_env["STORMHELM_ANCHOR_VISUALIZER_MODE"] == "off"

    case_f_env = module.case_env(_case(module, "F"))
    assert case_f_env["STORMHELM_UI_VARIANT"] == "stormforge"
    assert case_f_env["STORMHELM_STORMFORGE_FOG"] == "1"
    assert case_f_env["STORMHELM_ANCHOR_VISUALIZER_MODE"] == "envelope_timeline"

    case_g_env = module.case_env(_case(module, "G"))
    assert case_g_env["STORMHELM_UI_VARIANT"] == "stormforge"
    assert case_g_env["STORMHELM_STORMFORGE_FOG"] == "1"
    assert "STORMHELM_ANCHOR_VISUALIZER_MODE" not in case_g_env


def test_classifies_decision_table_without_guessing() -> None:
    module = _load_probe_module()

    assert module.classify_root_cause(
        [{"case": "A", "subjective_result": "stutter"}]
    ) == "case_a_stutter_real_voice_bridge_or_ghost_runtime_pressure"

    assert module.classify_root_cause(
        [
            {"case": "A", "subjective_result": "smooth"},
            {"case": "B", "subjective_result": "stutter"},
        ]
    ) == "case_b_stutter_anchor_canvas_or_speaking_state_churn"

    assert module.classify_root_cause(
        [
            {"case": "A", "subjective_result": "smooth"},
            {"case": "B", "subjective_result": "smooth"},
            {"case": "C", "subjective_result": "smooth"},
            {"case": "D", "subjective_result": "stutter"},
        ]
    ) == "case_d_stutter_envelope_timeline_sampling_or_payload_churn"

    assert module.classify_root_cause(
        [
            {"case": "A", "subjective_result": "smooth"},
            {"case": "B", "subjective_result": "smooth"},
            {"case": "C", "subjective_result": "smooth"},
            {"case": "D", "subjective_result": "smooth"},
            {"case": "E", "subjective_result": "stutter"},
            {"case": "F", "subjective_result": "stutter"},
        ]
    ) == "fog_render_load_combined_with_real_voice"

    assert module.classify_root_cause(
        [
            {"case": "A", "subjective_result": "smooth"},
            {"case": "B", "subjective_result": "smooth"},
            {"case": "C", "subjective_result": "smooth"},
            {"case": "D", "subjective_result": "smooth"},
            {"case": "E", "subjective_result": "smooth"},
            {"case": "F", "subjective_result": "smooth"},
            {"case": "G", "subjective_result": "stutter"},
        ]
    ) == "default_source_selection_or_env_config_mismatch"


def test_case_summary_keeps_required_fields_and_not_available_values() -> None:
    module = _load_probe_module()
    started = 100.0
    samples = [
        {
            "sample_t": started + 0.0,
            "speaking_visual_active": True,
            "latest_voice_energy": 0.2,
            "visualizerSourceStrategy": "playback_envelope_timeline",
            "visualizerSourceSwitchCount": 0,
            "forcedVisualizerModeHonored": True,
            "visualizerStrategySelectedBy": "config",
            "playback_envelope_alignment_delta_ms": 12,
            "playback_envelope_alignment_tolerance_ms": 260,
            "playback_envelope_alignment_status": "ahead_clamped",
        },
        {
            "sample_t": started + 0.5,
            "speaking_visual_active": True,
            "latest_voice_energy": 0.5,
            "visualizerSourceStrategy": "playback_envelope_timeline",
            "visualizerSourceSwitchCount": 0,
            "forcedVisualizerModeHonored": True,
            "visualizerStrategySelectedBy": "config",
            "playback_envelope_alignment_delta_ms": 8,
            "playback_envelope_alignment_tolerance_ms": 260,
            "playback_envelope_alignment_status": "aligned",
        },
    ]

    summary = module.summarize_case_samples(samples, started_at=started, ended_at=started + 1.0)

    assert summary["finalSpeakingEnergy_min"] == 0.2
    assert summary["finalSpeakingEnergy_max"] == 0.5
    assert summary["finalSpeakingEnergy_range"] == 0.3
    assert summary["chosen_visualizer_strategy"] == "playback_envelope_timeline"
    assert summary["visualizer_source_switch_count"] == 0
    assert summary["forced_visualizer_mode_honored"] is True
    assert summary["visualizer_strategy_selected_by"] == "config"
    assert summary["playback_envelope_alignment_delta_ms"] == 8
    assert summary["playback_envelope_alignment_tolerance_ms"] == 260
    assert summary["frameSwapped_fps"] == "not_available"
    assert summary["anchor_paint_count_per_second"] == "not_available"


def test_case_summary_uses_latest_envelope_usability_and_reports_disagreement() -> None:
    module = _load_probe_module()
    started = 200.0
    samples = [
        {
            "sample_t": started + 0.0,
            "speaking_visual_active": True,
            "visualizerSourceStrategy": "playback_envelope_timeline",
            "playback_envelope_usable": True,
            "playback_envelope_alignment_status": "aligned",
            "playback_envelope_energy": 0.22,
        },
        {
            "sample_t": started + 0.5,
            "speaking_visual_active": True,
            "visualizerSourceStrategy": "playback_envelope_timeline",
            "playback_envelope_usable": False,
            "playback_envelope_usable_reason": "playback_envelope_unaligned",
            "playback_envelope_alignment_status": "not_playback_time",
            "playback_envelope_energy": 0.0,
        },
    ]

    summary = module.summarize_case_samples(samples, started_at=started, ended_at=started + 1.0)

    assert summary["playback_envelope_usable"] is False
    assert summary["playback_envelope_usable_any"] is True
    assert summary["playback_envelope_usability_snapshot_disagreement"] is True
    assert summary["playback_envelope_usable_reason"] == "playback_envelope_unaligned"
    assert summary["playback_envelope_alignment_status"] == "not_playback_time"


def test_spoken_stimulus_diagnostics_marks_openai_error_as_invalid() -> None:
    module = _load_probe_module()
    samples = [
        {
            "last_spoken_text_preview": "OpenAI integration is not configured.",
            "last_synthesis_state": "failed",
            "last_synthesis_error_message": "missing key",
            "last_openai_tts_call_blocked_reason": "openai_key_missing",
        }
    ]
    trigger_response = {
        "assistant_message": {
            "content": "OpenAI integration is not configured.",
            "metadata": {"spoken_response": "OpenAI integration is not configured."},
        }
    }

    diagnostics = module.spoken_stimulus_diagnostics(
        requested_prompt="Testing one, two, three. Anchor sync check.",
        trigger_response=trigger_response,
        samples=samples,
        settings={"openai": {"enabled": False}},
    )

    assert diagnostics["spoken_text_requested"] == "Testing one, two, three. Anchor sync check."
    assert diagnostics["spoken_text_actual"] == "OpenAI integration is not configured."
    assert diagnostics["valid_spoken_stimulus"] is False
    assert diagnostics["voice_output_path"] == "fallback_error"
    assert diagnostics["spoken_fallback_reason"] == "openai_integration_not_configured"
    assert diagnostics["tts_provider_configured"] is False


def test_probe_cli_can_require_valid_spoken_stimulus_and_request_fixture() -> None:
    module = _load_probe_module()

    args = module.build_parser().parse_args(
        ["--dry-run", "--require-valid-spoken-stimulus", "--use-local-voice-test-fixture"]
    )

    assert args.require_valid_spoken_stimulus is True
    assert args.use_local_voice_test_fixture is True


def test_source_expectation_check_flags_forced_mode_mismatch() -> None:
    module = _load_probe_module()

    ok = module.source_expectation_check(
        {"STORMHELM_ANCHOR_VISUALIZER_MODE": "constant_test_wave"},
        {"chosen_visualizer_strategy": "constant_test_wave"},
    )
    assert ok["source_mismatch_detected"] is False
    assert ok["expected_visualizer_strategy"] == "constant_test_wave"

    mismatch = module.source_expectation_check(
        {"STORMHELM_ANCHOR_VISUALIZER_MODE": "envelope_timeline"},
        {"chosen_visualizer_strategy": "procedural_speaking"},
    )
    assert mismatch["source_mismatch_detected"] is True
    assert "expected playback_envelope_timeline" in mismatch["source_mismatch_reason"]


def test_report_payload_includes_live_audible_and_cache_runtime_sections(tmp_path: Path) -> None:
    module = _load_probe_module()
    report = module.build_report(
        cases=[
            {
                "case": "A",
                "name": "fog_off_visualizer_off",
                "subjective_result": "not_tested",
                "real_audible_playback_occurred": False,
            }
        ],
        process_state={"core": {"pid": 123}, "ui": {"pid": 456}},
        cache_state={"cleared": False, "reason": "not_requested"},
        spoken_prompt="Testing one, two, three. Anchor sync check.",
    )

    assert report["live_audible_voice_playback_exercised"] is False
    assert report["spoken_prompt"] == "Testing one, two, three. Anchor sync check."
    assert report["process_state"]["core"]["pid"] == 123
    assert report["cache_state"]["cleared"] is False
    assert report["root_cause_classification"] == "insufficient_live_audible_ab_results"

    module.write_artifacts(report, tmp_path)
    assert (tmp_path / "live_voice_visualizer_ab_report.json").exists()
    assert (tmp_path / "live_voice_visualizer_ab_report.md").exists()
    assert (tmp_path / "live_voice_visualizer_ab_observations.csv").exists()


def test_probe_cli_defaults_to_quiet_polling_with_verbose_opt_in() -> None:
    module = _load_probe_module()

    quiet_args = module.build_parser().parse_args(["--dry-run"])
    assert quiet_args.verbose_polling is False
    assert quiet_args.print_report_json is False

    verbose_args = module.build_parser().parse_args(
        ["--dry-run", "--verbose-polling", "--print-report-json"]
    )
    assert verbose_args.verbose_polling is True
    assert verbose_args.print_report_json is True


def test_child_process_log_plan_redirects_by_default(tmp_path: Path) -> None:
    module = _load_probe_module()

    quiet_plan = module.child_log_plan(
        case={"case": "A", "name": "fog_off_visualizer_off"},
        output_dir=tmp_path,
        verbose_polling=False,
    )
    assert quiet_plan["redirected"] is True
    assert quiet_plan["core_log_path"].endswith("case_A_fog_off_visualizer_off_core.log")
    assert quiet_plan["ui_log_path"].endswith("case_A_fog_off_visualizer_off_ui.log")

    verbose_plan = module.child_log_plan(
        case={"case": "A", "name": "fog_off_visualizer_off"},
        output_dir=tmp_path,
        verbose_polling=True,
    )
    assert verbose_plan == {"redirected": False, "reason": "verbose_polling_enabled"}


def test_polling_summary_counts_samples_and_errors() -> None:
    module = _load_probe_module()

    summary = module.polling_terminal_summary(
        [
            {"t_ms": 0},
            {"t_ms": 100, "status_error": "timeout"},
            {"t_ms": 200},
        ]
    )

    assert summary == "Captured 3 status samples, 1 request errors."
