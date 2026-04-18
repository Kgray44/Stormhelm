from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class RoutedCommand:
    tool_name: str | None
    arguments: dict[str, object] = field(default_factory=dict)
    fallback_message: str | None = None


class IntentRouter:
    def route(self, message: str) -> RoutedCommand:
        text = message.strip()
        lower = text.lower()
        if not text:
            return RoutedCommand(None, fallback_message="Send a message or use a command like /time or /system.")

        if lower.startswith("/time") or "what time" in lower or "what date" in lower:
            return RoutedCommand("clock")

        if lower.startswith("/system") or "system info" in lower:
            return RoutedCommand("system_info")

        if lower.startswith("/echo "):
            return RoutedCommand("echo", {"text": text[6:].strip()})

        if lower.startswith("/read "):
            return RoutedCommand("file_reader", {"path": text[6:].strip()})

        if lower.startswith("/note "):
            payload = text[6:].strip()
            if "|" in payload:
                title, content = [part.strip() for part in payload.split("|", 1)]
            else:
                title, content = "Quick Note", payload
            return RoutedCommand("notes_write", {"title": title or "Quick Note", "content": content})

        if lower.startswith("/shell "):
            return RoutedCommand("shell_command", {"command": text[7:].strip()})

        if "read file" in lower:
            path = text.partition("read file")[-1].strip(": ").strip()
            if path:
                return RoutedCommand("file_reader", {"path": path})

        return RoutedCommand(
            None,
            fallback_message=(
                "Phase 1 supports safe local commands. Try /time, /system, /echo <text>, "
                "/read <path>, /note <title> | <content>, or /shell <command>."
            ),
        )

