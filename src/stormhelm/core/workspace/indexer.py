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


class WorkspaceIndexer:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def search_files(self, query: str, *, limit: int = 8) -> list[dict[str, Any]]:
        tokens = [token for token in self._normalize(query).split() if len(token) > 1]
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
                        score = self._score_path(path, tokens)
                    except OSError:
                        continue
                    if score <= 0:
                        continue
                    try:
                        payload = self._build_item(path)
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

    def _score_path(self, path: Path, tokens: list[str]) -> float:
        lowered_name = path.name.lower()
        lowered_parent = str(path.parent).lower()
        if not tokens:
            return 0.0
        score = 0.0
        for token in tokens:
            if token in lowered_name:
                score += 6.0
            if token in lowered_parent:
                score += 2.5
        if path.suffix.lower() in {".md", ".pdf", ".txt", ".py"}:
            score += 1.5
        return score

    def _build_item(self, path: Path) -> dict[str, Any]:
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
            "summary": f"Indexed from {path.parent.name or path.parent}",
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
