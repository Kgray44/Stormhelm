from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse


@dataclass(slots=True)
class ToolRequest:
    tool_name: str
    arguments: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class RoutedCommand:
    tool_calls: list[ToolRequest] = field(default_factory=list)
    assistant_message: str | None = None


class IntentRouter:
    def route(self, message: str, *, surface_mode: str = "ghost") -> RoutedCommand:
        text = message.strip()
        lower = text.lower()
        normalized_surface = surface_mode.strip().lower() if surface_mode else "ghost"
        if not text:
            return RoutedCommand(assistant_message="Send a message or use a command like /time or /system.")

        if lower.startswith("/time") or "what time" in lower or "what date" in lower:
            return RoutedCommand(tool_calls=[ToolRequest("clock")])

        if lower.startswith("/system") or "system info" in lower:
            return RoutedCommand(tool_calls=[ToolRequest("system_info")])

        if lower.startswith("/battery") or lower.startswith("/power"):
            return RoutedCommand(tool_calls=[ToolRequest("power_status")])

        if lower.startswith("/storage") or lower.startswith("/disk"):
            return RoutedCommand(tool_calls=[ToolRequest("storage_status")])

        if lower.startswith("/network") or lower.startswith("/wifi"):
            return RoutedCommand(tool_calls=[ToolRequest("network_status")])

        if lower.startswith("/apps") or lower.startswith("/windows"):
            return RoutedCommand(tool_calls=[ToolRequest("active_apps")])

        if lower.startswith("/recent"):
            return RoutedCommand(tool_calls=[ToolRequest("recent_files")])

        if lower.startswith("/echo "):
            return RoutedCommand(tool_calls=[ToolRequest("echo", {"text": text[6:].strip()})])

        if lower.startswith("/read "):
            return RoutedCommand(tool_calls=[ToolRequest("file_reader", {"path": text[6:].strip()})])

        if lower.startswith("/note "):
            payload = text[6:].strip()
            if "|" in payload:
                title, content = [part.strip() for part in payload.split("|", 1)]
            else:
                title, content = "Quick Note", payload
            return RoutedCommand(
                tool_calls=[ToolRequest("notes_write", {"title": title or "Quick Note", "content": content})]
            )

        if lower.startswith("/shell "):
            return RoutedCommand(tool_calls=[ToolRequest("shell_command", {"command": text[7:].strip()})])

        if lower.startswith("/open "):
            target = text[6:].strip()
            prefer_deck = normalized_surface == "deck"
            if target.lower().startswith("deck "):
                target = target[5:].strip()
                prefer_deck = True
            elif target.lower().startswith("external "):
                target = target[9:].strip()
                prefer_deck = False
            return self._route_open_target(target, prefer_deck=prefer_deck)

        if "read file" in lower:
            path = text.partition("read file")[-1].strip(": ").strip()
            if path:
                return RoutedCommand(tool_calls=[ToolRequest("file_reader", {"path": path})])

        if self._looks_like_url(text):
            return self._route_open_target(text, prefer_deck=normalized_surface == "deck")

        if self._looks_like_path(text):
            return self._route_open_target(text, prefer_deck=normalized_surface == "deck")

        if lower.startswith("/workspace "):
            payload = text[11:].strip()
            payload_lower = payload.lower()
            if payload_lower == "save" or payload_lower == "snapshot":
                return RoutedCommand(tool_calls=[ToolRequest("workspace_save", {"session_id": "default"})])
            if payload_lower == "clear":
                return RoutedCommand(tool_calls=[ToolRequest("workspace_clear", {"session_id": "default"})])
            if payload_lower == "archive":
                return RoutedCommand(tool_calls=[ToolRequest("workspace_archive", {"session_id": "default"})])
            if payload_lower == "recent":
                return RoutedCommand(
                    tool_calls=[ToolRequest("workspace_list", {"session_id": "default", "query": "", "archived_only": False})]
                )
            if payload_lower == "archived":
                return RoutedCommand(
                    tool_calls=[
                        ToolRequest(
                            "workspace_list",
                            {"session_id": "default", "query": "", "archived_only": True, "include_archived": True},
                        )
                    ]
                )
            if payload_lower == "leftoff":
                return RoutedCommand(tool_calls=[ToolRequest("workspace_where_left_off", {"session_id": "default"})])
            if payload_lower == "next":
                return RoutedCommand(tool_calls=[ToolRequest("workspace_next_steps", {"session_id": "default"})])
            if payload_lower.startswith("restore "):
                return RoutedCommand(
                    tool_calls=[ToolRequest("workspace_restore", {"query": payload[8:].strip(), "session_id": "default"})]
                )
            if payload_lower.startswith("rename "):
                return RoutedCommand(
                    tool_calls=[ToolRequest("workspace_rename", {"new_name": payload[7:].strip(), "session_id": "default"})]
                )
            if payload_lower.startswith("tag "):
                tags = [part.strip() for part in payload[4:].replace(",", " ").split() if part.strip()]
                return RoutedCommand(tool_calls=[ToolRequest("workspace_tag", {"tags": tags, "session_id": "default"})])

        if text.startswith("/"):
            return RoutedCommand(
                assistant_message=(
                    "Available direct commands: /time, /system, /echo <text>, /read <path>, "
                    "/battery, /storage, /network, /apps, /recent, /note <title> | <content>, "
                    "/open [deck|external] <url-or-path>, /workspace [save|clear|archive|recent|archived|leftoff|next|restore <query>|rename <name>|tag <tags>], "
                    "or /shell <command>."
                )
            )

        return RoutedCommand()

    def _route_open_target(self, target: str, *, prefer_deck: bool) -> RoutedCommand:
        if self._looks_like_url(target):
            tool_name = "deck_open_url" if prefer_deck else "external_open_url"
            return RoutedCommand(tool_calls=[ToolRequest(tool_name, {"url": target})])
        if self._looks_like_path(target):
            tool_name = "deck_open_file" if prefer_deck else "external_open_file"
            return RoutedCommand(tool_calls=[ToolRequest(tool_name, {"path": target})])
        return RoutedCommand(
            assistant_message="I can only open http/https URLs or existing local files from safe directories."
        )

    def _looks_like_url(self, value: str) -> bool:
        candidate = value.strip()
        if candidate.startswith("www."):
            return True
        parsed = urlparse(candidate)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    def _looks_like_path(self, value: str) -> bool:
        candidate = value.strip().strip('"')
        if not candidate or candidate.startswith(("http://", "https://", "www.")):
            return False
        try:
            return Path(candidate).expanduser().exists()
        except (OSError, RuntimeError):
            return False
