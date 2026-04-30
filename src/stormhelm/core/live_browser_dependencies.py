from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import re
from typing import Any, Mapping
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


OFFICIAL_OBSCURA_REPO = "h4ckf0r0day/obscura"
OFFICIAL_OBSCURA_API_LATEST = f"https://api.github.com/repos/{OFFICIAL_OBSCURA_REPO}/releases/latest"
OFFICIAL_OBSCURA_API_TAG = f"https://api.github.com/repos/{OFFICIAL_OBSCURA_REPO}/releases/tags"
_REPORT_LIMIT = 500


@dataclass(slots=True)
class ObscuraReleaseSelection:
    status: str
    obscura_release_repo: str = OFFICIAL_OBSCURA_REPO
    obscura_release_tag: str = ""
    obscura_release_name: str = ""
    obscura_asset_name: str = ""
    obscura_asset_url_redacted_or_bounded: str = ""
    checksum_status: str = "unavailable"
    checksum_asset_name: str = ""
    checksum_asset_url_redacted_or_bounded: str = ""
    matched_asset_names: list[str] | None = None
    error_code: str = ""
    bounded_error_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "obscura_release_repo": self.obscura_release_repo,
            "obscura_release_tag": self.obscura_release_tag,
            "obscura_release_name": self.obscura_release_name,
            "obscura_asset_name": self.obscura_asset_name,
            "obscura_asset_url_redacted_or_bounded": self.obscura_asset_url_redacted_or_bounded,
            "checksum_status": self.checksum_status,
            "checksum_asset_name": self.checksum_asset_name,
            "checksum_asset_url_redacted_or_bounded": self.checksum_asset_url_redacted_or_bounded,
            "matched_asset_names": list(self.matched_asset_names or []),
            "error_code": self.error_code,
            "bounded_error_message": self.bounded_error_message,
        }


def select_obscura_windows_asset(release_payload: Mapping[str, Any], *, asset_name: str = "") -> dict[str, Any]:
    release_tag = _bounded(release_payload.get("tag_name") or "")
    release_name = _bounded(release_payload.get("name") or "")
    raw_assets = release_payload.get("assets") or []
    assets = [asset for asset in raw_assets if isinstance(asset, Mapping)]
    checksum = _find_checksum_asset(assets)

    if asset_name:
        requested = str(asset_name).strip().lower()
        matches = [asset for asset in assets if str(asset.get("name") or "").strip().lower() == requested]
        if not matches:
            return ObscuraReleaseSelection(
                status="failed",
                obscura_release_tag=release_tag,
                obscura_release_name=release_name,
                checksum_status=_checksum_status(checksum),
                checksum_asset_name=_asset_name(checksum),
                checksum_asset_url_redacted_or_bounded=_asset_url(checksum),
                error_code="asset_name_missing",
                bounded_error_message=f"Requested Obscura release asset was not found: {_bounded(asset_name, 120)}",
            ).to_dict()
        return _selection(release_tag, release_name, matches[0], checksum, [asset_name])

    specific = [asset for asset in assets if _is_specific_windows_zip(_asset_name(asset))]
    if len(specific) > 1:
        return _multiple(release_tag, release_name, specific, checksum)
    if len(specific) == 1:
        return _selection(release_tag, release_name, specific[0], checksum, [_asset_name(specific[0])])

    generic = [asset for asset in assets if _is_generic_obscura_zip(_asset_name(asset))]
    if len(generic) > 1:
        return _multiple(release_tag, release_name, generic, checksum)
    if len(generic) == 1:
        return _selection(release_tag, release_name, generic[0], checksum, [_asset_name(generic[0])])

    return ObscuraReleaseSelection(
        status="failed",
        obscura_release_tag=release_tag,
        obscura_release_name=release_name,
        checksum_status=_checksum_status(checksum),
        checksum_asset_name=_asset_name(checksum),
        checksum_asset_url_redacted_or_bounded=_asset_url(checksum),
        error_code="windows_asset_missing",
        bounded_error_message="No Windows Obscura release zip asset matched the supported patterns.",
    ).to_dict()


def validate_obscura_release_url(url: str) -> dict[str, Any]:
    text = str(url or "").strip()
    parsed = urlparse(text)
    if parsed.scheme.lower() != "https":
        return {"allowed": False, "error_code": "release_url_not_https", "bounded_error_message": "Obscura release URL must use HTTPS."}
    if parsed.netloc.lower() != "github.com":
        return {"allowed": False, "error_code": "release_url_not_official", "bounded_error_message": "Obscura release URL must use the official github.com host."}
    expected_prefix = f"/{OFFICIAL_OBSCURA_REPO}/releases/download/"
    if not parsed.path.startswith(expected_prefix):
        return {"allowed": False, "error_code": "release_url_not_official", "bounded_error_message": "Obscura release URL must be from h4ckf0r0day/obscura GitHub Releases."}
    if not parsed.path.lower().endswith(".zip"):
        return {"allowed": False, "error_code": "release_url_not_zip", "bounded_error_message": "Obscura release URL must point to a zip asset."}
    return {"allowed": True, "error_code": "", "bounded_error_message": "", "url": _bounded(text)}


def discover_obscura_release(*, release_tag: str = "", asset_name: str = "", timeout_seconds: float = 12.0) -> dict[str, Any]:
    api_url = f"{OFFICIAL_OBSCURA_API_TAG}/{release_tag}" if release_tag else OFFICIAL_OBSCURA_API_LATEST
    try:
        request = Request(api_url, headers={"Accept": "application/vnd.github+json", "User-Agent": "Stormhelm-live-browser-diagnostics"})
        with urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError) as exc:
        return ObscuraReleaseSelection(
            status="failed",
            error_code="release_discovery_failed",
            bounded_error_message=_bounded(f"{type(exc).__name__}: {exc}"),
        ).to_dict()
    return select_obscura_windows_asset(payload, asset_name=asset_name)


def _selection(release_tag: str, release_name: str, asset: Mapping[str, Any], checksum: Mapping[str, Any] | None, names: list[str]) -> dict[str, Any]:
    return ObscuraReleaseSelection(
        status="selected",
        obscura_release_tag=release_tag,
        obscura_release_name=release_name,
        obscura_asset_name=_asset_name(asset),
        obscura_asset_url_redacted_or_bounded=_asset_url(asset),
        checksum_status=_checksum_status(checksum),
        checksum_asset_name=_asset_name(checksum),
        checksum_asset_url_redacted_or_bounded=_asset_url(checksum),
        matched_asset_names=names,
    ).to_dict()


def _multiple(release_tag: str, release_name: str, assets: list[Mapping[str, Any]], checksum: Mapping[str, Any] | None) -> dict[str, Any]:
    names = [_asset_name(asset) for asset in assets]
    return ObscuraReleaseSelection(
        status="failed",
        obscura_release_tag=release_tag,
        obscura_release_name=release_name,
        checksum_status=_checksum_status(checksum),
        checksum_asset_name=_asset_name(checksum),
        checksum_asset_url_redacted_or_bounded=_asset_url(checksum),
        matched_asset_names=names,
        error_code="multiple_assets_matched",
        bounded_error_message="Multiple Obscura Windows zip assets matched; pass -ObscuraAssetName to choose one explicitly.",
    ).to_dict()


def _asset_name(asset: Mapping[str, Any] | None) -> str:
    return _bounded((asset or {}).get("name") or "", 200)


def _asset_url(asset: Mapping[str, Any] | None) -> str:
    return _bounded((asset or {}).get("browser_download_url") or "", 500)


def _is_specific_windows_zip(name: str) -> bool:
    lower = name.lower()
    if not lower.endswith(".zip"):
        return False
    return (
        "windows" in lower
        or bool(re.search(r"(^|[-_.])win(64|32|dows)?($|[-_.])", lower))
        or ("x86_64" in lower and "pc" in lower and "windows" in lower)
    )


def _is_generic_obscura_zip(name: str) -> bool:
    lower = name.lower()
    non_windows_markers = ("linux", "darwin", "macos", "apple", "aarch64-unknown-linux", "x86_64-unknown-linux")
    return lower.endswith(".zip") and lower.startswith("obscura") and not any(marker in lower for marker in non_windows_markers)


def _find_checksum_asset(assets: list[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    for asset in assets:
        name = _asset_name(asset).lower()
        if "checksum" in name or "sha256" in name or name.endswith(".sha256") or name.endswith("sums.txt"):
            return asset
    return None


def _checksum_status(asset: Mapping[str, Any] | None) -> str:
    return "asset_available_not_verified" if asset else "unavailable"


def _bounded(value: Any, limit: int = _REPORT_LIMIT) -> str:
    text = str(value or "")
    text = re.sub(r"(?i)(token|password|api[_-]?key)=([^&\s]+)", r"\1=[redacted]", text)
    return text if len(text) <= limit else f"{text[: max(0, limit - 3)]}..."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Discover official Obscura release assets for Stormhelm diagnostics.")
    parser.add_argument("--release-tag", default="")
    parser.add_argument("--asset-name", default="")
    parser.add_argument("--release-url", default="")
    args = parser.parse_args(argv)

    if args.release_url:
        validation = validate_obscura_release_url(args.release_url)
        if not validation["allowed"]:
            payload = ObscuraReleaseSelection(
                status="failed",
                error_code=str(validation["error_code"]),
                bounded_error_message=str(validation["bounded_error_message"]),
            ).to_dict()
        else:
            asset_name = args.release_url.rsplit("/", 1)[-1]
            payload = ObscuraReleaseSelection(
                status="selected",
                obscura_asset_name=asset_name,
                obscura_asset_url_redacted_or_bounded=args.release_url,
                checksum_status="unavailable",
                matched_asset_names=[asset_name],
            ).to_dict()
    else:
        payload = discover_obscura_release(release_tag=args.release_tag, asset_name=args.asset_name)
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
