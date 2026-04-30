from __future__ import annotations

import pytest

from stormhelm.config.loader import load_config


def test_load_config_defaults_web_retrieval_to_public_http_with_obscura_optional(temp_project_root) -> None:
    config = load_config(project_root=temp_project_root, env={})

    assert config.web_retrieval.enabled is True
    assert config.web_retrieval.planner_routing_enabled is True
    assert config.web_retrieval.debug_events_enabled is True
    assert config.web_retrieval.default_provider == "auto"
    assert config.web_retrieval.max_url_count == 8
    assert config.web_retrieval.max_url_chars == 4096
    assert config.web_retrieval.max_parallel_pages == 3
    assert config.web_retrieval.timeout_seconds == pytest.approx(12.0)
    assert config.web_retrieval.max_text_chars == 60000
    assert config.web_retrieval.max_html_chars == 250000
    assert config.web_retrieval.respect_robots is True
    assert config.web_retrieval.allow_private_network_urls is False
    assert config.web_retrieval.allow_file_urls is False
    assert config.web_retrieval.allow_logged_in_context is False

    assert config.web_retrieval.http.enabled is True
    assert config.web_retrieval.http.timeout_seconds == pytest.approx(8.0)
    assert config.web_retrieval.obscura.enabled is False
    assert config.web_retrieval.obscura.binary_path == "obscura"
    assert config.web_retrieval.obscura.allow_cdp_server is False
    assert config.web_retrieval.obscura.stealth_enabled is False
    assert config.web_retrieval.obscura.allow_js_eval is False
    assert config.web_retrieval.obscura.max_concurrency == 3
    assert config.web_retrieval.obscura.cdp.enabled is False
    assert config.web_retrieval.obscura.cdp.binary_path == "obscura"
    assert config.web_retrieval.obscura.cdp.host == "127.0.0.1"
    assert config.web_retrieval.obscura.cdp.port == 0
    assert config.web_retrieval.obscura.cdp.startup_timeout_seconds == pytest.approx(8.0)
    assert config.web_retrieval.obscura.cdp.shutdown_timeout_seconds == pytest.approx(4.0)
    assert config.web_retrieval.obscura.cdp.navigation_timeout_seconds == pytest.approx(12.0)
    assert config.web_retrieval.obscura.cdp.max_session_seconds == pytest.approx(120.0)
    assert config.web_retrieval.obscura.cdp.max_pages_per_session == 8
    assert config.web_retrieval.obscura.cdp.max_dom_text_chars == 60000
    assert config.web_retrieval.obscura.cdp.max_html_chars == 250000
    assert config.web_retrieval.obscura.cdp.max_links == 500
    assert config.web_retrieval.obscura.cdp.allow_runtime_eval is False
    assert config.web_retrieval.obscura.cdp.allow_input_domain is False
    assert config.web_retrieval.obscura.cdp.allow_cookies is False
    assert config.web_retrieval.obscura.cdp.allow_logged_in_context is False
    assert config.web_retrieval.obscura.cdp.allow_screenshots is False
    assert config.web_retrieval.obscura.cdp.debug_events_enabled is True
    assert config.web_retrieval.chromium.enabled is False
    assert config.web_retrieval.chromium.fallback_enabled is True


def test_load_config_applies_web_retrieval_environment_overrides(temp_project_root) -> None:
    config = load_config(
        project_root=temp_project_root,
        env={
            "STORMHELM_WEB_RETRIEVAL_ENABLED": "false",
            "STORMHELM_WEB_RETRIEVAL_DEFAULT_PROVIDER": "obscura",
            "STORMHELM_WEB_RETRIEVAL_MAX_URL_COUNT": "3",
            "STORMHELM_WEB_RETRIEVAL_MAX_URL_CHARS": "2048",
            "STORMHELM_WEB_RETRIEVAL_ALLOW_PRIVATE_NETWORK_URLS": "true",
            "STORMHELM_WEB_RETRIEVAL_HTTP_ENABLED": "false",
            "STORMHELM_OBSCURA_ENABLED": "true",
            "STORMHELM_OBSCURA_BINARY_PATH": "C:/Tools/obscura.exe",
            "STORMHELM_OBSCURA_MAX_CONCURRENCY": "2",
            "STORMHELM_OBSCURA_CDP_ENABLED": "true",
            "STORMHELM_OBSCURA_CDP_BINARY_PATH": "C:/Tools/obscura-cdp.exe",
            "STORMHELM_OBSCURA_CDP_PORT": "9444",
            "STORMHELM_OBSCURA_CDP_MAX_PAGES_PER_SESSION": "4",
        },
    )

    assert config.web_retrieval.enabled is False
    assert config.web_retrieval.default_provider == "obscura"
    assert config.web_retrieval.max_url_count == 3
    assert config.web_retrieval.max_url_chars == 2048
    assert config.web_retrieval.allow_private_network_urls is True
    assert config.web_retrieval.http.enabled is False
    assert config.web_retrieval.obscura.enabled is True
    assert config.web_retrieval.obscura.binary_path == "C:/Tools/obscura.exe"
    assert config.web_retrieval.obscura.max_concurrency == 2
    assert config.web_retrieval.obscura.cdp.enabled is True
    assert config.web_retrieval.obscura.cdp.binary_path == "C:/Tools/obscura-cdp.exe"
    assert config.web_retrieval.obscura.cdp.port == 9444
    assert config.web_retrieval.obscura.cdp.max_pages_per_session == 4
