from __future__ import annotations

from typing import Any

from stormhelm.config.models import AppConfig


class PersonaContract:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def report(self, text: str) -> str:
        cleaned = self._clean(text)
        if not cleaned:
            return "Standing by."
        return cleaned

    def confirmation(self, text: str) -> str:
        return self.report(text)

    def error(self, text: str) -> str:
        detail = self._clean(text).rstrip(".")
        if not detail:
            detail = "the requested course could not be secured"
        return f"Stormhelm could not secure that course: {detail}."

    def workspace_restored(self, name: str, item_count: int, basis: str | None = None) -> str:
        detail = f"Restored {name} to the Deck and recovered {item_count} relevant item{'s' if item_count != 1 else ''}"
        if basis:
            detail = f"{detail} from {basis}"
        return self.report(f"{detail}.")

    def workspace_assembled(self, name: str, item_count: int, basis: str | None = None) -> str:
        detail = f"Assembled the {name} workspace and plotted {item_count} relevant item{'s' if item_count != 1 else ''}"
        if basis:
            detail = f"{detail} from {basis}"
        return self.report(f"{detail}.")

    def build_provider_instructions(
        self,
        *,
        role: str,
        surface_mode: str,
        active_module: str,
        workspace_context: dict[str, Any] | None = None,
    ) -> str:
        role_rules = {
            "planner": (
                "You are the fast Stormhelm planner. Decide whether deterministic tools, workspace memory, "
                "internal Deck opens, external opens, or a direct short reply are appropriate. Prefer "
                "deterministic local facts and specialized tools before model-only answers. Keep planning terse "
                "and operational."
            ),
            "reasoner": (
                "You are the deeper Stormhelm synthesis engine. Reconcile tool results, restore context, explain "
                "ambiguous situations, and keep the final answer calm, concise, and decisive. Do not expose raw "
                "tool dumps or hidden reasoning."
            ),
        }
        dynamic = [
            f"Current Stormhelm surface: {surface_mode.title()} Mode.",
            f"Current active Deck module: {active_module}.",
            "Ghost Mode is for quick orchestration, machine bearings, and external hand-offs.",
            "Deck Mode is for integrated work, internal viewing, workspace assembly, and sustained collaboration.",
            "Stormhelm persona is mandatory on every visible answer. Never sound like a generic assistant.",
            "Wrap system facts, tool summaries, restore notices, and errors in Stormhelm's calm command voice.",
        ]
        workspace_summary = self.describe_workspace_context(workspace_context)
        if workspace_summary:
            dynamic.append(workspace_summary)
        base = self.config.openai.instructions.strip()
        role_text = role_rules.get(role, role_rules["reasoner"])
        return "\n\n".join(part for part in [base, role_text, "\n".join(dynamic)] if part)

    def describe_workspace_context(self, workspace_context: dict[str, Any] | None) -> str:
        if not workspace_context:
            return ""
        workspace = workspace_context.get("workspace") if isinstance(workspace_context, dict) else None
        opened = workspace_context.get("opened_items", []) if isinstance(workspace_context, dict) else []
        active_item = workspace_context.get("active_item", {}) if isinstance(workspace_context, dict) else {}
        pieces: list[str] = []
        if isinstance(workspace, dict) and workspace.get("name"):
            pieces.append(f"Active workspace: {workspace.get('name')} ({workspace.get('topic', 'no topic')}).")
        if isinstance(active_item, dict) and active_item.get("title"):
            pieces.append(f"Active opened item: {active_item.get('title')}.")
        if isinstance(opened, list) and opened:
            titles = [str(item.get("title", "")).strip() for item in opened[:6] if isinstance(item, dict)]
            titles = [title for title in titles if title]
            if titles:
                pieces.append("Opened items in the current Deck: " + ", ".join(titles) + ".")
        return " ".join(pieces)

    def _clean(self, text: str) -> str:
        cleaned = " ".join(str(text or "").split())
        if not cleaned:
            return ""
        if cleaned[-1] not in ".!?":
            cleaned += "."
        return cleaned
