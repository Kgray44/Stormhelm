from __future__ import annotations

import json
from pathlib import Path

from stormhelm.config.models import AppConfig
from stormhelm.core.intelligence.language import fuzzy_ratio, normalize_lookup_phrase, normalize_phrase
from stormhelm.core.power.models import RoutineDefinition, TrustedHookDefinition


class PowerRegistryStore:
    def __init__(self, config: AppConfig) -> None:
        self.path = Path(config.storage.data_dir) / "power" / "registry.json"

    def list_routines(self) -> list[RoutineDefinition]:
        payload = self._load()
        return [RoutineDefinition.from_dict(item) for item in payload.get("routines", []) if isinstance(item, dict)]

    def save_routine(self, definition: RoutineDefinition) -> None:
        payload = self._load()
        routines = [item for item in payload.get("routines", []) if isinstance(item, dict)]
        key = self._normalize_key(definition.name)
        updated: list[dict[str, object]] = []
        replaced = False
        for item in routines:
            if self._normalize_key(str(item.get("name", ""))) == key:
                updated.append(definition.to_dict())
                replaced = True
            else:
                updated.append(item)
        if not replaced:
            updated.append(definition.to_dict())
        payload["routines"] = updated
        self._save(payload)

    def get_routine(self, name: str) -> RoutineDefinition | None:
        return self._resolve_definition(self.list_routines(), name)

    def list_hooks(self) -> list[TrustedHookDefinition]:
        payload = self._load()
        return [TrustedHookDefinition.from_dict(item) for item in payload.get("hooks", []) if isinstance(item, dict)]

    def save_hook(self, definition: TrustedHookDefinition) -> None:
        payload = self._load()
        hooks = [item for item in payload.get("hooks", []) if isinstance(item, dict)]
        key = self._normalize_key(definition.name)
        updated: list[dict[str, object]] = []
        replaced = False
        for item in hooks:
            if self._normalize_key(str(item.get("name", ""))) == key:
                updated.append(definition.to_dict())
                replaced = True
            else:
                updated.append(item)
        if not replaced:
            updated.append(definition.to_dict())
        payload["hooks"] = updated
        self._save(payload)

    def get_hook(self, name: str) -> TrustedHookDefinition | None:
        return self._resolve_definition(self.list_hooks(), name)

    def _resolve_definition(self, definitions: list[object], name: str):
        normalized = self._normalize_key(name)
        if not normalized:
            return None
        exact = next((item for item in definitions if self._normalize_key(getattr(item, "name", "")) == normalized), None)
        if exact is not None:
            return exact
        best = None
        best_score = 0.0
        for item in definitions:
            score = fuzzy_ratio(normalized, self._normalize_key(getattr(item, "name", "")))
            if score > best_score:
                best = item
                best_score = score
        if best is None or best_score < 0.86:
            return None
        return best

    def _load(self) -> dict[str, object]:
        if not self.path.exists():
            return {"routines": [], "hooks": []}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {"routines": [], "hooks": []}

    def _save(self, payload: dict[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def _normalize_key(self, value: str) -> str:
        return normalize_lookup_phrase(value) or normalize_phrase(value)
