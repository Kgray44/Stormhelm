from __future__ import annotations

import json
from pathlib import Path
import subprocess
from urllib.request import urlopen
import zipfile

from stormhelm.config.loader import load_config
from stormhelm.core.adapters import ClaimOutcome
from stormhelm.core.adapters import default_adapter_contract_registry
from stormhelm.core.container import build_container
from stormhelm.core.live_browser_integration import LiveBrowserFixtureServer
from stormhelm.core.live_browser_integration import LiveBrowserIntegrationGates
from stormhelm.core.live_browser_integration import LiveBrowserIntegrationReport
from stormhelm.core.live_browser_integration import LiveBrowserIntegrationResult
from stormhelm.core.live_browser_integration import LiveBrowserIntegrationRunner
from stormhelm.core.live_browser_integration import _live_grounding_target
from stormhelm.core.live_browser_integration import _live_guidance_message
from stormhelm.core.live_browser_integration import apply_live_browser_profile
from stormhelm.core.orchestrator.planner import DeterministicPlanner
from stormhelm.core.screen_awareness import PlaywrightBrowserSemanticAdapter
from stormhelm.core.screen_awareness.models import BrowserSemanticControl
from stormhelm.core.screen_awareness.models import BrowserSemanticObservation
from stormhelm.core.web_retrieval.safety import validate_public_url


def test_live_browser_gates_skip_by_default(temp_config) -> None:
    gates = LiveBrowserIntegrationGates.from_env({})
    config = apply_live_browser_profile(temp_config, gates)
    report = LiveBrowserIntegrationRunner(config, gates=gates).run_all()

    assert gates.live_browser_tests is False
    assert report.overall_status == "skipped"
    assert all(result.status == "skipped" for result in report.results.values())
    assert report.safety_gates_active["live_browser_tests"] is False


def test_live_profile_enables_requested_providers_without_action_capabilities(temp_config) -> None:
    gates = LiveBrowserIntegrationGates.from_env(
        {
            "STORMHELM_LIVE_BROWSER_TESTS": "true",
            "STORMHELM_ENABLE_LIVE_OBSCURA": "true",
            "STORMHELM_ENABLE_LIVE_OBSCURA_CDP": "true",
            "STORMHELM_ENABLE_LIVE_PLAYWRIGHT": "true",
            "STORMHELM_PLAYWRIGHT_ALLOW_BROWSER_LAUNCH": "true",
            "STORMHELM_OBSCURA_BINARY": "obscura-test",
        }
    )

    config = apply_live_browser_profile(temp_config, gates)
    playwright = config.screen_awareness.browser_adapters.playwright
    cdp = config.web_retrieval.obscura.cdp

    assert config.web_retrieval.enabled is True
    assert config.web_retrieval.obscura.enabled is True
    assert cdp.enabled is True
    assert cdp.host == "127.0.0.1"
    assert cdp.allow_runtime_eval is False
    assert cdp.allow_input_domain is False
    assert cdp.allow_cookies is False
    assert cdp.allow_logged_in_context is False
    assert playwright.enabled is True
    assert playwright.allow_dev_adapter is True
    assert playwright.allow_browser_launch is True
    assert playwright.allow_connect_existing is False
    assert playwright.allow_actions is False
    assert playwright.allow_click is False
    assert playwright.allow_focus is False
    assert playwright.allow_type_text is False
    assert playwright.allow_scroll is False
    assert playwright.allow_form_fill is False
    assert playwright.allow_form_submit is False
    assert playwright.allow_login is False
    assert playwright.allow_cookies is False
    assert playwright.allow_user_profile is False
    assert playwright.allow_screenshots is False
    assert playwright.allow_dev_actions is False


def test_missing_obscura_binary_reports_structured_unavailable(temp_config) -> None:
    gates = LiveBrowserIntegrationGates.from_env(
        {
            "STORMHELM_LIVE_BROWSER_TESTS": "true",
            "STORMHELM_ENABLE_LIVE_OBSCURA": "true",
            "STORMHELM_OBSCURA_BINARY": "stormhelm-obscura-missing-for-test",
            "STORMHELM_LIVE_BROWSER_TEST_URL": "https://example.com",
        }
    )
    config = apply_live_browser_profile(temp_config, gates)

    result = LiveBrowserIntegrationRunner(config, gates=gates).run_obscura_cli_check()

    assert result.status == "unavailable"
    assert result.error_code == "binary_missing"
    assert result.provider == "obscura_cli"
    assert result.claim_ceiling == "rendered_page_evidence"
    assert result.details["binary_found"] is False
    assert "not_user_visible_screen" in result.limitations
    assert "not_truth_verified" in result.limitations


def test_missing_playwright_dependency_reports_dependency_missing(temp_config, monkeypatch) -> None:
    gates = LiveBrowserIntegrationGates.from_env(
        {
            "STORMHELM_LIVE_BROWSER_TESTS": "true",
            "STORMHELM_ENABLE_LIVE_PLAYWRIGHT": "true",
            "STORMHELM_PLAYWRIGHT_ALLOW_BROWSER_LAUNCH": "true",
        }
    )
    monkeypatch.setattr("stormhelm.core.live_browser_integration.find_spec", lambda _name: None)
    config = apply_live_browser_profile(temp_config, gates)

    result = LiveBrowserIntegrationRunner(config, gates=gates).run_playwright_readiness_check()

    assert result.status == "unavailable"
    assert result.error_code == "dependency_missing"
    assert result.provider == "playwright"
    assert result.claim_ceiling == "browser_semantic_observation"
    assert result.details["actions_enabled"] is False
    assert result.details["dependency_installed"] is False


def test_live_report_serializes_statuses_without_raw_content_or_secrets() -> None:
    report = LiveBrowserIntegrationReport(
        results={
            "obscura_cli": LiveBrowserIntegrationResult(
                provider="obscura_cli",
                status="unavailable",
                enabled=True,
                claim_ceiling="rendered_page_evidence",
                error_code="binary_missing",
                bounded_error_message="x" * 1200 + " secret-token",
                details={"raw_html": "<html>secret-token</html>", "safe_url_display": "https://example.com/path?secret-token"},
                limitations=["not_truth_verified"],
            )
        },
        safety_gates_active={"live_browser_tests": True, "actions_disabled": True},
    )

    payload = report.to_dict()
    text = json.dumps(payload)

    assert payload["overall_status"] == "unavailable"
    assert payload["results"]["obscura_cli"]["bounded_error_message"].endswith("...")
    assert "raw_html" not in text
    assert "secret-token" not in text
    assert payload["raw_output_redacted"] is True


def test_live_report_treats_navigation_unsupported_cdp_as_partial_when_other_live_checks_pass() -> None:
    report = LiveBrowserIntegrationReport(
        results={
            "obscura_cli": LiveBrowserIntegrationResult(
                provider="obscura_cli",
                status="passed",
                enabled=True,
                claim_ceiling="rendered_page_evidence",
            ),
            "obscura_cdp": LiveBrowserIntegrationResult(
                provider="obscura_cdp",
                status="incompatible",
                enabled=True,
                claim_ceiling="headless_cdp_page_evidence",
                error_code="cdp_navigation_unsupported",
                limitations=["cdp_diagnostic_only"],
                details={
                    "endpoint_discovered": True,
                    "compatible": False,
                    "diagnostic_only": True,
                    "recommended_fallback_provider": "obscura_cli",
                },
            ),
            "playwright_readiness": LiveBrowserIntegrationResult(
                provider="playwright",
                status="passed",
                enabled=True,
                claim_ceiling="browser_semantic_observation",
            ),
        },
        safety_gates_active={"actions_disabled": True},
    )

    payload = report.to_dict()

    assert report.overall_status == "partial"
    assert payload["overall_status"] == "partial"
    assert payload["results"]["obscura_cdp"]["details"]["compatible"] is False
    assert payload["results"]["obscura_cdp"]["details"]["diagnostic_only"] is True
    assert "Obscura CDP endpoint exists" in " ".join(payload["limitations"])


def test_live_playwright_guidance_uses_observed_control_and_live_wording() -> None:
    controls = [
        BrowserSemanticControl(
            control_id="link-learn",
            role="link",
            name="Learn more",
            visible=True,
            enabled=True,
        )
    ]

    assert _live_grounding_target(controls) == "Learn more"
    assert _live_guidance_message("I could not ground that target in the mock browser observation.") == (
        "I could not ground that target in the live browser semantic observation."
    )


def test_live_playwright_smoke_uses_screen_awareness_adapter_snapshot(monkeypatch, temp_config) -> None:
    calls: list[dict[str, object]] = []

    def fake_observe(self, url: str, *, fixture_mode: bool = False, context_options=None):
        del self, context_options
        calls.append({"url": url, "fixture_mode": fixture_mode})
        return BrowserSemanticObservation(
            provider="playwright_live_semantic",
            adapter_id="screen_awareness.browser.playwright",
            session_id="live-smoke",
            page_url=url,
            page_title="Stormhelm Fixture Form",
            browser_context_kind="isolated_playwright_context",
            controls=[
                BrowserSemanticControl(
                    control_id="button-continue",
                    role="button",
                    name="Continue",
                    visible=True,
                    enabled=True,
                )
            ],
            forms=[{"form_id": "checkout", "field_count": 1}],
            limitations=[
                "live_semantic_observation_only",
                "isolated_temporary_browser_context",
                "no_actions",
                "not_visible_screen_verification",
                "not_truth_verified",
            ],
            confidence=0.72,
        )

    monkeypatch.setattr("stormhelm.core.live_browser_integration.find_spec", lambda _name: object())
    monkeypatch.setattr("stormhelm.core.live_browser_integration._playwright_browser_engine_available", lambda: (True, ""))
    monkeypatch.setattr(PlaywrightBrowserSemanticAdapter, "observe_live_browser_page", fake_observe)
    runner = LiveBrowserIntegrationRunner(
        temp_config,
        gates=LiveBrowserIntegrationGates(
            live_browser_tests=True,
            enable_playwright=True,
            playwright_allow_browser_launch=True,
        ),
    )

    result = runner.run_playwright_semantic_observation_check()

    assert result.status == "passed"
    assert calls and calls[0]["fixture_mode"] is True
    assert result.details["semantic_extraction_path"] == "screen_awareness.playwright_adapter"
    assert result.details["browser_context_kind"] == "isolated_playwright_context"
    assert result.details["control_count"] == 1
    assert result.details["forms_found"] == 1
    assert result.details["action_supported"] is False


def test_live_fixture_server_serves_deterministic_pages_on_loopback() -> None:
    with LiveBrowserFixtureServer() as server:
        assert server.host == "127.0.0.1"
        static = urlopen(server.url("/static.html"), timeout=2).read().decode("utf-8")
        redirect = urlopen(server.url("/redirect-safe"), timeout=2)

    assert "<title>Stormhelm Fixture Static</title>" in static
    assert "Continue" in static
    assert redirect.url.endswith("/static.html")


def test_live_enabled_adapter_contracts_remain_evidence_only(temp_config) -> None:
    gates = LiveBrowserIntegrationGates.from_env(
        {
            "STORMHELM_LIVE_BROWSER_TESTS": "true",
            "STORMHELM_ENABLE_LIVE_OBSCURA": "true",
            "STORMHELM_ENABLE_LIVE_OBSCURA_CDP": "true",
            "STORMHELM_ENABLE_LIVE_PLAYWRIGHT": "true",
            "STORMHELM_PLAYWRIGHT_ALLOW_BROWSER_LAUNCH": "true",
        }
    )
    apply_live_browser_profile(temp_config, gates)
    registry = default_adapter_contract_registry()
    forbidden = {
        "browser.input.click",
        "browser.input.type",
        "browser.input.scroll",
        "browser.form.fill",
        "browser.form.submit",
        "browser.login",
        "browser.cookies.read",
        "browser.cookies.write",
        "browser.visible_screen_verify",
        "browser.truth_verify",
    }

    cli = registry.get_contract("web_retrieval.obscura.cli")
    cdp = registry.get_contract("web_retrieval.obscura.cdp")
    playwright = registry.get_contract("screen_awareness.browser.playwright")
    declared = set(playwright.action_modes) | set(playwright.artifact_modes) | set(cdp.action_modes) | set(cdp.artifact_modes)

    assert cli.verification.max_claimable_outcome == ClaimOutcome.OBSERVED
    assert cdp.verification.max_claimable_outcome == ClaimOutcome.OBSERVED
    assert playwright.verification.max_claimable_outcome == ClaimOutcome.OBSERVED
    assert forbidden.isdisjoint(declared)


def test_route_boundaries_hold_with_live_profile_enabled(temp_config) -> None:
    gates = LiveBrowserIntegrationGates.from_env(
        {
            "STORMHELM_LIVE_BROWSER_TESTS": "true",
            "STORMHELM_ENABLE_LIVE_OBSCURA": "true",
            "STORMHELM_ENABLE_LIVE_OBSCURA_CDP": "true",
            "STORMHELM_ENABLE_LIVE_PLAYWRIGHT": "true",
        }
    )
    config = apply_live_browser_profile(temp_config, gates)
    planner = DeterministicPlanner(screen_awareness_config=config.screen_awareness, discord_relay_config=config.discord_relay)

    def winner(text: str) -> str:
        plan = planner.plan(
            text,
            session_id="live-browser-route-test",
            surface_mode="ghost",
            active_module="chartroom",
            workspace_context={},
            active_posture={},
            active_request_state={},
            active_context={},
            recent_tool_results=[],
        )
        return plan.route_state.to_dict()["winner"]["route_family"]

    assert winner("open YouTube") != "web_retrieval"
    assert winner("what am I looking at") == "screen_awareness"
    assert winner("click the Continue button") != "web_retrieval"
    assert winner("send this page to Baby") == "discord_relay"


def test_safety_blocks_still_apply_with_live_profile_enabled(temp_config) -> None:
    gates = LiveBrowserIntegrationGates.from_env(
        {
            "STORMHELM_LIVE_BROWSER_TESTS": "true",
            "STORMHELM_ENABLE_LIVE_OBSCURA": "true",
            "STORMHELM_ENABLE_LIVE_OBSCURA_CDP": "true",
        }
    )
    config = apply_live_browser_profile(temp_config, gates)

    assert validate_public_url("http://127.0.0.1:8765/static.html", config.web_retrieval).allowed is False
    assert validate_public_url("http://192.168.1.20/page", config.web_retrieval).allowed is False
    assert validate_public_url("https://user:pass@example.com", config.web_retrieval).allowed is False
    assert validate_public_url("file:///C:/Windows/win.ini", config.web_retrieval).allowed is False
    assert validate_public_url("https://example.com", config.web_retrieval).allowed is True


def test_container_status_exposes_live_enabled_provider_readiness(temp_config) -> None:
    gates = LiveBrowserIntegrationGates.from_env(
        {
            "STORMHELM_LIVE_BROWSER_TESTS": "true",
            "STORMHELM_ENABLE_LIVE_OBSCURA": "true",
            "STORMHELM_ENABLE_LIVE_OBSCURA_CDP": "true",
            "STORMHELM_ENABLE_LIVE_PLAYWRIGHT": "true",
            "STORMHELM_OBSCURA_BINARY": "stormhelm-obscura-missing-for-test",
        }
    )
    config = apply_live_browser_profile(temp_config, gates)
    container = build_container(config)

    status = container.status_snapshot_fast()

    assert status["web_retrieval"]["enabled"] is True
    assert status["web_retrieval"]["providers"]["obscura"]["status"] == "binary_missing"
    assert status["web_retrieval"]["obscura_cdp"]["enabled"] is True
    assert status["web_retrieval"]["obscura_cdp"]["claim_ceiling"] == "headless_cdp_page_evidence"
    assert status["screen_awareness"]["browser_adapters"]["playwright"]["playwright_adapter_enabled"] is True
    assert status["screen_awareness"]["browser_adapters"]["playwright"]["live_actions_enabled"] is False


def test_pytest_live_browser_markers_are_registered(pytestconfig) -> None:
    markers = "\n".join(pytestconfig.getini("markers"))

    assert "live_browser" in markers
    assert "live_obscura" in markers
    assert "live_obscura_cdp" in markers
    assert "live_playwright" in markers


def test_live_profile_example_and_script_preserve_disabled_actions() -> None:
    profile = Path("config/development-live-browser.toml.example").read_text(encoding="utf-8")
    script = Path("scripts/run_live_browser_checks.ps1").read_text(encoding="utf-8")
    module = Path("src/stormhelm/core/live_browser_integration.py").read_text(encoding="utf-8")
    adapter = Path("src/stormhelm/core/screen_awareness/browser_playwright.py").read_text(encoding="utf-8")

    assert "allow_actions = false" in profile
    assert "allow_click = false" in profile
    assert "allow_focus = false" in profile
    assert "allow_type_text = false" in profile
    assert "allow_scroll = false" in profile
    assert "allow_form_fill = false" in profile
    assert "allow_form_submit = false" in profile
    assert "allow_login = false" in profile
    assert "allow_cookies = false" in profile
    assert "allow_user_profile = false" in profile
    assert "allow_dev_actions = false" in profile
    assert "allow_input_domain = false" in profile
    assert "allow_runtime_eval = false" in profile
    assert "STORMHELM_LIVE_BROWSER_TESTS" in script
    assert "STORMHELM_PLAYWRIGHT_ALLOW_BROWSER_LAUNCH" in script
    assert "stormhelm.core.live_browser_integration" in script
    assert "observe_live_browser_page" in module
    assert "new_context(storage_state=None" in adapter
    assert "launch_persistent_context" not in adapter
    assert "clear_cookies()" in adapter


def test_dependency_setup_script_check_only_writes_report_without_installing(tmp_path) -> None:
    script_path = Path("scripts/setup_live_browser_dependencies.ps1")
    report_path = tmp_path / "dependencies.json"

    completed = subprocess.run(
        [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            "-CheckOnly",
            "-ReportPath",
            str(report_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["mode"] == "check_only"
    assert payload["install_requested"]["playwright_package"] is False
    assert payload["install_requested"]["playwright_chromium"] is False
    assert "python_available" in payload
    assert "obscura" in payload
    assert payload["install_requested"]["obscura"] is False
    assert payload["obscura"]["install_mode"] in {"existing_path", "skipped"}
    assert payload["obscura"]["added_to_path"] is False
    assert payload["obscura"]["stormhelm_obscura_binary_set"] is False
    assert "playwright" in payload


def test_dependency_setup_script_missing_obscura_zip_reports_typed_failure(tmp_path) -> None:
    script_path = Path("scripts/setup_live_browser_dependencies.ps1")
    report_path = tmp_path / "dependencies.json"
    install_dir = tmp_path / "obscura-install"

    completed = subprocess.run(
        [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            "-InstallObscura",
            "-ObscuraZipPath",
            str(tmp_path / "missing-obscura.zip"),
            "-ObscuraInstallDir",
            str(install_dir),
            "-ReportPath",
            str(report_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["install_requested"]["obscura"] is True
    assert payload["obscura"]["install_mode"] == "local_zip"
    assert payload["obscura"]["install_status"] == "failed"
    assert payload["obscura"]["error_code"] == "zip_missing"
    assert payload["obscura"]["binary_found"] is False


def test_dependency_setup_script_does_not_download_obscura_without_install_flag(tmp_path) -> None:
    script_path = Path("scripts/setup_live_browser_dependencies.ps1")
    report_path = tmp_path / "dependencies.json"

    completed = subprocess.run(
        [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            "-ObscuraReleaseUrl",
            "http://127.0.0.1:1/obscura.zip",
            "-ObscuraBinaryPath",
            str(tmp_path / "missing-obscura.exe"),
            "-ReportPath",
            str(report_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["install_requested"]["obscura"] is False
    assert payload["obscura"]["install_status"] == "not_found"
    assert payload["safety"]["no_obscura_download_without_install_flag"] is True


def test_dependency_setup_script_rejects_non_official_obscura_release_url(tmp_path) -> None:
    script_path = Path("scripts/setup_live_browser_dependencies.ps1")
    report_path = tmp_path / "dependencies.json"

    completed = subprocess.run(
        [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            "-InstallObscura",
            "-ObscuraReleaseUrl",
            "https://example.com/obscura-windows.zip",
            "-ObscuraInstallDir",
            str(tmp_path / "obscura-install"),
            "-ReportPath",
            str(report_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["obscura"]["install_mode"] == "release_url"
    assert payload["obscura"]["download_attempted"] is False
    assert payload["obscura"]["install_status"] == "failed"
    assert payload["obscura"]["error_code"] == "release_url_not_official"
    assert payload["obscura"]["obscura_release_repo"] == "h4ckf0r0day/obscura"


def test_dependency_setup_script_obscura_binary_override_reports_existing_path(tmp_path) -> None:
    script_path = Path("scripts/setup_live_browser_dependencies.ps1")
    report_path = tmp_path / "dependencies.json"
    binary_path = _fake_obscura_binary(tmp_path)

    completed = subprocess.run(
        [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            "-ObscuraBinaryPath",
            str(binary_path),
            "-ReportPath",
            str(report_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["obscura"]["install_mode"] == "existing_path"
    assert payload["obscura"]["install_status"] == "present"
    assert payload["obscura"]["binary_found"] is True
    assert Path(payload["obscura"]["obscura_binary_path"]) == binary_path
    assert payload["obscura"]["version_status"] == "supported"


def test_dependency_setup_script_obscura_unsupported_version_is_not_executable_failure(tmp_path) -> None:
    script_path = Path("scripts/setup_live_browser_dependencies.ps1")
    report_path = tmp_path / "dependencies.json"
    binary_path = tmp_path / "obscura.cmd"
    binary_path.write_text("@echo error: unexpected argument '--version' found 1>&2\r\nexit /b 2\r\n", encoding="utf-8")

    completed = subprocess.run(
        [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            "-ObscuraBinaryPath",
            str(binary_path),
            "-ReportPath",
            str(report_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["obscura"]["binary_found"] is True
    assert payload["obscura"]["version_status"] == "version_unknown"
    assert payload["obscura"]["binary_executable"] is True
    assert payload["obscura"]["error_code"] == ""


def test_dependency_setup_script_installs_obscura_from_local_zip_and_detects_binary(tmp_path) -> None:
    script_path = Path("scripts/setup_live_browser_dependencies.ps1")
    report_path = tmp_path / "dependencies.json"
    install_dir = tmp_path / "obscura-install"
    zip_path = _fake_obscura_zip(tmp_path)

    completed = subprocess.run(
        [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            "-InstallObscura",
            "-ObscuraZipPath",
            str(zip_path),
            "-ObscuraInstallDir",
            str(install_dir),
            "-ReportPath",
            str(report_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    binary_path = Path(payload["obscura"]["obscura_binary_path"])

    assert payload["obscura"]["install_mode"] == "local_zip"
    assert payload["obscura"]["install_status"] == "installed"
    assert payload["obscura"]["binary_found"] is True
    assert binary_path.exists()
    assert binary_path.name == "obscura.cmd"
    assert payload["obscura"]["version_status"] == "supported"
    assert "obscura fake 1.0" in payload["obscura"]["version_output_bounded"]
    assert payload["obscura"]["added_to_path"] is False
    assert payload["obscura"]["stormhelm_obscura_binary_set"] is False


def test_dependency_setup_script_requires_explicit_install_flags() -> None:
    script = Path("scripts/setup_live_browser_dependencies.ps1").read_text(encoding="utf-8")
    live_script = Path("scripts/run_live_browser_checks.ps1").read_text(encoding="utf-8")
    docs = Path("docs/live-browser-integration.md").read_text(encoding="utf-8")

    assert "InstallObscura" in script
    assert "DownloadLatestObscuraRelease" in script
    assert "ObscuraZipPath" in script
    assert "ObscuraReleaseUrl" in script
    assert "ObscuraReleaseTag" in script
    assert "ObscuraAssetName" in script
    assert "AddObscuraToUserPath" in script
    assert "SetStormhelmObscuraBinary" in script
    assert "h4ckf0r0day/obscura" in script
    assert '[Environment]::GetEnvironmentVariable("STORMHELM_OBSCURA_BINARY", "User")' in script
    assert '[Environment]::GetEnvironmentVariable("STORMHELM_OBSCURA_BINARY", "User")' in live_script
    assert "Invoke-WebRequest" in script
    assert "InstallPlaywrightPackage" in script
    assert "InstallPlaywrightChromium" in script
    assert "explicit_install" in script
    assert "python -m pip install playwright" not in script
    assert "-m pip install playwright" in script
    assert "-m playwright install chromium" in script
    assert "Download Obscura" not in script
    assert "setup_live_browser_dependencies.ps1" in docs
    assert "-InstallObscura" in docs
    assert "-DownloadLatestObscuraRelease" in docs
    assert "-ObscuraZipPath" in docs
    assert "-ObscuraReleaseUrl" in docs
    assert "-InstallPlaywrightPackage" in docs
    assert "-InstallPlaywrightChromium" in docs


def _fake_obscura_zip(tmp_path: Path) -> Path:
    zip_path = tmp_path / "obscura-windows.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("obscura/obscura.cmd", "@echo obscura fake 1.0\r\n")
    return zip_path


def _fake_obscura_binary(tmp_path: Path) -> Path:
    binary_path = tmp_path / "obscura.cmd"
    binary_path.write_text("@echo obscura fake 1.0\r\n", encoding="utf-8")
    return binary_path
