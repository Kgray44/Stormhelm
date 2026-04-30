from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from stormhelm.config.loader import load_config
from stormhelm.core.web_retrieval.cdp import ObscuraCDPCompatibilityProbe
from stormhelm.core.web_retrieval.models import WebRetrievalRequest
from stormhelm.core.web_retrieval.safety import validate_public_url
from stormhelm.core.web_retrieval.service import WebRetrievalService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run an opt-in Obscura CDP compatibility probe.")
    parser.add_argument("--config", type=Path, default=None, help="Optional Stormhelm config override path.")
    parser.add_argument("--url", default="", help="Optional public URL to inspect after the compatibility probe.")
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON report path.")
    parser.add_argument("--require-compatible", action="store_true", help="Exit nonzero when compatibility is not ready or partial.")
    args = parser.parse_args(argv)

    app_config = load_config(config_path=args.config)
    cdp_config = app_config.web_retrieval.obscura.cdp
    report = ObscuraCDPCompatibilityProbe(cdp_config).run()
    payload: dict[str, Any] = report.to_dict()

    if args.url:
        safety = validate_public_url(args.url, app_config.web_retrieval)
        if not safety.allowed:
            payload["navigation_probe_status"] = "blocked"
            payload["extraction_probe_status"] = "not_run"
            payload["navigation_probe_error_code"] = safety.reason_code
        elif not report.compatible:
            payload["navigation_probe_status"] = "not_run"
            payload["extraction_probe_status"] = "not_run"
            payload["navigation_probe_error_code"] = "cdp_incompatible"
        else:
            request = WebRetrievalRequest(
                urls=[safety.normalized_url],
                intent="cdp_inspect",
                preferred_provider="obscura_cdp",
                include_links=True,
                include_html=False,
            )
            bundle = WebRetrievalService(app_config.web_retrieval).retrieve(request)
            page = bundle.pages[0] if bundle.pages else None
            payload["navigation_probe_status"] = str(getattr(page, "status", "") or bundle.result_state)
            payload["extraction_probe_status"] = bundle.result_state
            payload["inspection_summary"] = {
                "status": str(getattr(page, "status", "") or ""),
                "provider": str(getattr(page, "provider", "") or ""),
                "final_url": str(getattr(page, "final_url", "") or ""),
                "title_present": bool(getattr(page, "title", "") or ""),
                "dom_text_chars": int(getattr(page, "text_chars", 0) or 0),
                "links_found": int(getattr(page, "link_count", 0) or 0),
                "claim_ceiling": str(getattr(page, "claim_ceiling", "") or ""),
                "error_code": str(getattr(page, "error_code", "") or ""),
            }

    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    if args.require_compatible and payload.get("compatibility_level") not in {"ready", "partial"}:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
