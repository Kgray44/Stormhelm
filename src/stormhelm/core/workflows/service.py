from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Any

from stormhelm.core.intelligence.language import fuzzy_ratio
from stormhelm.core.intelligence.language import normalize_lookup_phrase
from stormhelm.core.intelligence.language import normalize_phrase
from stormhelm.core.intelligence.language import token_overlap
from stormhelm.core.orchestrator.persona import PersonaContract
from stormhelm.core.tools.base import ToolContext
from stormhelm.core.workflows.models import (
    AccessFailureReason,
    ActionChain,
    FileResolutionDecision,
    FileSearchScope,
    FolderAccessStatus,
    FuzzyFileCandidate,
    FuzzyMatchScore,
    KnownFolderResolution,
    SearchResult,
    SearchWithinFolderPlan,
    WorkflowStep,
)
from stormhelm.shared.result import ToolResult


CAD_EXTENSIONS = {".dwg", ".dxf", ".step", ".stp", ".sldprt", ".sldasm", ".ipt", ".iam"}
NOTE_EXTENSIONS = {".md", ".markdown", ".txt"}
FILE_QUERY_STOP_WORDS = {
    "a",
    "an",
    "and",
    "file",
    "files",
    "find",
    "folder",
    "folders",
    "for",
    "from",
    "in",
    "inside",
    "it",
    "latest",
    "locate",
    "most",
    "my",
    "open",
    "recent",
    "search",
    "show",
    "the",
    "this",
    "that",
    "up",
    "within",
}
SEMANTIC_TOKEN_MAP = {
    "doc": "docs",
    "docs": "docs",
    "document": "docs",
    "documents": "docs",
    "documentation": "docs",
    "manual": "docs",
    "readme": "docs",
    "guide": "docs",
    "guides": "docs",
    "note": "notes",
    "notes": "notes",
    "notebook": "notes",
    "journal": "notes",
    "screenshot": "screenshots",
    "screenshots": "screenshots",
    "screen": "screenshots",
    "picture": "images",
    "pictures": "images",
    "photo": "images",
    "photos": "images",
    "image": "images",
    "images": "images",
    "report": "report",
    "reports": "report",
}
KEYWORD_FAMILIES: dict[str, set[str]] = {
    "docs": {"docs", "document", "documentation", "manual", "readme", "guide"},
    "notes": {"note", "notes", "notebook", "journal"},
    "screenshots": {"screenshot", "screenshots", "screen"},
    "images": {"picture", "pictures", "photo", "photos", "image", "images"},
    "report": {"report", "reports"},
}
KNOWN_FOLDER_SPECS: dict[str, dict[str, Any]] = {
    "documents": {"label": "Documents", "aliases": ("documents", "my documents", "documents folder", "the documents folder")},
    "downloads": {"label": "Downloads", "aliases": ("downloads", "my downloads", "downloads folder", "the downloads folder")},
    "desktop": {"label": "Desktop", "aliases": ("desktop", "my desktop", "desktop folder", "the desktop folder")},
    "pictures": {"label": "Pictures", "aliases": ("pictures", "my pictures", "pictures folder", "the pictures folder")},
    "music": {"label": "Music", "aliases": ("music", "my music", "music folder", "the music folder")},
    "videos": {"label": "Videos", "aliases": ("videos", "my videos", "videos folder", "the videos folder")},
}


class WorkflowPowerService:
    def __init__(self, context: ToolContext) -> None:
        self.context = context
        self.persona = PersonaContract(context.config)

    def desktop_search(
        self,
        *,
        query: str,
        domains: list[str] | None,
        action: str,
        open_target: str,
        latest_only: bool,
        file_extensions: list[str] | None,
        folder_hint: str | None,
        prefer_folders: bool,
        session_id: str,
        limit: int = 8,
    ) -> ToolResult:
        del session_id
        capabilities = self._search_capabilities()
        requested_domains = [str(domain).strip().lower() for domain in (domains or ["files", "apps", "windows"]) if str(domain).strip()]
        if "files" in requested_domains and str(folder_hint or "").strip():
            return self._desktop_search_within_folder(
                query=query,
                folder_hint=str(folder_hint or "").strip(),
                action=action,
                open_target=open_target,
                latest_only=latest_only,
                file_extensions=file_extensions or [],
                prefer_folders=prefer_folders,
                capabilities=capabilities,
            )
        allowed_domains = [domain for domain in requested_domains if capabilities.get(domain, False)]
        if not allowed_domains:
            return ToolResult(
                success=False,
                summary="Search authority is not available for those targets here.",
                data={"search": {"results": [], "capabilities": capabilities}},
                error="unsupported_search_domains",
            )
        results = self._search_results(
            query=query,
            domains=allowed_domains,
            latest_only=latest_only,
            file_extensions=file_extensions or [],
            limit=limit,
        )
        if not results:
            return ToolResult(
                success=False,
                summary="No strong match found.",
                data={"search": {"results": [], "capabilities": capabilities}},
                error="no_search_results",
            )
        actions: list[dict[str, Any]] = []
        summary = f"Found {results[0].title}."
        if action == "open":
            open_action = self._action_for_search_result(results[0], open_target=open_target)
            if open_action is not None:
                actions.append(open_action)
                summary = f"Opened {results[0].title}."
            elif results[0].domain in {"apps", "windows"}:
                probe = self.context.system_probe
                if probe is not None:
                    target_name = str(results[0].target.get("app_name") or results[0].title).strip()
                    if results[0].domain == "apps" and hasattr(probe, "app_control"):
                        focused = probe.app_control(action="focus", app_name=target_name)
                        if bool(focused.get("success")):
                            summary = f"Focused {results[0].title}."
                    elif results[0].domain == "windows" and hasattr(probe, "window_control"):
                        focused = probe.window_control(action="focus", app_name=target_name, target_mode="app")
                        if bool(focused.get("success")):
                            summary = f"Focused {results[0].title}."
            elif open_target == "external" and results[0].domain == "files":
                summary = f"Opened {results[0].title}."
        return ToolResult(
            success=True,
            summary=summary,
            data={
                "search": {
                    "query": query,
                    "domains": allowed_domains,
                    "results": [result.to_dict() for result in results],
                    "capabilities": capabilities,
                },
                "actions": actions,
            },
        )

    def _desktop_search_within_folder(
        self,
        *,
        query: str,
        folder_hint: str,
        action: str,
        open_target: str,
        latest_only: bool,
        file_extensions: list[str],
        prefer_folders: bool,
        capabilities: dict[str, Any],
    ) -> ToolResult:
        resolution = self._resolve_known_folder(folder_hint)
        if resolution is None:
            access_status = FolderAccessStatus(
                state="unresolved_folder",
                path=None,
                allowed=False,
                reason="I couldn't resolve that folder name.",
                failure_reason=AccessFailureReason.UNRESOLVED_FOLDER.value,
            )
            decision = FileResolutionDecision(
                state="unresolved_folder",
                clarification_required=False,
                failure_reason=AccessFailureReason.UNRESOLVED_FOLDER.value,
            )
            plan = SearchWithinFolderPlan(known_folder=None, access_status=access_status, scope=None, decision=decision)
            action_contract = self._response_contract(
                bearing_title="Folder unresolved",
                micro_response="Couldn't resolve that folder.",
                full_response=access_status.reason,
            )
            self._emit_folder_search_debug("Folder hint could not be resolved.", plan.to_dict())
            return ToolResult(
                success=False,
                summary=access_status.reason,
                data={"search": {**plan.to_dict(), "capabilities": capabilities}, "action": action_contract},
                error=AccessFailureReason.UNRESOLVED_FOLDER.value,
            )

        access_status = self._known_folder_access_status(resolution)
        if access_status.state != "resolved_and_accessible":
            decision = FileResolutionDecision(
                state=access_status.state,
                clarification_required=False,
                failure_reason=access_status.failure_reason,
            )
            plan = SearchWithinFolderPlan(known_folder=resolution, access_status=access_status, scope=None, decision=decision)
            action_contract = self._response_contract(
                bearing_title=f"{resolution.label} inaccessible",
                micro_response=f"{resolution.label} isn't accessible here.",
                full_response=access_status.reason,
            )
            self._emit_folder_search_debug("Resolved folder is outside current read scope.", plan.to_dict())
            return ToolResult(
                success=False,
                summary=access_status.reason,
                data={"search": {**plan.to_dict(), "capabilities": capabilities}, "action": action_contract},
                error=access_status.failure_reason or AccessFailureReason.FOLDER_INACCESSIBLE.value,
            )

        cleaned_query = self._clean_folder_query(query, folder_hint)
        scope = FileSearchScope(
            root_path=str(Path(resolution.path or "").resolve()),
            query=cleaned_query,
            folder_hint=resolution.label,
            prefer_folders=prefer_folders,
            latest_only=latest_only,
            requested_extensions=sorted({self._normalize_extension(value) for value in file_extensions if self._normalize_extension(value)}),
        )
        candidates = self._search_within_folder(scope)
        decision = self._decide_folder_candidates(candidates, prefer_folders=prefer_folders)
        plan = SearchWithinFolderPlan(known_folder=resolution, access_status=access_status, scope=scope, decision=decision)

        if decision.state == "accessible_single_strong_match" and decision.chosen_candidate is not None:
            actions: list[dict[str, Any]] = []
            if action == "open":
                open_action = self._action_for_fuzzy_candidate(decision.chosen_candidate, open_target=open_target)
                if open_action is not None:
                    actions.append(open_action)
            query_label = self._display_folder_query(cleaned_query, fallback=decision.chosen_candidate.title)
            full_response = (
                f"Resolved {resolution.label}, found the strongest match for {query_label}, and opened it."
                if action == "open"
                else f"Resolved {resolution.label} and found the strongest match for {query_label}."
            )
            action_contract = self._response_contract(
                bearing_title=f"{query_label} opened" if action == "open" else f"{query_label} found",
                micro_response=f"Opened the best match in {resolution.label}." if action == "open" else f"Found the best match in {resolution.label}.",
                full_response=full_response,
            )
            self._emit_folder_search_debug("Folder search resolved a single strong match.", plan.to_dict())
            return ToolResult(
                success=True,
                summary=full_response,
                data={"search": {**plan.to_dict(), "capabilities": capabilities}, "action": action_contract, "actions": actions},
            )

        if decision.state == "accessible_multiple_strong_matches":
            candidate_names = [candidate.title for candidate in decision.candidates[:3]]
            joined = " and ".join(candidate_names[:2]) if len(candidate_names) >= 2 else ", ".join(candidate_names)
            full_response = f"I found multiple strong matches in {resolution.label}: {joined}. Which one?"
            action_contract = self._response_contract(
                bearing_title="Need file clarified",
                micro_response="Found multiple likely matches.",
                full_response=full_response,
            )
            self._emit_folder_search_debug("Folder search requires clarification.", plan.to_dict())
            return ToolResult(
                success=False,
                summary=full_response,
                data={"search": {**plan.to_dict(), "capabilities": capabilities}, "action": action_contract},
                error=AccessFailureReason.MULTIPLE_STRONG_MATCHES.value,
            )

        query_label = self._display_folder_query(cleaned_query, fallback="that request")
        full_response = f"I searched {resolution.label} but found no strong match for {query_label}."
        action_contract = self._response_contract(
            bearing_title="No strong match",
            micro_response=f"No strong {query_label} match found.",
            full_response=full_response,
        )
        self._emit_folder_search_debug("Folder search found no strong match.", plan.to_dict())
        return ToolResult(
            success=False,
            summary=full_response,
            data={"search": {**plan.to_dict(), "capabilities": capabilities}, "action": action_contract},
            error=AccessFailureReason.NO_STRONG_MATCH.value,
        )

    def _resolve_known_folder(self, folder_hint: str) -> KnownFolderResolution | None:
        raw_hint = str(folder_hint or "").strip()
        if not raw_hint:
            return None
        if any(token in raw_hint for token in ("\\", "/", ":")):
            candidate_path = Path(raw_hint).expanduser()
            if candidate_path.exists():
                resolved_path = candidate_path.resolve()
                return KnownFolderResolution(
                    requested=raw_hint,
                    key="path",
                    label=resolved_path.name or raw_hint,
                    path=str(resolved_path),
                    source="path",
                    aliases=[raw_hint],
                )

        normalized = normalize_lookup_phrase(raw_hint) or normalize_phrase(raw_hint)
        for key, spec in KNOWN_FOLDER_SPECS.items():
            aliases = [normalize_phrase(alias) for alias in spec.get("aliases", ())]
            if normalized not in aliases and normalized != key:
                continue
            label = str(spec.get("label") or raw_hint).strip() or raw_hint
            candidates = self._known_folder_candidate_paths(label)
            chosen = next((path for path in candidates if path.exists()), candidates[0] if candidates else None)
            return KnownFolderResolution(
                requested=raw_hint,
                key=key,
                label=label,
                path=str(chosen.resolve()) if chosen is not None else None,
                source="known_folder",
                aliases=[str(alias) for alias in spec.get("aliases", ())],
            )
        return None

    def _known_folder_candidate_paths(self, label: str) -> list[Path]:
        home = Path.home()
        candidates: list[Path] = [home / label]
        one_drive_raw = os.getenv("OneDrive") or os.getenv("OneDriveConsumer")
        if one_drive_raw:
            candidates.append(Path(one_drive_raw) / label)
        else:
            candidates.append(home / "OneDrive" / label)
        deduped: list[Path] = []
        seen: set[str] = set()
        for candidate in candidates:
            key = str(candidate).lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(candidate)
        return deduped

    def _known_folder_access_status(self, resolution: KnownFolderResolution) -> FolderAccessStatus:
        path = Path(resolution.path or "").expanduser() if resolution.path else None
        if path is None or not path.exists():
            return FolderAccessStatus(
                state="resolved_but_inaccessible",
                path=str(path) if path is not None else None,
                allowed=False,
                reason=f"{resolution.label} isn't accessible from the current execution scope.",
                failure_reason=AccessFailureReason.FOLDER_INACCESSIBLE.value,
            )
        decision = self.context.safety_policy.can_read_path(str(path))
        if not decision.allowed or not self._has_explicit_known_folder_scope(path.resolve(), resolution):
            return FolderAccessStatus(
                state="resolved_but_inaccessible",
                path=str(path.resolve()),
                allowed=False,
                reason=f"{resolution.label} isn't accessible from the current execution scope.",
                failure_reason=AccessFailureReason.FOLDER_INACCESSIBLE.value,
            )
        return FolderAccessStatus(
            state="resolved_and_accessible",
            path=str(path.resolve()),
            allowed=True,
            reason=f"{resolution.label} is accessible.",
        )

    def _has_explicit_known_folder_scope(self, path: Path, resolution: KnownFolderResolution) -> bool:
        home = Path.home().resolve()
        project_root = self.context.config.project_root.resolve()
        label_key = resolution.label.lower()
        for allowed_dir in self.context.config.safety.allowed_read_dirs:
            base = allowed_dir.resolve()
            if base == project_root:
                continue
            if not path.is_relative_to(base):
                continue
            base_name = base.name.lower()
            if base == path or base == home or home.is_relative_to(base):
                return True
            if base_name in {label_key, "onedrive"}:
                return True
        return False

    def _clean_folder_query(self, query: str, folder_hint: str) -> str:
        cleaned = str(query or "").strip()
        if not cleaned:
            return ""
        cleaned = re.sub(
            rf"\s+(?:in|inside|within|from|under|at)\s+(?:my\s+|the\s+)?{re.escape(folder_hint)}(?:\s+folder)?\b",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"^(?:open|show|find|search|locate|pull up|bring up)\s+", "", cleaned, flags=re.IGNORECASE)
        return " ".join(cleaned.split()).strip(" .")

    def _display_folder_query(self, query: str, *, fallback: str) -> str:
        cleaned = " ".join(str(query or "").split()).strip(" .")
        return cleaned or fallback

    def _search_within_folder(self, scope: FileSearchScope) -> list[FuzzyFileCandidate]:
        root = Path(scope.root_path)
        entries = self._iter_folder_entries(root, max_depth=scope.max_depth, max_entries=scope.max_entries)
        candidates: list[FuzzyFileCandidate] = []
        query_tokens = self._canonical_file_tokens(scope.query)
        for entry in entries:
            candidate = self._score_folder_candidate(
                entry,
                query=scope.query,
                query_tokens=query_tokens,
                requested_extensions=set(scope.requested_extensions),
                prefer_folders=scope.prefer_folders,
                latest_only=scope.latest_only,
            )
            if candidate is not None:
                candidates.append(candidate)
        return sorted(candidates, key=lambda item: item.score.total, reverse=True)[:8]

    def _iter_folder_entries(self, root: Path, *, max_depth: int, max_entries: int) -> list[Path]:
        entries: list[Path] = []
        frontier: list[tuple[Path, int]] = [(root, 0)]
        while frontier and len(entries) < max_entries:
            current, depth = frontier.pop(0)
            if depth >= max_depth:
                continue
            try:
                children = sorted(current.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
            except OSError:
                continue
            for child in children:
                entries.append(child)
                if len(entries) >= max_entries:
                    break
                if child.is_dir():
                    frontier.append((child, depth + 1))
        return entries

    def _score_folder_candidate(
        self,
        path: Path,
        *,
        query: str,
        query_tokens: set[str],
        requested_extensions: set[str],
        prefer_folders: bool,
        latest_only: bool,
    ) -> FuzzyFileCandidate | None:
        is_dir = path.is_dir()
        extension = "" if is_dir else self._normalize_extension(path.suffix)
        if requested_extensions and extension and extension not in requested_extensions:
            return None
        display_name = path.name
        candidate_name = display_name if is_dir else path.stem
        normalized_name = normalize_lookup_phrase(candidate_name) or normalize_phrase(candidate_name)
        normalized_query = normalize_lookup_phrase(query) or normalize_phrase(query)
        candidate_tokens = self._canonical_file_tokens(f"{candidate_name} {extension.lstrip('.')}")
        coverage = self._coverage(query_tokens, candidate_tokens)
        overlap = self._overlap(query_tokens, candidate_tokens)
        phrase = 1.0 if normalized_query and normalized_query in normalized_name else 0.0
        fuzzy = max(
            fuzzy_ratio(normalized_query, normalized_name) if normalized_query else 0.0,
            fuzzy_ratio(normalized_query, normalize_lookup_phrase(display_name)) if normalized_query else 0.0,
            token_overlap(normalized_query, normalized_name) if normalized_query else 0.0,
        )
        keyword_bonus = self._keyword_bonus(query_tokens, normalized_name)
        type_bonus = self._type_bonus(query_tokens, extension, requested_extensions=requested_extensions)
        folder_bonus = 0.16 if prefer_folders and is_dir else (-0.04 if prefer_folders and not is_dir else 0.0)
        recency_bonus = self._recency_bonus(path) if latest_only else 0.0
        total = (0.38 * coverage) + (0.24 * overlap) + (0.22 * fuzzy) + (0.12 * phrase) + keyword_bonus + type_bonus + folder_bonus + recency_bonus
        if total < 0.3:
            return None
        reasons: list[str] = []
        if phrase >= 1.0:
            reasons.append("Exact phrase match")
        if coverage >= 0.99:
            reasons.append("Covered the full query")
        elif overlap >= 0.5:
            reasons.append("Strong token overlap")
        if keyword_bonus > 0:
            reasons.append("Matched likely document keywords")
        if type_bonus > 0:
            reasons.append("Matched the requested file type")
        if folder_bonus > 0:
            reasons.append("Preferred a folder match for this request")
        if latest_only and recency_bonus > 0:
            reasons.append("Favored the latest matching item")
        score = FuzzyMatchScore(
            total=total,
            phrase=phrase,
            coverage=coverage,
            overlap=overlap,
            fuzzy=fuzzy,
            keyword_bonus=keyword_bonus,
            type_bonus=type_bonus,
            folder_bonus=folder_bonus,
            recency_bonus=recency_bonus,
        )
        return FuzzyFileCandidate(
            title=display_name,
            path=str(path.resolve()),
            is_dir=is_dir,
            score=score,
            reasons=reasons,
            extension=extension,
            metadata={"modified_at": self._modified_at(path)},
        )

    def _decide_folder_candidates(self, candidates: list[FuzzyFileCandidate], *, prefer_folders: bool) -> FileResolutionDecision:
        if not candidates:
            return FileResolutionDecision(
                state="accessible_no_strong_match",
                candidates=[],
                clarification_required=False,
                failure_reason=AccessFailureReason.NO_STRONG_MATCH.value,
            )
        ranked = sorted(candidates, key=lambda item: item.score.total, reverse=True)
        top = ranked[0]
        second = ranked[1] if len(ranked) > 1 else None
        strong_threshold = 0.72
        alternate_threshold = 0.68
        ambiguity_gap = 0.18 if prefer_folders else 0.32
        if top.score.total >= strong_threshold and second is not None and second.score.total >= alternate_threshold and (top.score.total - second.score.total) <= ambiguity_gap:
            return FileResolutionDecision(
                state="accessible_multiple_strong_matches",
                candidates=ranked[:3],
                clarification_required=True,
                failure_reason=AccessFailureReason.MULTIPLE_STRONG_MATCHES.value,
            )
        if top.score.total >= strong_threshold:
            return FileResolutionDecision(
                state="accessible_single_strong_match",
                chosen_candidate=top,
                candidates=ranked[:5],
            )
        return FileResolutionDecision(
            state="accessible_no_strong_match",
            candidates=ranked[:5],
            clarification_required=False,
            failure_reason=AccessFailureReason.NO_STRONG_MATCH.value,
        )

    def _canonical_file_tokens(self, text: str) -> set[str]:
        normalized = normalize_lookup_phrase(text) or normalize_phrase(text)
        tokens = re.findall(r"[a-z0-9]+", normalized)
        canonical: set[str] = set()
        for token in tokens:
            if token in FILE_QUERY_STOP_WORDS:
                continue
            canonical.add(SEMANTIC_TOKEN_MAP.get(token, token))
        return canonical

    def _coverage(self, query_tokens: set[str], candidate_tokens: set[str]) -> float:
        if not query_tokens:
            return 0.0
        return len(query_tokens & candidate_tokens) / float(max(len(query_tokens), 1))

    def _overlap(self, query_tokens: set[str], candidate_tokens: set[str]) -> float:
        if not query_tokens or not candidate_tokens:
            return 0.0
        return len(query_tokens & candidate_tokens) / float(max(len(query_tokens), len(candidate_tokens)))

    def _keyword_bonus(self, query_tokens: set[str], normalized_name: str) -> float:
        bonus = 0.0
        for canonical, keywords in KEYWORD_FAMILIES.items():
            if canonical not in query_tokens:
                continue
            if any(keyword in normalized_name for keyword in keywords):
                bonus += 0.08
        return min(bonus, 0.16)

    def _type_bonus(self, query_tokens: set[str], extension: str, *, requested_extensions: set[str]) -> float:
        if requested_extensions and extension in requested_extensions:
            return 0.12
        if "pdf" in query_tokens and extension == ".pdf":
            return 0.1
        if "docs" in query_tokens and extension in {".pdf", ".doc", ".docx", ".md", ".txt"}:
            return 0.06
        return 0.0

    def _recency_bonus(self, path: Path) -> float:
        modified_at = self._modified_at(path)
        if not modified_at:
            return 0.0
        return 0.06

    def _modified_at(self, path: Path) -> float | None:
        try:
            return float(path.stat().st_mtime)
        except OSError:
            return None

    def _action_for_fuzzy_candidate(self, candidate: FuzzyFileCandidate, *, open_target: str) -> dict[str, Any] | None:
        path = Path(candidate.path)
        if open_target == "deck" and not candidate.is_dir():
            return {
                "type": "workspace_open",
                "target": "deck",
                "module": "files",
                "section": "opened-items",
                "item": self._deck_file_item({"path": str(path), "title": candidate.title}),
            }
        return self._external_open_action(path)

    def _external_open_action(self, path: Path) -> dict[str, Any]:
        resolved = path.resolve()
        return {
            "type": "open_external",
            "path": str(resolved),
            "url": resolved.as_uri(),
        }

    def _response_contract(self, *, bearing_title: str, micro_response: str, full_response: str) -> dict[str, Any]:
        return {
            "type": "desktop_search",
            "bearing_title": bearing_title,
            "micro_response": micro_response,
            "full_response": full_response,
        }

    def _emit_folder_search_debug(self, message: str, payload: dict[str, Any]) -> None:
        self.context.events.publish(
            level="DEBUG",
            source="workflow.desktop_search",
            message=message,
            payload=payload,
        )

    def execute_workflow(self, *, workflow_kind: str, query: str, session_id: str) -> ToolResult:
        chain = self._build_workflow_chain(workflow_kind=workflow_kind, query=query, session_id=session_id)
        if chain is None:
            return ToolResult(success=False, summary="That workflow is not available here yet.", error="unsupported_workflow")
        return self._run_chain(chain)

    def repair_action(self, *, repair_kind: str, target: str, session_id: str) -> ToolResult:
        chain = self._build_repair_chain(repair_kind=repair_kind, target=target, session_id=session_id)
        if chain is None:
            return ToolResult(success=False, summary="That repair action is not available here yet.", error="unsupported_repair")
        return self._run_chain(chain)

    def _build_workflow_chain(self, *, workflow_kind: str, query: str, session_id: str) -> ActionChain | None:
        kind = str(workflow_kind or "").strip().lower()
        if kind == "writing_setup":
            return ActionChain(
                title="Writing setup",
                kind=kind,
                steps=[
                    WorkflowStep("Assemble the writing workspace", "workspace_assemble", {"query": query or "writing", "session_id": session_id}, True),
                    WorkflowStep(
                        "Pull the latest writing file",
                        "search_open",
                        {"query": "draft notes writing", "domains": ["files"], "open_target": "deck", "latest_only": True, "file_extensions": sorted(NOTE_EXTENSIONS)},
                    ),
                    WorkflowStep("Focus the active thread", "workspace_focus", {"module": "chartroom", "section": "active-thread"}, True),
                ],
            )
        if kind == "research_setup":
            return ActionChain(
                title="Research setup",
                kind=kind,
                steps=[
                    WorkflowStep("Assemble the research workspace", "workspace_assemble", {"query": query or "research", "session_id": session_id}, True),
                    WorkflowStep("Focus references in the Deck", "workspace_focus", {"module": "browser", "section": "references"}, True),
                ],
            )
        if kind == "diagnostics_setup":
            return ActionChain(
                title="Diagnostics setup",
                kind=kind,
                steps=[
                    WorkflowStep("Assemble the diagnostics workspace", "workspace_assemble", {"query": query or "diagnostics", "session_id": session_id}, True),
                    WorkflowStep("Run a short network diagnostic sample", "network_diagnosis", {"focus": "overview", "diagnostic_burst": True}),
                    WorkflowStep("Focus Systems diagnostics", "workspace_focus", {"module": "systems", "section": "network"}, True),
                ],
            )
        if kind == "current_work_context":
            return ActionChain(
                title="Current work context",
                kind=kind,
                steps=[
                    WorkflowStep("Restore the current workspace context", "workspace_restore", {"query": query or "current workspace", "session_id": session_id}, True),
                    WorkflowStep("Focus the active thread", "workspace_focus", {"module": "chartroom", "section": "active-thread"}, True),
                ],
            )
        if kind == "project_setup":
            return ActionChain(
                title="Project setup",
                kind=kind,
                steps=[
                    WorkflowStep("Assemble the project workspace", "workspace_assemble", {"query": query or "project", "session_id": session_id}, True),
                    WorkflowStep("Focus the working set", "workspace_focus", {"module": "files", "section": "opened-items"}, True),
                ],
            )
        return None

    def _build_repair_chain(self, *, repair_kind: str, target: str, session_id: str) -> ActionChain | None:
        del session_id
        kind = str(repair_kind or "").strip().lower()
        target_name = str(target or "").strip()
        if kind == "network_repair":
            return ActionChain(
                title="Network repair",
                kind=kind,
                steps=[
                    WorkflowStep("Check current connectivity", "network_diagnosis", {"focus": "overview", "diagnostic_burst": True}, True),
                    WorkflowStep("Flush the DNS cache", "flush_dns", required=True),
                    WorkflowStep("Restart the network adapter", "restart_network_adapter"),
                ],
            )
        if kind == "connectivity_checks":
            return ActionChain(
                title="Connectivity checks",
                kind=kind,
                steps=[WorkflowStep("Run a diagnostic connection sample", "network_diagnosis", {"focus": "overview", "diagnostic_burst": True}, True)],
            )
        if kind == "flush_dns":
            return ActionChain(title="DNS cache flush", kind=kind, steps=[WorkflowStep("Flush the DNS cache", "flush_dns", required=True)])
        if kind == "restart_network_adapter":
            return ActionChain(title="Network adapter restart", kind=kind, steps=[WorkflowStep("Restart the network adapter", "restart_network_adapter", required=True)])
        if kind == "restart_explorer":
            return ActionChain(title="Explorer restart", kind=kind, steps=[WorkflowStep("Restart Explorer", "restart_explorer", required=True)])
        if kind == "relaunch_app" and target_name:
            return ActionChain(title=f"Relaunch {target_name}", kind=kind, steps=[WorkflowStep(f"Restart {target_name}", "app_restart", {"app_name": target_name}, True)])
        return None

    def _run_chain(self, chain: ActionChain) -> ToolResult:
        actions: list[dict[str, Any]] = []
        restore_action: dict[str, Any] | None = None
        chain.status = "running"
        self._emit_progress(chain)
        for index, step in enumerate(chain.steps):
            chain.current_step_index = index
            step.status = "running"
            self._emit_progress(chain)
            outcome = self._run_step(step)
            if not outcome.get("success", False):
                step.status = "failed"
                step.error = str(outcome.get("error") or outcome.get("reason") or "step_failed")
                step.summary = str(outcome.get("summary") or "Step failed.")
                step.data = dict(outcome.get("data") or {})
                chain.partial = True
                if step.required:
                    chain.status = "failed"
                    break
                continue
            step.status = "completed"
            step.summary = str(outcome.get("summary") or "Completed.")
            step.data = dict(outcome.get("data") or {})
            candidate_restore = outcome.get("restore_action")
            if isinstance(candidate_restore, dict):
                restore_action = dict(candidate_restore)
            step_actions = outcome.get("actions")
            if isinstance(step_actions, list):
                actions.extend(action for action in step_actions if isinstance(action, dict))
            elif isinstance(step_actions, dict):
                actions.append(step_actions)
            self._emit_progress(chain)

        if chain.status != "failed":
            chain.status = "completed"
        completed_steps = sum(1 for step in chain.steps if step.status == "completed")
        if chain.status == "failed":
            chain.summary = self._failure_summary(chain)
            success = False
            error = "workflow_failed"
        elif chain.partial:
            chain.summary = self._partial_summary(chain, completed_steps=completed_steps)
            success = True
            error = None
        else:
            chain.summary = self._success_summary(chain)
            success = True
            error = None
        if restore_action is not None:
            focus_action = next(
                (
                    action
                    for action in actions
                    if str(action.get("type", "")).strip().lower() == "workspace_focus"
                ),
                None,
            )
            if isinstance(focus_action, dict):
                restore_action["module"] = str(focus_action.get("module", restore_action.get("module", "chartroom")))
                restore_action["section"] = str(focus_action.get("section", restore_action.get("section", "working-set")))
            actions = [action for action in actions if str(action.get("type", "")).strip().lower() == "workspace_focus"] + [restore_action]
        self._emit_progress(chain)
        return ToolResult(success=success, summary=chain.summary, data={"workflow": chain.progress_payload(), "actions": actions}, error=error)

    def _run_step(self, step: WorkflowStep) -> dict[str, Any]:
        kind = step.kind
        if kind == "workspace_assemble":
            if self.context.workspace_service is None:
                return {"success": False, "error": "workspace_service_unavailable", "summary": "Workspace memory is unavailable."}
            result = self.context.workspace_service.assemble_workspace(str(step.parameters.get("query", "")), session_id=str(step.parameters.get("session_id", "default")))
            return {"success": True, "summary": str(result.get("summary", "Workspace assembled.")), "data": result, "restore_action": self._workspace_restore_action(result)}
        if kind == "workspace_restore":
            if self.context.workspace_service is None:
                return {"success": False, "error": "workspace_service_unavailable", "summary": "Workspace memory is unavailable."}
            result = self.context.workspace_service.restore_workspace(str(step.parameters.get("query", "")), session_id=str(step.parameters.get("session_id", "default")))
            return {"success": True, "summary": str(result.get("summary", "Workspace restored.")), "data": result, "restore_action": self._workspace_restore_action(result)}
        if kind == "workspace_focus":
            return {
                "success": True,
                "summary": f"Focused {step.parameters.get('module', 'deck')}.",
                "actions": {"type": "workspace_focus", "target": "deck", "module": str(step.parameters.get("module", "chartroom")), "section": str(step.parameters.get("section", "overview"))},
            }
        if kind == "search_open":
            search = self.desktop_search(
                query=str(step.parameters.get("query", "")),
                domains=[str(domain) for domain in step.parameters.get("domains", ["files"])],
                action="open",
                open_target=str(step.parameters.get("open_target", "deck")),
                latest_only=bool(step.parameters.get("latest_only", False)),
                file_extensions=[str(ext) for ext in step.parameters.get("file_extensions", [])],
                folder_hint=str(step.parameters.get("folder_hint", "")).strip() or None,
                prefer_folders=bool(step.parameters.get("prefer_folders", False)),
                session_id="default",
                limit=3,
            )
            return {"success": search.success, "summary": search.summary, "data": dict(search.data), "error": search.error}
        if kind == "network_diagnosis":
            probe = self.context.system_probe
            if probe is None or not hasattr(probe, "network_diagnosis"):
                return {"success": False, "error": "network_diagnosis_unavailable", "summary": "Network diagnosis is unavailable."}
            data = probe.network_diagnosis(focus=str(step.parameters.get("focus", "overview")), diagnostic_burst=bool(step.parameters.get("diagnostic_burst", False)))
            assessment = data.get("assessment", {}) if isinstance(data, dict) else {}
            return {"success": True, "summary": str(assessment.get("headline") or "Ran a diagnostic sample.").strip(), "data": {"diagnosis": data}, "actions": {"type": "workspace_focus", "target": "deck", "module": "systems", "section": "network"}}
        if kind == "flush_dns":
            probe = self.context.system_probe
            if probe is None or not hasattr(probe, "flush_dns_cache"):
                return {"success": False, "error": "flush_dns_unavailable", "summary": "DNS cache flushing is unavailable."}
            data = probe.flush_dns_cache()
            return {"success": bool(data.get("success")), "summary": "Flushed the DNS cache." if data.get("success") else "DNS cache flush is unavailable here.", "data": data, "error": data.get("reason")}
        if kind == "restart_network_adapter":
            probe = self.context.system_probe
            if probe is None or not hasattr(probe, "restart_network_adapter"):
                return {"success": False, "error": "restart_network_adapter_unavailable", "summary": "Adapter restart is unavailable."}
            data = probe.restart_network_adapter()
            return {"success": bool(data.get("success")), "summary": "Restarted the network adapter." if data.get("success") else "Network adapter restart is unavailable here.", "data": data, "error": data.get("reason")}
        if kind == "restart_explorer":
            probe = self.context.system_probe
            if probe is None or not hasattr(probe, "restart_explorer_shell"):
                return {"success": False, "error": "restart_explorer_unavailable", "summary": "Explorer restart is unavailable."}
            data = probe.restart_explorer_shell()
            return {"success": bool(data.get("success")), "summary": "Restarted Explorer." if data.get("success") else "Explorer restart failed.", "data": data, "error": data.get("reason")}
        if kind == "app_restart":
            probe = self.context.system_probe
            if probe is None or not hasattr(probe, "app_control"):
                return {"success": False, "error": "app_control_unavailable", "summary": "App restart is unavailable."}
            app_name = str(step.parameters.get("app_name", "")).strip()
            data = probe.app_control(action="restart", app_name=app_name)
            return {"success": bool(data.get("success")), "summary": f"Relaunched {app_name}." if data.get("success") else f"Couldn't relaunch {app_name}.", "data": data, "error": data.get("reason")}
        return {"success": False, "error": "unsupported_step_kind", "summary": "Unsupported workflow step."}

    def _search_results(
        self,
        *,
        query: str,
        domains: list[str],
        latest_only: bool,
        file_extensions: list[str],
        limit: int,
    ) -> list[SearchResult]:
        requested_extensions = {self._normalize_extension(value) for value in file_extensions if self._normalize_extension(value)}
        candidates: list[SearchResult] = []
        if "files" in domains:
            candidates.extend(self._search_workspace_files(query=query, latest_only=latest_only, file_extensions=requested_extensions, limit=limit))
            candidates.extend(self._search_recent_files(query=query, latest_only=latest_only, file_extensions=requested_extensions, limit=limit))
        if "apps" in domains:
            candidates.extend(self._search_apps(query=query, limit=limit))
        if "windows" in domains:
            candidates.extend(self._search_windows(query=query, limit=limit))

        deduped: dict[tuple[str, str], SearchResult] = {}
        for candidate in candidates:
            key = (
                candidate.domain,
                str(candidate.target.get("path") or candidate.target.get("url") or candidate.target.get("window_handle") or candidate.title).strip().lower(),
            )
            existing = deduped.get(key)
            if existing is None or candidate.score > existing.score:
                deduped[key] = candidate
        return sorted(deduped.values(), key=lambda item: item.score, reverse=True)[:limit]

    def _search_workspace_files(
        self,
        *,
        query: str,
        latest_only: bool,
        file_extensions: set[str],
        limit: int,
    ) -> list[SearchResult]:
        workspace_service = self.context.workspace_service
        indexer = getattr(workspace_service, "indexer", None)
        if indexer is None or not hasattr(indexer, "search_files"):
            return []
        try:
            matches = indexer.search_files(query, limit=max(limit * 2, 8))
        except Exception:
            return []
        results: list[SearchResult] = []
        for item in matches:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "").strip()
            extension = self._normalize_extension(Path(path).suffix if path else "")
            if file_extensions and extension not in file_extensions:
                continue
            reasons = list(((item.get("metadata") or {}).get("reasons") or [])) if isinstance(item.get("metadata"), dict) else []
            if extension:
                reasons.append(f"Matched {extension} file type")
            if latest_only:
                reasons.append("Favored the latest matching file")
            score = float(item.get("score") or 0.6)
            if latest_only:
                score += 0.08
            results.append(
                SearchResult(
                    domain="files",
                    title=str(item.get("title") or Path(path).name or "File"),
                    subtitle=path or str(item.get("subtitle") or ""),
                    score=score,
                    target=self._deck_file_item(item),
                    reasons=[str(reason) for reason in reasons if str(reason).strip()],
                    kind=str(item.get("kind") or extension.lstrip(".") or "file"),
                    metadata={"source": "workspace_index", "latest_only": latest_only},
                )
            )
        return results

    def _search_recent_files(
        self,
        *,
        query: str,
        latest_only: bool,
        file_extensions: set[str],
        limit: int,
    ) -> list[SearchResult]:
        probe = self.context.system_probe
        if probe is None or not hasattr(probe, "recent_files"):
            return []
        payload = probe.recent_files(limit=max(limit * 2, 12))
        files = payload.get("files", []) if isinstance(payload, dict) else []
        results: list[SearchResult] = []
        for index, item in enumerate(files):
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "").strip()
            extension = self._normalize_extension(Path(path).suffix if path else "")
            if file_extensions and extension not in file_extensions:
                continue
            name = str(item.get("name") or Path(path).name or "File").strip()
            score = 0.34 + self._token_score(query, name=name, path=path)
            if latest_only:
                score += max(0.0, 0.3 - (index * 0.03))
            reasons = ["Recent file watch"]
            if extension:
                reasons.append(f"Matched {extension} file type")
            if latest_only:
                reasons.append("Most recent candidate")
            results.append(
                SearchResult(
                    domain="files",
                    title=name,
                    subtitle=path,
                    score=score,
                    target=self._deck_file_item({"path": path, "title": name}),
                    reasons=reasons,
                    kind=extension.lstrip(".") or "file",
                    metadata={"source": "recent_files", "modified_at": str(item.get("modified_at") or "")},
                )
            )
        return results

    def _search_apps(self, *, query: str, limit: int) -> list[SearchResult]:
        probe = self.context.system_probe
        if probe is None or not hasattr(probe, "active_apps"):
            return []
        payload = probe.active_apps()
        apps = payload.get("applications", []) if isinstance(payload, dict) else []
        results: list[SearchResult] = []
        for item in apps:
            if not isinstance(item, dict):
                continue
            process_name = str(item.get("process_name") or "").strip()
            window_title = str(item.get("window_title") or "").strip()
            score = self._token_score(query, name=process_name, path=window_title)
            if score <= 0:
                continue
            results.append(
                SearchResult(
                    domain="apps",
                    title=window_title or process_name or "Application",
                    subtitle=process_name,
                    score=0.35 + score,
                    target={
                        "app_name": process_name or window_title,
                        "window_title": window_title,
                        "path": item.get("path"),
                    },
                    reasons=["Matched the active application list"],
                    kind="application",
                    metadata={"pid": item.get("pid")},
                )
            )
        return sorted(results, key=lambda item: item.score, reverse=True)[:limit]

    def _search_windows(self, *, query: str, limit: int) -> list[SearchResult]:
        probe = self.context.system_probe
        if probe is None or not hasattr(probe, "window_status"):
            return []
        payload = probe.window_status()
        windows = payload.get("windows", []) if isinstance(payload, dict) else []
        results: list[SearchResult] = []
        for item in windows:
            if not isinstance(item, dict):
                continue
            process_name = str(item.get("process_name") or "").strip()
            window_title = str(item.get("window_title") or "").strip()
            score = self._token_score(query, name=window_title, path=process_name)
            if score <= 0:
                continue
            results.append(
                SearchResult(
                    domain="windows",
                    title=window_title or process_name or "Window",
                    subtitle=process_name,
                    score=0.32 + score,
                    target={
                        "app_name": process_name or window_title,
                        "window_title": window_title,
                        "window_handle": item.get("window_handle"),
                    },
                    reasons=["Matched an open window"],
                    kind="window",
                    metadata={"pid": item.get("pid"), "monitor_index": item.get("monitor_index")},
                )
            )
        return sorted(results, key=lambda item: item.score, reverse=True)[:limit]

    def _action_for_search_result(self, result: SearchResult, *, open_target: str) -> dict[str, Any] | None:
        if result.domain != "files":
            return None
        if open_target == "external":
            path = str(result.target.get("path") or "").strip()
            if path:
                return self._external_open_action(Path(path))
        return {
            "type": "workspace_open",
            "target": "deck",
            "module": "files",
            "section": "opened-items",
            "item": dict(result.target),
        }

    def _workspace_restore_action(self, payload: dict[str, Any]) -> dict[str, Any]:
        workspace = dict(payload.get("workspace") or {}) if isinstance(payload.get("workspace"), dict) else {}
        items = [dict(item) for item in payload.get("items", []) if isinstance(item, dict)] if isinstance(payload.get("items"), list) else []
        active_item_id = str(items[0].get("itemId", "")) if items else ""
        return {
            "type": "workspace_restore",
            "target": "deck",
            "module": "chartroom",
            "section": "working-set",
            "workspace": workspace,
            "items": items,
            "active_item_id": active_item_id,
        }

    def _search_capabilities(self) -> dict[str, Any]:
        probe = self.context.system_probe
        capabilities = probe.control_capabilities() if probe is not None and hasattr(probe, "control_capabilities") else {}
        search_caps = capabilities.get("search", {}) if isinstance(capabilities, dict) and isinstance(capabilities.get("search"), dict) else {}
        files_supported = bool(search_caps.get("workspace_files") or search_caps.get("recent_files") or getattr(getattr(self.context.workspace_service, "indexer", None), "search_files", None) or hasattr(probe, "recent_files") if probe is not None else False)
        apps_supported = bool(search_caps.get("apps") or (probe is not None and hasattr(probe, "active_apps")))
        windows_supported = bool(search_caps.get("windows") or (probe is not None and hasattr(probe, "window_status")))
        return {
            "files": files_supported,
            "apps": apps_supported,
            "windows": windows_supported,
            "workspace_files": bool(search_caps.get("workspace_files", files_supported)),
            "recent_files": bool(search_caps.get("recent_files", files_supported)),
            "browser_tabs": bool(search_caps.get("browser_tabs", False)),
            "notes": bool(search_caps.get("notes", False)),
            "repair": capabilities.get("repair", {}) if isinstance(capabilities, dict) else {},
        }

    def _token_score(self, query: str, *, name: str, path: str = "") -> float:
        stop_words = {"find", "latest", "open", "show", "the", "my", "and", "it", "this", "that", "recent"}
        tokens = [token for token in normalize_lookup_phrase(query).split() if token and token not in stop_words]
        if not tokens:
            return 0.18 if any(token in normalize_lookup_phrase(query) for token in {"pdf", "doc", "note", "notes"}) else 0.0
        haystack = " ".join(part for part in (normalize_lookup_phrase(name), normalize_lookup_phrase(path)) if part)
        if not haystack:
            return 0.0
        overlap = sum(1 for token in tokens if token in haystack)
        return overlap / max(len(tokens), 1)

    def _normalize_extension(self, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if not normalized:
            return ""
        return normalized if normalized.startswith(".") else f".{normalized}"

    def _deck_file_item(self, item: dict[str, Any]) -> dict[str, Any]:
        path = str(item.get("path") or "").strip()
        title = str(item.get("title") or Path(path).name or "File").strip()
        extension = self._normalize_extension(Path(path).suffix if path else "")
        kind = str(item.get("kind") or extension.lstrip(".") or "file").strip() or "file"
        viewer = str(item.get("viewer") or ("pdf" if extension == ".pdf" else "markdown" if extension in NOTE_EXTENSIONS else kind)).strip()
        return {
            "itemId": str(item.get("itemId") or path or title),
            "kind": kind,
            "viewer": viewer,
            "title": title,
            "subtitle": str(item.get("summary") or item.get("subtitle") or path),
            "path": path or None,
            "url": str(item.get("url") or ""),
            "module": "files",
            "section": "opened-items",
        }

    def _success_summary(self, chain: ActionChain) -> str:
        labels = {
            "writing_setup": "Opened the writing setup.",
            "research_setup": "Opened the research setup.",
            "diagnostics_setup": "Opened the diagnostics setup.",
            "current_work_context": "Restored the current work context.",
            "project_setup": "Opened the project setup.",
            "network_repair": "Ran the first network repair steps.",
            "connectivity_checks": "Ran connectivity checks.",
            "flush_dns": "Flushed the DNS cache.",
            "restart_network_adapter": "Restarted the network adapter.",
            "restart_explorer": "Restarted Explorer.",
            "relaunch_app": f"Relaunched {chain.title.replace('Relaunch ', '').strip()}.",
        }
        return labels.get(chain.kind, f"Completed {chain.title.lower()}.")

    def _partial_summary(self, chain: ActionChain, *, completed_steps: int) -> str:
        failed_step = next((step for step in chain.steps if step.status == "failed"), None)
        if chain.kind == "network_repair":
            dns_flushed = any(step.kind == "flush_dns" and step.status == "completed" for step in chain.steps)
            if failed_step is not None and failed_step.kind == "restart_network_adapter":
                if dns_flushed:
                    return "Ran the first network repair steps and flushed the DNS cache, but adapter recovery is unavailable here."
                return "Ran the first network repair steps, but adapter recovery is unavailable here."
            if dns_flushed:
                return "Ran the first network repair steps and flushed the DNS cache, but some recovery actions were unavailable."
            return "Ran the first network repair steps, but some recovery actions were unavailable."

        success_label = self._success_summary(chain).rstrip(".")
        return f"{success_label} with some limits ({completed_steps}/{len(chain.steps)} steps)."

    def _failure_summary(self, chain: ActionChain) -> str:
        failed_step = next((step for step in chain.steps if step.status == "failed"), None)
        if failed_step is None:
            return f"{chain.title} stopped."
        return failed_step.summary or f"{failed_step.title} failed."

    def _emit_progress(self, chain: ActionChain) -> None:
        total_steps = max(len(chain.steps), 1)
        current_index = max(chain.current_step_index, 0)
        active_title = chain.steps[current_index].title if 0 <= current_index < len(chain.steps) else chain.title
        summary = chain.summary or f"Running step {min(current_index + 1, total_steps)} of {total_steps}: {active_title}."
        self.context.report_progress({"summary": summary, "data": {"workflow": chain.progress_payload()}})
