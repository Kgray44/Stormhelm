from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from typing import Any

from stormhelm.config.models import AppConfig


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
}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg"}
SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules", "dist", "build", ".runtime", "release"}
INTERNAL_PROJECT_DIRS = {"src", "tests", "assets", "config", "scripts"}
INTERNAL_PROJECT_TOKENS = {"stormhelm", "ghost", "deck", "chartroom", "qml", "scheduler", "orchestrator", "development", "dev"}


class WorkspaceIndexer:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def search_files(self, query: str, *, limit: int = 8) -> list[dict[str, Any]]:
        normalized_query = self._normalize(query)
        tokens = [token for token in normalized_query.split() if len(token) > 1]
        allow_internal_project_files = self._query_targets_internal_project(normalized_query)
        roots = [Path(path) for path in self.config.safety.allowed_read_dirs if Path(path).exists()]
        candidates: list[tuple[float, dict[str, Any]]] = []
        visited = 0
        for root in roots:
            for current_root, dirnames, filenames in os.walk(root):
                dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS and not name.startswith(".")]
                for filename in filenames:
                    visited += 1
                    if visited > 5000:
                        break
                    path = Path(current_root) / filename
                    try:
                        score, reason = self._score_path(
                            path,
                            tokens,
                            allow_internal_project_files=allow_internal_project_files,
                        )
                    except OSError:
                        continue
                    if score <= 0:
                        continue
                    try:
                        payload = self._build_item(path, reason=reason)
                    except OSError:
                        continue
                    candidates.append((score, payload))
                if visited > 5000:
                    break
            if visited > 5000:
                break
        candidates.sort(key=lambda item: item[0], reverse=True)
        unique: list[dict[str, Any]] = []
        seen: set[str] = set()
        for _, payload in candidates:
            key = str(payload.get("path") or payload.get("url") or payload.get("title"))
            if key in seen:
                continue
            seen.add(key)
            unique.append(payload)
            if len(unique) >= limit:
                break
        return unique

    def _score_path(
        self,
        path: Path,
        tokens: list[str],
        *,
        allow_internal_project_files: bool,
    ) -> tuple[float, str]:
        lowered_name = path.name.lower()
        lowered_parent = str(path.parent).lower()
        if not tokens:
            return 0.0, ""
        if not allow_internal_project_files and self._is_internal_project_path(path):
            return 0.0, ""
        score = 0.0
        matched_name_tokens: list[str] = []
        matched_parent_tokens: list[str] = []
        for token in tokens:
            if token in lowered_name:
                score += 6.0
                matched_name_tokens.append(token)
            if token in lowered_parent:
                score += 2.5
                matched_parent_tokens.append(token)
        if not matched_name_tokens and not matched_parent_tokens:
            return 0.0, ""
        if path.suffix.lower() in {".md", ".pdf", ".txt", ".py"}:
            score += 1.5
        reason = self._relevance_reason(path, matched_name_tokens, matched_parent_tokens)
        return score, reason

    def _build_item(self, path: Path, *, reason: str) -> dict[str, Any]:
        suffix = path.suffix.lower()
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        item: dict[str, Any] = {
            "title": path.name,
            "subtitle": str(path.parent),
            "path": str(path),
            "url": path.as_uri(),
            "mime_type": mime_type,
            "module": "files",
            "section": "opened-items",
            "summary": reason or f"Indexed from {path.parent.name or path.parent}",
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
            content = raw_bytes[: self.config.tools.max_file_read_bytes].decode("utf-8", errors="replace")
            item["kind"] = "markdown" if suffix in {".md", ".markdown"} else "text"
            item["viewer"] = item["kind"]
            item["content"] = content
            item["truncated"] = len(raw_bytes) > self.config.tools.max_file_read_bytes
            return item
        item["kind"] = "unsupported"
        item["viewer"] = "fallback"
        return item

    def _normalize(self, value: str) -> str:
        return " ".join(value.lower().replace("-", " ").replace("_", " ").split())

    def _query_targets_internal_project(self, normalized_query: str) -> bool:
        return any(token in normalized_query.split() for token in INTERNAL_PROJECT_TOKENS)

    def _is_internal_project_path(self, path: Path) -> bool:
        try:
            relative = path.resolve().relative_to(self.config.project_root.resolve())
        except ValueError:
            return False
        parts = [part.lower() for part in relative.parts]
        if not parts:
            return False
        if parts[0] in INTERNAL_PROJECT_DIRS:
            return True
        if len(parts) >= 2 and parts[0] == "src" and parts[1] == "stormhelm":
            return True
        return False

    def _relevance_reason(self, path: Path, matched_name_tokens: list[str], matched_parent_tokens: list[str]) -> str:
        if matched_name_tokens:
            token_text = ", ".join(dict.fromkeys(matched_name_tokens))
            return f"Matches the workspace topic in the file name ({token_text})."
        if matched_parent_tokens:
            token_text = ", ".join(dict.fromkeys(matched_parent_tokens))
            return f"Matches the workspace topic in the containing path ({token_text})."
        return f"Indexed from {path.parent.name or path.parent}"
