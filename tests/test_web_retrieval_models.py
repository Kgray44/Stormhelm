from __future__ import annotations

from stormhelm.core.web_retrieval.models import ExtractedLink
from stormhelm.core.web_retrieval.models import ObscuraCDPReadiness
from stormhelm.core.web_retrieval.models import RenderedWebPage
from stormhelm.core.web_retrieval.models import WebEvidenceBundle
from stormhelm.core.web_retrieval.models import WebRetrievalProviderCapability
from stormhelm.core.web_retrieval.models import WebRetrievalRequest
from stormhelm.core.web_retrieval.models import WebRetrievalTrace


def test_web_retrieval_models_serialize_claim_ceiling_and_limits() -> None:
    page = RenderedWebPage(
        requested_url="https://example.com",
        final_url="https://example.com/",
        provider="http",
        status="success",
        title="Example Domain",
        text="Example text",
        links=[ExtractedLink(url="https://example.com/about", text="About")],
        elapsed_ms=12.5,
        rendered_javascript=False,
        limitations=["static_http_only"],
    )
    trace = WebRetrievalTrace(
        request_id="web-test",
        selected_provider="http",
        attempted_providers=["http"],
        result_state="extracted",
        claim_ceiling="rendered_page_evidence",
    )
    bundle = WebEvidenceBundle(
        request=WebRetrievalRequest(urls=["https://example.com"], intent="summarize_page"),
        pages=[page],
        trace=trace,
        result_state="extracted",
    )

    payload = bundle.to_dict()

    assert payload["result_state"] == "extracted"
    assert payload["trace"]["claim_ceiling"] == "rendered_page_evidence"
    assert payload["pages"][0]["links"][0]["url"] == "https://example.com/about"
    assert payload["pages"][0]["limitations"] == ["static_http_only"]


def test_obscura_addition_one_capability_forbids_user_context_and_truth_verification() -> None:
    capability = WebRetrievalProviderCapability.obscura_cli()

    assert capability.can_render_javascript is True
    assert capability.can_eval_js is False
    assert capability.can_use_cookies is False
    assert capability.can_submit_forms is False
    assert capability.can_use_logged_in_context is False
    assert capability.can_verify_user_visible_screen is False
    assert capability.claim_ceiling == "rendered_page_evidence"


def test_obscura_cdp_capability_and_readiness_keep_headless_claim_ceiling() -> None:
    capability = WebRetrievalProviderCapability.obscura_cdp()
    readiness = ObscuraCDPReadiness(
        enabled=True,
        available=True,
        binary_path="obscura",
        host="127.0.0.1",
        configured_port=0,
        active_port=9444,
        server_running=True,
        cdp_endpoint_url="http://127.0.0.1:9444",
        browser_version="Obscura/1.0",
        protocol_version="1.3",
        status="active",
    )

    assert capability.provider == "obscura_cdp"
    assert capability.can_render_javascript is True
    assert capability.can_eval_js is False
    assert capability.can_click_or_type is False
    assert capability.can_use_cookies is False
    assert capability.can_use_logged_in_context is False
    assert capability.can_verify_user_visible_screen is False
    assert capability.claim_ceiling == "headless_cdp_page_evidence"
    assert "no_input_domain" in capability.limitations

    payload = readiness.to_dict()
    assert payload["status"] == "active"
    assert payload["server_running"] is True
    assert payload["claim_ceiling"] == "headless_cdp_page_evidence"
