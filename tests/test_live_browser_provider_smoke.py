from __future__ import annotations

import os

import pytest

from stormhelm.core.live_browser_integration import LiveBrowserIntegrationGates
from stormhelm.core.live_browser_integration import LiveBrowserIntegrationRunner


pytestmark = [
    pytest.mark.live_browser,
    pytest.mark.skipif(
        str(os.environ.get("STORMHELM_LIVE_BROWSER_TESTS") or "").strip().lower()
        not in {"1", "true", "yes", "on"},
        reason="live browser provider checks require STORMHELM_LIVE_BROWSER_TESTS=true",
    ),
]


def test_live_browser_provider_checks_are_opt_in_and_evidence_only(temp_config) -> None:
    gates = LiveBrowserIntegrationGates.from_env()
    report = LiveBrowserIntegrationRunner(temp_config, gates=gates).run_all()
    payload = report.to_dict()

    assert payload["action_capabilities_disabled"] is True
    assert payload["claim_ceilings"]["obscura_cli"] == "rendered_page_evidence"
    assert payload["claim_ceilings"]["obscura_cdp"] == "headless_cdp_page_evidence"
    assert payload["claim_ceilings"]["playwright"] == "browser_semantic_observation"
    assert payload["raw_output_redacted"] is True
    for result in payload["results"].values():
        assert result["action_capabilities_disabled"] is True
        assert result["safety_gates_active"] is True
        assert result["status"] in {"passed", "skipped", "unavailable", "partial", "failed", "incompatible"}
