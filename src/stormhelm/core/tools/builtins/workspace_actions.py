from __future__ import annotations

import mimetypes
from pathlib import Path
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
            },
            "required": ["url"],
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"url": _validate_http_url(str(arguments.get("url", "")))}

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        url = arguments["url"]
        parsed = urlparse(url)
        title = parsed.netloc or url
        return ToolResult(
            success=True,
            summary=f"Opened {title} in the Deck browser.",
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
            },
            "required": ["url"],
            "additionalProperties": False,
        }

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"url": _validate_external_url(str(arguments.get("url", "")))}

    def execute_sync(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        url = arguments["url"]
        parsed = urlparse(url)
        title = parsed.netloc or parsed.path or url
        return ToolResult(
            success=True,
            summary=f"Opened {title} externally.",
            data={
                "action": {
                    "type": "open_external",
                    "kind": "url",
                    "url": url,
                    "title": title,
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
