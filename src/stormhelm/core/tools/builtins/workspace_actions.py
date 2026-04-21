from __future__ import annotations

from dataclasses import dataclass
import mimetypes
import os
from pathlib import Path
import shutil
from typing import Any
from urllib.parse import urlparse

from stormhelm.core.tools.base import BaseTool, ToolContext
from stormhelm.shared.result import SafetyClassification, ToolResult


TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".py",
    ".json",
    ".toml",
    ".yaml",
    ".yml",
    ".ini",
    ".cfg",
    ".log",
    ".csv",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".html",
    ".css",
    ".xml",
    ".sql",
    ".ps1",
    ".bat",
    ".cmd",
    ".sh",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".rs",
    ".java",
    ".go",
}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg"}

BROWSER_TARGET_COMMANDS = {
    "edge": "msedge",
    "chrome": "chrome",
    "firefox": "firefox",
    "brave": "brave",
    "opera": "opera",
    "vivaldi": "vivaldi",
}

BROWSER_TARGET_TITLES = {
    "edge": "Microsoft Edge",
    "chrome": "Chrome",
    "firefox": "Firefox",
    "brave": "Brave",
    "opera": "Opera",
    "vivaldi": "Vivaldi",
}


@dataclass(frozen=True, slots=True)
class BrowserTargetProbeResult:
    requested_target: str
    resolved_target: str
    browser_title: str
    available: bool
    launch_command: str | None
    fallback_to_default: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested_target": self.requested_target,
            "resolved_target": self.resolved_target,
            "browser_title": self.browser_title,
            "available": self.available,
            "launch_command": self.launch_command,
            "fallback_to_default": self.fallback_to_default,
            "reason": self.reason,
        }


def _common_browser_install_paths(target: str) -> tuple[str, ...]:
    program_files = os.environ.get("ProgramFiles", "")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", "")
    local_app_data = os.environ.get("LocalAppData", "")

    candidates: dict[str, tuple[str, ...]] = {
        "edge": (
            str(Path(program_files_x86) / "Microsoft" / "Edge" / "Application" / "msedge.exe"),
            str(Path(program_files) / "Microsoft" / "Edge" / "Application" / "msedge.exe"),
        ),
        "chrome": (
            str(Path(program_files_x86) / "Google" / "Chrome" / "Application" / "chrome.exe"),
            str(Path(program_files) / "Google" / "Chrome" / "Application" / "chrome.exe"),
            str(Path(local_app_data) / "Google" / "Chrome" / "Application" / "chrome.exe"),
        ),
        "firefox": (
            str(Path(program_files) / "Mozilla Firefox" / "firefox.exe"),
            str(Path(program_files_x86) / "Mozilla Firefox" / "firefox.exe"),
        ),
        "brave": (
            str(Path(program_files_x86) / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe"),
            str(Path(program_files) / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe"),
        ),
        "opera": (
            str(Path(local_app_data) / "Programs" / "Opera" / "opera.exe"),
            str(Path(program_files_x86) / "Opera" / "launcher.exe"),
            str(Path(program_files) / "Opera" / "launcher.exe"),
        ),
        "vivaldi": (
            str(Path(local_app_data) / "Vivaldi" / "Application" / "vivaldi.exe"),
            str(Path(program_files_x86) / "Vivaldi" / "Application" / "vivaldi.exe"),
            str(Path(program_files) / "Vivaldi" / "Application" / "vivaldi.exe"),
        ),
    }
    return tuple(path for path in candidates.get(target, ()) if path and Path(path).exists())


def probe_browser_target(browser_target: str) -> BrowserTargetProbeResult:
    requested_target = str(browser_target or "").strip().lower()
    resolved_target = requested_target
    browser_title = BROWSER_TARGET_TITLES.get(resolved_target, requested_target.title() or "Browser")
    launcher = BROWSER_TARGET_COMMANDS.get(resolved_target)
    if not launcher:
        return BrowserTargetProbeResult(
            requested_target=requested_target,
            resolved_target=resolved_target,
            browser_title=browser_title,
            available=False,
            launch_command=None,
            fallback_to_default=True,
            reason="unknown_browser_target",
        )
    direct_launcher = shutil.which(launcher)
    if direct_launcher:
        return BrowserTargetProbeResult(
            requested_target=requested_target,
            resolved_target=resolved_target,
            browser_title=browser_title,
            available=True,
            launch_command=direct_launcher,
            fallback_to_default=False,
            reason="launcher_found_on_path",
        )
    install_candidates = _common_browser_install_paths(resolved_target)
    if install_candidates:
        return BrowserTargetProbeResult(
            requested_target=requested_target,
            resolved_target=resolved_target,
            browser_title=browser_title,
            available=True,
            launch_command=install_candidates[0],
            fallback_to_default=False,
            reason="launcher_found_in_common_install_path",
        )
    return BrowserTargetProbeResult(
        requested_target=requested_target,
        resolved_target=resolved_target,
        browser_title=browser_title,
        available=False,
        launch_command=None,
        fallback_to_default=True,
        reason="browser_not_available",
    )


def _fallback_response_contract_for_default_browser(
    *,
    title: str,
    browser_title: str,
    base_contract: dict[str, str] | None,
) -> dict[str, str]:
    bearing_title = str((base_contract or {}).get("bearing_title") or f"{title} opened").strip()
    return {
        "bearing_title": bearing_title,
        "micro_response": f"{browser_title} wasn't available, so I opened {title} in the default browser.",
        "full_response": f"Resolved {title}, couldn't use {browser_title} on this machine, and fell back to the default browser.",
    }


def _validate_http_url(raw_url: str) -> str:
    candidate = raw_url.strip()
    if not candidate:
        raise ValueError("A non-empty 'url' is required.")
    if candidate.startswith("www."):
        candidate = f"https://{candidate}"
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Only http and https URLs are supported.")
    return candidate


def _validate_external_url(raw_url: str) -> str:
    candidate = raw_url.strip()
    if not candidate:
        raise ValueError("A non-empty 'url' is required.")
    if candidate.startswith("www."):
        candidate = f"https://{candidate}"
    parsed = urlparse(candidate)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return candidate
    if parsed.scheme == "ms-settings":
        return candidate
    raise ValueError("Only http, https, and supported system settings URLs are allowed.")


def _validate_response_contract(raw_contract: object) -> dict[str, str] | None:
    if not isinstance(raw_contract, dict):
        return None
    bearing_title = str(raw_contract.get("bearing_title", "")).strip()
    micro_response = str(raw_contract.get("micro_response", "")).strip()
    full_response = str(raw_contract.get("full_response", "")).strip()
    if not any((bearing_title, micro_response, full_response)):
        return None
    return {
        "bearing_title": bearing_title,
        "micro_response": micro_response,
        "full_response": full_response,
    }


def _infer_file_item(path: Path, max_bytes: int) -> dict[str, Any]:
    suffix = path.suffix.lower()
    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    title = path.name
    url = path.as_uri()
    item: dict[str, Any] = {
        "title": title,
        "path": str(path),
        "url": url,
        "mime_type": mime_type,
        "extension": suffix,
    }

    if suffix == ".pdf":
        item["kind"] = "pdf"
        item["viewer"] = "pdf"
        return item

    if suffix in IMAGE_EXTENSIONS:
        item["kind"] = "image"
        item["viewer"] = "image"
        return item

    if suffix in TEXT_EXTENSIONS or mime_type.startswith("text/"):
        raw_bytes = path.read_bytes()
        truncated = len(raw_bytes) > max_bytes
        content = raw_bytes[:max_bytes].decode("utf-8", errors="replace")
        item["kind"] = "markdown" if suffix in {".md", ".markdown"} else "text"
        item["viewer"] = item["kind"]
        item["content"] = content
        item["truncated"] = truncated
        item["bytes_read"] = min(len(raw_bytes), max_bytes)
        return item

    item["kind"] = "unsupported"
    item["viewer"] = "fallback"
    return item


class DeckOpenUrlTool(BaseTool):
    name = "deck_open_url"
    display_name = "Deck Open URL"
    description = "Open a research or reference URL inside Stormhelm's Deck browser surface."
    category = "browser"
    classification = SafetyClassification.ACTION

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The http or https URL to open in the Deck."},
                "label": {"type": "string", "description": "Optional human-readable destination label."},
                "response_contract": {
                    "type": "object",
                    "properties": {
                        "bearing_title": {"type": "string"},
                        "micro_response": {"type": "string"},
                        "full_response": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            },
            "required": ["url"],
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "url": _validate_http_url(str(arguments.get("url", ""))),
            "label": str(arguments.get("label", "")).strip() or None,
            "response_contract": _validate_response_contract(arguments.get("response_contract")),
        }

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        url = arguments["url"]
        parsed = urlparse(url)
        title = str(arguments.get("label") or parsed.netloc or url).strip()
        response_contract = arguments.get("response_contract") if isinstance(arguments.get("response_contract"), dict) else None
        return ToolResult(
            success=True,
            summary=str(response_contract.get("full_response") if response_contract else "") or f"Opened {title} in the Deck browser.",
            data={
                "action": {
                    "type": "workspace_open",
                    "target": "deck",
                    "module": "browser",
                    "section": "open-pages",
                    "item": {
                        "kind": "browser",
                        "viewer": "browser",
                        "title": title,
                        "subtitle": url,
                        "url": url,
                    },
                    **(response_contract or {}),
                }
            },
        )


class ExternalOpenUrlTool(BaseTool):
    name = "external_open_url"
    display_name = "External Open URL"
    description = "Open a URL in the default external browser instead of inside Stormhelm."
    category = "browser"
    classification = SafetyClassification.ACTION

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The http or https URL to open externally."},
                "label": {"type": "string", "description": "Optional human-readable destination label."},
                "browser_target": {"type": "string", "description": "Optional explicit browser target such as chrome or firefox."},
                "response_contract": {
                    "type": "object",
                    "properties": {
                        "bearing_title": {"type": "string"},
                        "micro_response": {"type": "string"},
                        "full_response": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            },
            "required": ["url"],
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "url": _validate_external_url(str(arguments.get("url", ""))),
            "label": str(arguments.get("label", "")).strip() or None,
            "browser_target": str(arguments.get("browser_target", "")).strip().lower() or None,
            "response_contract": _validate_response_contract(arguments.get("response_contract")),
        }

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        url = arguments["url"]
        parsed = urlparse(url)
        title = str(arguments.get("label") or parsed.netloc or parsed.path or url).strip()
        response_contract = arguments.get("response_contract") if isinstance(arguments.get("response_contract"), dict) else None
        requested_browser_target = str(arguments.get("browser_target") or "").strip().lower()
        browser_target = requested_browser_target or None
        browser_command: str | None = None
        browser_probe: BrowserTargetProbeResult | None = None
        if requested_browser_target:
            browser_probe = probe_browser_target(requested_browser_target)
            if browser_probe.available:
                browser_target = browser_probe.resolved_target
                browser_command = browser_probe.launch_command
            else:
                browser_target = None
                response_contract = _fallback_response_contract_for_default_browser(
                    title=title,
                    browser_title=browser_probe.browser_title,
                    base_contract=response_contract,
                )
            context.events.publish(
                level="DEBUG",
                source="tool.external_open_url",
                message="Resolved external browser target.",
                payload={
                    "url": url,
                    "title": title,
                    "requested_browser_target": requested_browser_target,
                    "browser_target_probe": browser_probe.to_dict(),
                },
            )
        return ToolResult(
            success=True,
            summary=str(response_contract.get("full_response") if response_contract else "") or f"Opened {title} externally.",
            data={
                "action": {
                    "type": "open_external",
                    "kind": "url",
                    "url": url,
                    "title": title,
                    **({"browser_target": browser_target} if browser_target else {}),
                    **({"browser_command": browser_command} if browser_command else {}),
                    **({"browser_target_requested": requested_browser_target} if requested_browser_target else {}),
                    **({"browser_target_probe": browser_probe.to_dict()} if browser_probe is not None else {}),
                    **({"browser_fallback_to_default": True} if browser_probe is not None and browser_probe.fallback_to_default else {}),
                    **(response_contract or {}),
                }
            },
        )


class DeckOpenFileTool(BaseTool):
    name = "deck_open_file"
    display_name = "Deck Open File"
    description = "Open an allowlisted local file inside Stormhelm's Deck file viewer."
    category = "files"
    classification = SafetyClassification.ACTION

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute or relative path to an allowlisted local file."},
            },
            "required": ["path"],
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        path = str(arguments.get("path", "")).strip()
        if not path:
            raise ValueError("A non-empty 'path' is required.")
        return {"path": path}

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        decision = context.safety_policy.can_read_path(arguments["path"])
        if not decision.allowed:
            return ToolResult(
                success=False,
                summary="File open blocked by allowlist policy.",
                data={"decision": decision.to_dict()},
                error=decision.reason,
            )

        path = Path(arguments["path"]).expanduser().resolve()
        if not path.exists() or not path.is_file():
            return ToolResult(
                success=False,
                summary="File does not exist.",
                data={"path": str(path)},
                error="missing_file",
            )

        item = _infer_file_item(path, context.config.tools.max_file_read_bytes)
        return ToolResult(
            success=True,
            summary=f"Opened {path.name} in the Deck.",
            data={
                "action": {
                    "type": "workspace_open",
                    "target": "deck",
                    "module": "files",
                    "section": "opened-items",
                    "item": item,
                }
            },
        )


class ExternalOpenFileTool(BaseTool):
    name = "external_open_file"
    display_name = "External Open File"
    description = "Open an allowlisted local file with the default external application."
    category = "files"
    classification = SafetyClassification.ACTION

    def parameter_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute or relative path to an allowlisted local file."},
            },
            "required": ["path"],
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        path = str(arguments.get("path", "")).strip()
        if not path:
            raise ValueError("A non-empty 'path' is required.")
        return {"path": path}

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        decision = context.safety_policy.can_read_path(arguments["path"])
        if not decision.allowed:
            return ToolResult(
                success=False,
                summary="External file open blocked by allowlist policy.",
                data={"decision": decision.to_dict()},
                error=decision.reason,
            )

        path = Path(arguments["path"]).expanduser().resolve()
        if not path.exists() or not path.is_file():
            return ToolResult(
                success=False,
                summary="File does not exist.",
                data={"path": str(path)},
                error="missing_file",
            )

        return ToolResult(
            success=True,
            summary=f"Opened {path.name} externally.",
            data={
                "action": {
                    "type": "open_external",
                    "kind": "file",
                    "path": str(path),
                    "url": path.as_uri(),
                    "title": path.name,
                }
            },
        )
