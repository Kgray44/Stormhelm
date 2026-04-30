from __future__ import annotations

from stormhelm.core.live_browser_dependencies import OFFICIAL_OBSCURA_REPO
from stormhelm.core.live_browser_dependencies import select_obscura_windows_asset
from stormhelm.core.live_browser_dependencies import validate_obscura_release_url


def test_obscura_release_selection_picks_single_windows_zip() -> None:
    report = select_obscura_windows_asset(
        {
            "tag_name": "v0.4.0",
            "name": "Obscura v0.4.0",
            "assets": [
                {
                    "name": "obscura-linux-x86_64.zip",
                    "browser_download_url": "https://github.com/h4ckf0r0day/obscura/releases/download/v0.4.0/obscura-linux-x86_64.zip",
                },
                {
                    "name": "obscura-x86_64-pc-windows-msvc.zip",
                    "browser_download_url": "https://github.com/h4ckf0r0day/obscura/releases/download/v0.4.0/obscura-x86_64-pc-windows-msvc.zip",
                },
                {
                    "name": "SHA256SUMS.txt",
                    "browser_download_url": "https://github.com/h4ckf0r0day/obscura/releases/download/v0.4.0/SHA256SUMS.txt",
                },
            ],
        }
    )

    assert report["status"] == "selected"
    assert report["obscura_release_repo"] == OFFICIAL_OBSCURA_REPO
    assert report["obscura_release_tag"] == "v0.4.0"
    assert report["obscura_asset_name"] == "obscura-x86_64-pc-windows-msvc.zip"
    assert report["checksum_status"] == "asset_available_not_verified"


def test_obscura_release_selection_reports_missing_windows_asset() -> None:
    report = select_obscura_windows_asset(
        {
            "tag_name": "v0.4.0",
            "assets": [
                {
                    "name": "obscura-linux-x86_64.zip",
                    "browser_download_url": "https://github.com/h4ckf0r0day/obscura/releases/download/v0.4.0/obscura-linux-x86_64.zip",
                }
            ],
        }
    )

    assert report["status"] == "failed"
    assert report["error_code"] == "windows_asset_missing"


def test_obscura_release_selection_reports_multiple_windows_assets_without_asset_name() -> None:
    report = select_obscura_windows_asset(
        {
            "tag_name": "v0.4.0",
            "assets": [
                {
                    "name": "obscura-windows-x86_64.zip",
                    "browser_download_url": "https://github.com/h4ckf0r0day/obscura/releases/download/v0.4.0/obscura-windows-x86_64.zip",
                },
                {
                    "name": "obscura-win64.zip",
                    "browser_download_url": "https://github.com/h4ckf0r0day/obscura/releases/download/v0.4.0/obscura-win64.zip",
                },
            ],
        }
    )

    assert report["status"] == "failed"
    assert report["error_code"] == "multiple_assets_matched"
    assert sorted(report["matched_asset_names"]) == ["obscura-win64.zip", "obscura-windows-x86_64.zip"]


def test_obscura_release_selection_asset_name_resolves_ambiguity() -> None:
    report = select_obscura_windows_asset(
        {
            "tag_name": "v0.4.0",
            "assets": [
                {
                    "name": "obscura-windows-x86_64.zip",
                    "browser_download_url": "https://github.com/h4ckf0r0day/obscura/releases/download/v0.4.0/obscura-windows-x86_64.zip",
                },
                {
                    "name": "obscura-win64.zip",
                    "browser_download_url": "https://github.com/h4ckf0r0day/obscura/releases/download/v0.4.0/obscura-win64.zip",
                },
            ],
        },
        asset_name="obscura-win64.zip",
    )

    assert report["status"] == "selected"
    assert report["obscura_asset_name"] == "obscura-win64.zip"


def test_obscura_release_url_validation_allows_only_official_https_assets() -> None:
    good = validate_obscura_release_url(
        "https://github.com/h4ckf0r0day/obscura/releases/download/v0.4.0/obscura-windows.zip"
    )
    bad_host = validate_obscura_release_url(
        "https://example.com/h4ckf0r0day/obscura/releases/download/v0.4.0/obscura-windows.zip"
    )
    bad_scheme = validate_obscura_release_url(
        "http://github.com/h4ckf0r0day/obscura/releases/download/v0.4.0/obscura-windows.zip"
    )

    assert good["allowed"] is True
    assert bad_host["allowed"] is False
    assert bad_host["error_code"] == "release_url_not_official"
    assert bad_scheme["allowed"] is False
    assert bad_scheme["error_code"] == "release_url_not_https"
