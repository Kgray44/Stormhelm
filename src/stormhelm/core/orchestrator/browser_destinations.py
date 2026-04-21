from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import re
from typing import Any

from stormhelm.core.intelligence.language import normalize_phrase


class BrowserIntentType(StrEnum):
    OPEN_DESTINATION = "open_destination"
    SEARCH_REQUEST = "search_request"


class DestinationScope(StrEnum):
    GENERAL = "general"
    PERSONAL = "personal"


class BrowserOpenFailureReason(StrEnum):
    DESTINATION_UNRESOLVED = "destination_unresolved"
    AMBIGUOUS_DESTINATION = "ambiguous_destination"
    BROWSER_OPEN_UNAVAILABLE = "browser_open_unavailable"
    BROWSER_OPEN_FAILED = "browser_open_failed"
    EXPLICIT_BROWSER_UNAVAILABLE = "explicit_browser_unavailable"


@dataclass(frozen=True, slots=True)
class KnownWebDestination:
    key: str
    title: str
    url: str
    aliases: tuple[str, ...]
    personal_aliases: tuple[str, ...] = ()
    requires_signed_in_session: bool = False

    def all_aliases(self, *, include_personal: bool) -> tuple[str, ...]:
        if include_personal:
            return tuple(dict.fromkeys([*self.aliases, *self.personal_aliases]))
        return self.aliases

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "url": self.url,
            "aliases": list(self.aliases),
            "personal_aliases": list(self.personal_aliases),
            "requires_signed_in_session": self.requires_signed_in_session,
        }


@dataclass(slots=True)
class BrowserDestinationRequest:
    raw_text: str
    normalized_text: str
    intent_type: BrowserIntentType
    destination_phrase: str
    scope: DestinationScope
    open_target: str
    browser_preference: str = "default"
    explicit_browser: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_text": self.raw_text,
            "normalized_text": self.normalized_text,
            "intent_type": self.intent_type.value,
            "destination_phrase": self.destination_phrase,
            "scope": self.scope.value,
            "open_target": self.open_target,
            "browser_preference": self.browser_preference,
            "explicit_browser": self.explicit_browser,
        }


@dataclass(slots=True)
class DestinationResolutionResult:
    success: bool
    request: BrowserDestinationRequest
    destination: KnownWebDestination | None = None
    url: str | None = None
    matched_alias: str | None = None
    failure_reason: BrowserOpenFailureReason | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "request": self.request.to_dict(),
            "destination": self.destination.to_dict() if self.destination is not None else None,
            "url": self.url,
            "matched_alias": self.matched_alias,
            "failure_reason": self.failure_reason.value if self.failure_reason is not None else None,
            "notes": list(self.notes),
        }


@dataclass(slots=True)
class BrowserOpenPlan:
    tool_name: str | None
    tool_arguments: dict[str, Any]
    response_contract: dict[str, str]
    open_target: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "tool_arguments": dict(self.tool_arguments),
            "response_contract": dict(self.response_contract),
            "open_target": self.open_target,
        }


KNOWN_BROWSER_DESTINATIONS: tuple[KnownWebDestination, ...] = (
    KnownWebDestination(
        key="youtube_history",
        title="YouTube history",
        url="https://www.youtube.com/feed/history",
        aliases=("youtube history",),
        personal_aliases=("history",),
        requires_signed_in_session=True,
    ),
    KnownWebDestination(
        key="youtube",
        title="YouTube",
        url="https://www.youtube.com/",
        aliases=("youtube",),
    ),
    KnownWebDestination(
        key="gmail",
        title="Gmail",
        url="https://mail.google.com/mail/u/0/#inbox",
        aliases=("gmail",),
        personal_aliases=("email", "mail", "inbox"),
        requires_signed_in_session=True,
    ),
    KnownWebDestination(
        key="google_drive",
        title="Google Drive",
        url="https://drive.google.com/drive/my-drive",
        aliases=("google drive",),
        personal_aliases=("drive", "my drive"),
        requires_signed_in_session=True,
    ),
    KnownWebDestination(
        key="chatgpt",
        title="ChatGPT",
        url="https://chatgpt.com/",
        aliases=("chatgpt", "chat gpt"),
    ),
    KnownWebDestination(
        key="openai",
        title="OpenAI",
        url="https://openai.com/",
        aliases=("openai", "open ai"),
    ),
    KnownWebDestination(
        key="github",
        title="GitHub",
        url="https://github.com/",
        aliases=("github", "git hub"),
    ),
    KnownWebDestination(
        key="google_docs",
        title="Google Docs",
        url="https://docs.google.com/document/",
        aliases=("google docs", "docs"),
        personal_aliases=("my docs",),
        requires_signed_in_session=True,
    ),
    KnownWebDestination(
        key="calendar",
        title="Google Calendar",
        url="https://calendar.google.com/",
        aliases=("calendar", "google calendar"),
        personal_aliases=("my calendar",),
        requires_signed_in_session=True,
    ),
    KnownWebDestination(
        key="maps",
        title="Google Maps",
        url="https://maps.google.com/",
        aliases=("maps", "google maps"),
    ),
    KnownWebDestination(
        key="reddit",
        title="Reddit",
        url="https://www.reddit.com/",
        aliases=("reddit",),
    ),
    KnownWebDestination(
        key="outlook_web",
        title="Outlook",
        url="https://outlook.office.com/mail/",
        aliases=("outlook", "outlook web"),
        personal_aliases=("outlook inbox",),
        requires_signed_in_session=True,
    ),
    KnownWebDestination(
        key="dropbox",
        title="Dropbox",
        url="https://www.dropbox.com/home",
        aliases=("dropbox",),
        requires_signed_in_session=True,
    ),
    KnownWebDestination(
        key="onedrive_web",
        title="OneDrive",
        url="https://onedrive.live.com/",
        aliases=("onedrive", "one drive"),
        personal_aliases=("my onedrive",),
        requires_signed_in_session=True,
    ),
)

OPEN_PREFIX_PATTERN = re.compile(r"^(?:open|show|bring up|pull up)\s+", re.IGNORECASE)
SEARCH_PREFIX_PATTERN = re.compile(r"^(?:search|look up|lookup|google)\s+", re.IGNORECASE)
TRAILING_BROWSER_MARKERS = (
    r"\bin a browser\b",
    r"\bin the browser\b",
    r"\busing a browser\b",
    r"\busing the browser\b",
    r"\bopen externally\b",
    r"\bexternally\b",
    r"\bon the web\b",
)
TRAILING_SITE_MARKERS = (
    r"\bsite\b",
    r"\bwebsite\b",
    r"\bhomepage\b",
    r"\bhome page\b",
)
NON_BROWSER_DESTINATION_PHRASES = {
    "weather",
    "forecast",
    "location settings",
    "bluetooth settings",
    "wifi settings",
    "wi fi settings",
    "wi-fi settings",
    "network settings",
    "sound settings",
    "display settings",
    "task manager",
    "device manager",
    "resource monitor",
}


class BrowserDestinationResolver:
    def __init__(self, destinations: tuple[KnownWebDestination, ...] | None = None) -> None:
        self._destinations = tuple(destinations or KNOWN_BROWSER_DESTINATIONS)

    def intent_type(self, text: str) -> BrowserIntentType | None:
        lower = normalize_phrase(text)
        if self._looks_like_search_request(lower):
            return BrowserIntentType.SEARCH_REQUEST
        if self._looks_like_open_destination_request(lower):
            return BrowserIntentType.OPEN_DESTINATION
        return None

    def parse(self, text: str, *, surface_mode: str) -> BrowserDestinationRequest | None:
        lower = normalize_phrase(text)
        intent_type = self.intent_type(lower)
        if intent_type != BrowserIntentType.OPEN_DESTINATION:
            return None
        explicit_browser = any(re.search(pattern, lower) for pattern in TRAILING_BROWSER_MARKERS)
        open_target = "external" if explicit_browser or surface_mode.strip().lower() != "deck" else "deck"
        scope = DestinationScope.PERSONAL if self._has_personal_scope(lower) else DestinationScope.GENERAL
        destination_phrase = self._extract_destination_phrase(lower)
        if not destination_phrase or self._is_excluded_destination_phrase(destination_phrase):
            return None
        return BrowserDestinationRequest(
            raw_text=text,
            normalized_text=lower,
            intent_type=BrowserIntentType.OPEN_DESTINATION,
            destination_phrase=destination_phrase,
            scope=scope,
            open_target=open_target,
            browser_preference="default",
            explicit_browser=explicit_browser,
        )

    def resolve(self, request: BrowserDestinationRequest) -> DestinationResolutionResult:
        candidate = normalize_phrase(request.destination_phrase)
        include_personal = request.scope == DestinationScope.PERSONAL
        matches: list[tuple[KnownWebDestination, str]] = []
        for destination in self._destinations:
            for alias in destination.all_aliases(include_personal=include_personal):
                normalized_alias = normalize_phrase(alias)
                if candidate == normalized_alias:
                    matches.append((destination, normalized_alias))
        if len(matches) > 1:
            return DestinationResolutionResult(
                success=False,
                request=request,
                failure_reason=BrowserOpenFailureReason.AMBIGUOUS_DESTINATION,
                notes=["multiple known browser destinations matched the normalized phrase"],
            )
        if not matches:
            return DestinationResolutionResult(
                success=False,
                request=request,
                failure_reason=BrowserOpenFailureReason.DESTINATION_UNRESOLVED,
                notes=["no known browser destination matched the normalized phrase"],
            )
        destination, matched_alias = matches[0]
        return DestinationResolutionResult(
            success=True,
            request=request,
            destination=destination,
            url=destination.url,
            matched_alias=matched_alias,
            notes=[
                f"matched known destination alias '{matched_alias}'",
                "signed-in browser state will handle authentication naturally" if destination.requires_signed_in_session else "destination does not require a signed-in browser session",
            ],
        )

    def build_open_plan(self, resolution: DestinationResolutionResult) -> BrowserOpenPlan:
        if not resolution.success or resolution.destination is None or resolution.url is None:
            raise ValueError("A successful destination resolution is required to build a browser open plan.")
        response_contract = self.response_contract_for_success(resolution)
        tool_name = "deck_open_url" if resolution.request.open_target == "deck" else "external_open_url"
        return BrowserOpenPlan(
            tool_name=tool_name,
            tool_arguments={
                "url": resolution.url,
                "label": resolution.destination.title,
                "response_contract": response_contract,
            },
            response_contract=response_contract,
            open_target=resolution.request.open_target,
        )

    def response_contract_for_success(self, resolution: DestinationResolutionResult) -> dict[str, str]:
        title = resolution.destination.title if resolution.destination is not None else "Browser destination"
        if resolution.request.open_target == "deck":
            return {
                "bearing_title": f"{title} opened",
                "micro_response": f"Opened {title} in Stormhelm.",
                "full_response": "Resolved the destination and opened it in Stormhelm.",
            }
        return {
            "bearing_title": f"{title} opened",
            "micro_response": f"Opened {title} in the browser.",
            "full_response": "Resolved the destination and opened it in the browser.",
        }

    def response_contract_for_failure(self, reason: BrowserOpenFailureReason) -> dict[str, str]:
        if reason == BrowserOpenFailureReason.AMBIGUOUS_DESTINATION:
            return {
                "bearing_title": "Browser destination ambiguous",
                "micro_response": "I need the site clarified.",
                "full_response": "I found multiple browser destinations that could match that request.",
            }
        if reason == BrowserOpenFailureReason.BROWSER_OPEN_UNAVAILABLE:
            return {
                "bearing_title": "Browser opening unavailable",
                "micro_response": "Browser opening isn't available here.",
                "full_response": "Browser opening isn't available in the current environment.",
            }
        if reason == BrowserOpenFailureReason.BROWSER_OPEN_FAILED:
            return {
                "bearing_title": "Browser open failed",
                "micro_response": "I resolved the page, but couldn't open it.",
                "full_response": "The destination URL was resolved, but the browser open action failed.",
            }
        if reason == BrowserOpenFailureReason.EXPLICIT_BROWSER_UNAVAILABLE:
            return {
                "bearing_title": "Requested browser unavailable",
                "micro_response": "That browser isn't available here.",
                "full_response": "I resolved the destination, but the requested browser target isn't available in this environment.",
            }
        return {
            "bearing_title": "Browser destination unresolved",
            "micro_response": "I couldn't resolve that site.",
            "full_response": "I couldn't resolve a browser destination for that request.",
        }

    def _looks_like_search_request(self, lower: str) -> bool:
        if not SEARCH_PREFIX_PATTERN.match(lower):
            return False
        return any(token in lower for token in {"youtube", "google", "openai", "chatgpt", "github", "web", "internet"})

    def _looks_like_open_destination_request(self, lower: str) -> bool:
        if not OPEN_PREFIX_PATTERN.match(lower):
            return False
        return any(re.search(pattern, lower) for pattern in TRAILING_BROWSER_MARKERS) or any(
            re.search(pattern, lower) for pattern in TRAILING_SITE_MARKERS
        )

    def _has_personal_scope(self, lower: str) -> bool:
        return bool(re.search(r"\b(?:my|personal|my personal)\b", lower))

    def _extract_destination_phrase(self, lower: str) -> str:
        candidate = OPEN_PREFIX_PATTERN.sub("", lower).strip()
        for pattern in [*TRAILING_BROWSER_MARKERS, *TRAILING_SITE_MARKERS]:
            candidate = re.sub(pattern, "", candidate).strip()
        candidate = re.sub(r"^(?:the\s+)", "", candidate).strip()
        candidate = re.sub(r"^(?:my personal|personal|my)\s+", "", candidate).strip()
        candidate = re.sub(r"\s+(?:please|for me)$", "", candidate).strip()
        candidate = re.sub(r"\s+", " ", candidate).strip(" .,:;!?")
        return candidate

    def _is_excluded_destination_phrase(self, candidate: str) -> bool:
        normalized = normalize_phrase(candidate)
        return normalized in NON_BROWSER_DESTINATION_PHRASES or normalized.endswith(" settings")
