from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import re
from typing import Any
from urllib.parse import quote_plus
from urllib.parse import urlparse

from stormhelm.core.intelligence.language import normalize_phrase
from stormhelm.core.subsystem_latency import get_subsystem_latency_profile


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


class BrowserSearchFailureReason(StrEnum):
    SEARCH_PROVIDER_UNRESOLVED = "search_provider_unresolved"
    SEARCH_QUERY_MISSING = "search_query_missing"
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

    def host(self) -> str | None:
        parsed = urlparse(self.url)
        host = str(parsed.netloc or "").strip().lower()
        return host or None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "url": self.url,
            "aliases": list(self.aliases),
            "personal_aliases": list(self.personal_aliases),
            "requires_signed_in_session": self.requires_signed_in_session,
        }


@dataclass(frozen=True, slots=True)
class KnownWebSearchProvider:
    key: str
    title: str
    url_template: str
    aliases: tuple[str, ...]

    def build_url(self, query: str) -> str:
        return self.url_template.format(query=quote_plus(query))

    def search_title(self) -> str:
        return "Web search" if self.key == "web" else f"{self.title} search"

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "url_template": self.url_template,
            "aliases": list(self.aliases),
        }


@dataclass(frozen=True, slots=True)
class KnownBrowserTarget:
    key: str
    title: str
    aliases: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "aliases": list(self.aliases),
        }


@dataclass(slots=True)
class BrowserDestinationRequest:
    raw_text: str
    normalized_text: str
    intent_type: BrowserIntentType
    destination_phrase: str
    scope: DestinationScope
    open_target: str
    raw_destination_phrase: str = ""
    browser_preference: str = "default"
    explicit_browser: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_text": self.raw_text,
            "normalized_text": self.normalized_text,
            "intent_type": self.intent_type.value,
            "destination_phrase": self.destination_phrase,
            "raw_destination_phrase": self.raw_destination_phrase,
            "scope": self.scope.value,
            "open_target": self.open_target,
            "browser_preference": self.browser_preference,
            "explicit_browser": self.explicit_browser,
        }


@dataclass(slots=True)
class BrowserSearchRequest:
    raw_text: str
    normalized_text: str
    intent_type: BrowserIntentType
    provider_key: str | None
    provider_phrase: str | None
    query: str
    open_target: str
    browser_preference: str = "default"
    explicit_browser: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_text": self.raw_text,
            "normalized_text": self.normalized_text,
            "intent_type": self.intent_type.value,
            "provider_key": self.provider_key,
            "provider_phrase": self.provider_phrase,
            "query": self.query,
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
    display_title: str | None = None
    resolution_kind: str | None = None
    site_domain: str | None = None
    matched_alias: str | None = None
    failure_reason: BrowserOpenFailureReason | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "request": self.request.to_dict(),
            "destination": self.destination.to_dict() if self.destination is not None else None,
            "url": self.url,
            "display_title": self.display_title,
            "resolution_kind": self.resolution_kind,
            "site_domain": self.site_domain,
            "matched_alias": self.matched_alias,
            "failure_reason": self.failure_reason.value if self.failure_reason is not None else None,
            "notes": list(self.notes),
        }


@dataclass(slots=True)
class SearchResolutionResult:
    success: bool
    request: BrowserSearchRequest
    provider: KnownWebSearchProvider | None = None
    url: str | None = None
    display_title: str | None = None
    resolution_kind: str | None = None
    site_domain: str | None = None
    failure_reason: BrowserSearchFailureReason | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "request": self.request.to_dict(),
            "provider": self.provider.to_dict() if self.provider is not None else None,
            "url": self.url,
            "display_title": self.display_title,
            "resolution_kind": self.resolution_kind,
            "site_domain": self.site_domain,
            "failure_reason": self.failure_reason.value if self.failure_reason is not None else None,
            "notes": list(self.notes),
        }


@dataclass(slots=True)
class BrowserOpenPlan:
    tool_name: str | None
    tool_arguments: dict[str, Any]
    response_contract: dict[str, str]
    open_target: str
    latency_mode: str = "plan_first"
    cache_policy_id: str = "browser_known_destination_cache"
    ack_stage: str = "open_requested"
    external_load_blocking: bool = False
    load_verification_required: bool = True
    verification_stage: str = "separate_adapter_evidence"
    provider_fallback_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "tool_arguments": dict(self.tool_arguments),
            "response_contract": dict(self.response_contract),
            "open_target": self.open_target,
            "latency_mode": self.latency_mode,
            "cache_policy_id": self.cache_policy_id,
            "ack_stage": self.ack_stage,
            "external_load_blocking": self.external_load_blocking,
            "load_verification_required": self.load_verification_required,
            "verification_stage": self.verification_stage,
            "provider_fallback_used": self.provider_fallback_used,
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
    KnownWebDestination(key="youtube", title="YouTube", url="https://www.youtube.com/", aliases=("youtube",)),
    KnownWebDestination(
        key="gmail",
        title="Gmail",
        url="https://mail.google.com/mail/u/0/#inbox",
        aliases=("gmail",),
        personal_aliases=("email", "mail", "inbox", "my gmail"),
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
    KnownWebDestination(key="chatgpt", title="ChatGPT", url="https://chatgpt.com/", aliases=("chatgpt", "chat gpt")),
    KnownWebDestination(
        key="openai",
        title="OpenAI",
        url="https://openai.com/",
        aliases=("openai", "open ai", "openai site", "open ai site"),
    ),
    KnownWebDestination(
        key="github",
        title="GitHub",
        url="https://github.com/",
        aliases=("github", "git hub", "github site"),
    ),
    KnownWebDestination(
        key="google_docs",
        title="Google Docs",
        url="https://docs.google.com/document/",
        aliases=("google docs", "google documents"),
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
    KnownWebDestination(key="maps", title="Google Maps", url="https://maps.google.com/", aliases=("maps", "google maps")),
    KnownWebDestination(key="reddit", title="Reddit", url="https://www.reddit.com/", aliases=("reddit",)),
    KnownWebDestination(
        key="outlook_web",
        title="Outlook",
        url="https://outlook.office.com/mail/",
        aliases=("outlook", "outlook web"),
        personal_aliases=("outlook inbox",),
        requires_signed_in_session=True,
    ),
    KnownWebDestination(key="dropbox", title="Dropbox", url="https://www.dropbox.com/home", aliases=("dropbox",), requires_signed_in_session=True),
    KnownWebDestination(
        key="onedrive_web",
        title="OneDrive",
        url="https://onedrive.live.com/",
        aliases=("onedrive", "one drive"),
        personal_aliases=("my onedrive",),
        requires_signed_in_session=True,
    ),
    KnownWebDestination(key="amazon", title="Amazon", url="https://www.amazon.com/", aliases=("amazon",)),
    KnownWebDestination(key="ebay", title="eBay", url="https://www.ebay.com/", aliases=("ebay", "e bay")),
    KnownWebDestination(key="etsy", title="Etsy", url="https://www.etsy.com/", aliases=("etsy",)),
    KnownWebDestination(key="walmart", title="Walmart", url="https://www.walmart.com/", aliases=("walmart",)),
    KnownWebDestination(key="best_buy", title="Best Buy", url="https://www.bestbuy.com/", aliases=("best buy", "bestbuy")),
    KnownWebDestination(key="spotify", title="Spotify", url="https://open.spotify.com/", aliases=("spotify",)),
    KnownWebDestination(key="soundcloud", title="SoundCloud", url="https://soundcloud.com/", aliases=("soundcloud", "sound cloud")),
    KnownWebDestination(key="twitch", title="Twitch", url="https://www.twitch.tv/", aliases=("twitch",)),
    KnownWebDestination(key="hacker_news", title="Hacker News", url="https://news.ycombinator.com/", aliases=("hacker news", "hn")),
    KnownWebDestination(key="quora", title="Quora", url="https://www.quora.com/", aliases=("quora",)),
    KnownWebDestination(key="stack_overflow", title="Stack Overflow", url="https://stackoverflow.com/", aliases=("stack overflow", "stackoverflow")),
    KnownWebDestination(key="booking", title="Booking.com", url="https://www.booking.com/", aliases=("booking", "booking.com")),
    KnownWebDestination(key="tripadvisor", title="Tripadvisor", url="https://www.tripadvisor.com/", aliases=("tripadvisor", "trip advisor")),
    KnownWebDestination(key="airbnb", title="Airbnb", url="https://www.airbnb.com/", aliases=("airbnb", "air bnb")),
    KnownWebDestination(key="expedia", title="Expedia", url="https://www.expedia.com/", aliases=("expedia",)),
    KnownWebDestination(
        key="python_docs",
        title="Python docs",
        url="https://docs.python.org/",
        aliases=("python docs", "python documentation", "python docs site"),
    ),
    KnownWebDestination(key="mdn", title="MDN", url="https://developer.mozilla.org/", aliases=("mdn", "mozilla developer network")),
)


KNOWN_WEB_SEARCH_PROVIDERS: tuple[KnownWebSearchProvider, ...] = (
    KnownWebSearchProvider(
        key="youtube",
        title="YouTube",
        url_template="https://www.youtube.com/results?search_query={query}",
        aliases=("youtube",),
    ),
    KnownWebSearchProvider(
        key="github",
        title="GitHub",
        url_template="https://github.com/search?q={query}",
        aliases=("github", "git hub"),
    ),
    KnownWebSearchProvider(
        key="reddit",
        title="Reddit",
        url_template="https://www.reddit.com/search/?q={query}",
        aliases=("reddit",),
    ),
    KnownWebSearchProvider(
        key="stack_overflow",
        title="Stack Overflow",
        url_template="https://stackoverflow.com/search?q={query}",
        aliases=("stack overflow", "stackoverflow"),
    ),
    KnownWebSearchProvider(
        key="wikipedia",
        title="Wikipedia",
        url_template="https://en.wikipedia.org/w/index.php?search={query}",
        aliases=("wikipedia", "wiki"),
    ),
    KnownWebSearchProvider(
        key="amazon",
        title="Amazon",
        url_template="https://www.amazon.com/s?k={query}",
        aliases=("amazon",),
    ),
    KnownWebSearchProvider(
        key="ebay",
        title="eBay",
        url_template="https://www.ebay.com/sch/i.html?_nkw={query}",
        aliases=("ebay", "e bay"),
    ),
    KnownWebSearchProvider(
        key="etsy",
        title="Etsy",
        url_template="https://www.etsy.com/search?q={query}",
        aliases=("etsy",),
    ),
    KnownWebSearchProvider(
        key="walmart",
        title="Walmart",
        url_template="https://www.walmart.com/search?q={query}",
        aliases=("walmart",),
    ),
    KnownWebSearchProvider(
        key="best_buy",
        title="Best Buy",
        url_template="https://www.bestbuy.com/site/searchpage.jsp?st={query}",
        aliases=("best buy", "bestbuy"),
    ),
    KnownWebSearchProvider(
        key="linkedin",
        title="LinkedIn",
        url_template="https://www.linkedin.com/search/results/all/?keywords={query}",
        aliases=("linkedin", "linked in"),
    ),
    KnownWebSearchProvider(
        key="x",
        title="X",
        url_template="https://x.com/search?q={query}&src=typed_query",
        aliases=("x", "twitter", "x twitter"),
    ),
    KnownWebSearchProvider(
        key="mdn",
        title="MDN",
        url_template="https://developer.mozilla.org/en-US/search?q={query}",
        aliases=("mdn", "mozilla developer network"),
    ),
    KnownWebSearchProvider(
        key="npm",
        title="npm",
        url_template="https://www.npmjs.com/search?q={query}",
        aliases=("npm",),
    ),
    KnownWebSearchProvider(
        key="pypi",
        title="PyPI",
        url_template="https://pypi.org/search/?q={query}",
        aliases=("pypi", "py pi"),
    ),
    KnownWebSearchProvider(
        key="arxiv",
        title="arXiv",
        url_template="https://arxiv.org/search/?query={query}&searchtype=all",
        aliases=("arxiv", "ar x i v"),
    ),
    KnownWebSearchProvider(
        key="pubmed",
        title="PubMed",
        url_template="https://pubmed.ncbi.nlm.nih.gov/?term={query}",
        aliases=("pubmed", "pub med"),
    ),
    KnownWebSearchProvider(
        key="python_docs",
        title="Python docs",
        url_template="https://docs.python.org/3/search.html?q={query}",
        aliases=("python docs", "python documentation"),
    ),
    KnownWebSearchProvider(
        key="spotify",
        title="Spotify",
        url_template="https://open.spotify.com/search/{query}",
        aliases=("spotify",),
    ),
    KnownWebSearchProvider(
        key="soundcloud",
        title="SoundCloud",
        url_template="https://soundcloud.com/search?q={query}",
        aliases=("soundcloud", "sound cloud"),
    ),
    KnownWebSearchProvider(
        key="twitch",
        title="Twitch",
        url_template="https://www.twitch.tv/search?term={query}",
        aliases=("twitch",),
    ),
    KnownWebSearchProvider(
        key="imdb",
        title="IMDb",
        url_template="https://www.imdb.com/find/?q={query}",
        aliases=("imdb", "i m d b"),
    ),
    KnownWebSearchProvider(
        key="hacker_news",
        title="Hacker News",
        url_template="https://hn.algolia.com/?q={query}",
        aliases=("hacker news", "hn"),
    ),
    KnownWebSearchProvider(
        key="quora",
        title="Quora",
        url_template="https://www.quora.com/search?q={query}",
        aliases=("quora",),
    ),
    KnownWebSearchProvider(
        key="stack_exchange",
        title="Stack Exchange",
        url_template="https://stackexchange.com/search?q={query}",
        aliases=("stack exchange", "stackexchange"),
    ),
    KnownWebSearchProvider(
        key="booking",
        title="Booking.com",
        url_template="https://www.booking.com/searchresults.html?ss={query}",
        aliases=("booking", "booking.com"),
    ),
    KnownWebSearchProvider(
        key="tripadvisor",
        title="Tripadvisor",
        url_template="https://www.tripadvisor.com/Search?q={query}",
        aliases=("tripadvisor", "trip advisor"),
    ),
    KnownWebSearchProvider(
        key="airbnb",
        title="Airbnb",
        url_template="https://www.airbnb.com/s/{query}/homes",
        aliases=("airbnb", "air bnb"),
    ),
    KnownWebSearchProvider(
        key="expedia",
        title="Expedia",
        url_template="https://www.expedia.com/Hotel-Search?destination={query}",
        aliases=("expedia",),
    ),
    KnownWebSearchProvider(
        key="web",
        title="Web",
        url_template="https://www.google.com/search?q={query}",
        aliases=("web", "the web", "google"),
    ),
)


KNOWN_BROWSER_TARGETS: tuple[KnownBrowserTarget, ...] = (
    KnownBrowserTarget(key="chrome", title="Google Chrome", aliases=("chrome", "google chrome")),
    KnownBrowserTarget(key="firefox", title="Firefox", aliases=("firefox", "mozilla firefox")),
    KnownBrowserTarget(key="edge", title="Microsoft Edge", aliases=("edge", "msedge", "microsoft edge")),
    KnownBrowserTarget(key="brave", title="Brave", aliases=("brave", "brave browser")),
    KnownBrowserTarget(key="opera", title="Opera", aliases=("opera", "opera browser")),
    KnownBrowserTarget(key="vivaldi", title="Vivaldi", aliases=("vivaldi", "vivaldi browser")),
)


LOCAL_SEARCH_PROVIDER_BLOCKLIST = frozenset(
    {
        "document",
        "documents",
        "docs",
        "documentation",
        "download",
        "downloads",
        "desktop",
        "file",
        "files",
        "folder",
        "folders",
        "directory",
        "directories",
        "repo",
        "repository",
        "codebase",
        "source",
        "src",
        "workspace",
        "workspaces",
        "project",
        "projects",
        "note",
        "notes",
        "pdf",
        "pdfs",
        "screenshot",
        "screenshots",
        "picture",
        "pictures",
        "image",
        "images",
        "video",
        "videos",
        "music",
        "clipboard",
        "selection",
    }
)

FILE_STYLE_DOMAIN_SUFFIX_BLOCKLIST = frozenset(
    {
        "7z",
        "bat",
        "bmp",
        "c",
        "cfg",
        "cmd",
        "cpp",
        "css",
        "csv",
        "doc",
        "docx",
        "flac",
        "gif",
        "go",
        "h",
        "hpp",
        "html",
        "ini",
        "jar",
        "java",
        "jpeg",
        "jpg",
        "js",
        "json",
        "jsx",
        "log",
        "md",
        "mkv",
        "mov",
        "mp3",
        "mp4",
        "pdf",
        "png",
        "ppt",
        "pptx",
        "ps1",
        "py",
        "rar",
        "rs",
        "sh",
        "sql",
        "svg",
        "tar",
        "toml",
        "ts",
        "tsx",
        "txt",
        "wav",
        "webp",
        "xls",
        "xlsx",
        "xml",
        "yaml",
        "yml",
        "zip",
    }
)


class BrowserDestinationResolver:
    def __init__(self) -> None:
        self._destinations = KNOWN_BROWSER_DESTINATIONS
        self._search_providers = KNOWN_WEB_SEARCH_PROVIDERS
        self._browser_targets = KNOWN_BROWSER_TARGETS

        self._destination_general_alias_index: dict[str, tuple[KnownWebDestination, str]] = {}
        self._destination_personal_alias_index: dict[str, tuple[KnownWebDestination, str]] = {}
        for destination in self._destinations:
            for alias in (destination.key, *destination.aliases):
                normalized_alias = normalize_phrase(alias)
                if normalized_alias:
                    self._destination_general_alias_index.setdefault(normalized_alias, (destination, normalized_alias))
                    self._destination_personal_alias_index.setdefault(normalized_alias, (destination, normalized_alias))
            for alias in destination.personal_aliases:
                normalized_alias = normalize_phrase(alias)
                if normalized_alias:
                    self._destination_personal_alias_index.setdefault(normalized_alias, (destination, normalized_alias))

        self._search_provider_alias_index: dict[str, KnownWebSearchProvider] = {}
        self._search_provider_key_index: dict[str, KnownWebSearchProvider] = {}
        for provider in self._search_providers:
            self._search_provider_key_index[provider.key] = provider
            for alias in (provider.key, *provider.aliases):
                normalized_alias = normalize_phrase(alias)
                if normalized_alias:
                    self._search_provider_alias_index.setdefault(normalized_alias, provider)

        self._browser_target_alias_index: dict[str, KnownBrowserTarget] = {}
        browser_aliases: list[str] = []
        for target in self._browser_targets:
            self._browser_target_alias_index[target.key] = target
            browser_aliases.append(target.key)
            for alias in target.aliases:
                normalized_alias = normalize_phrase(alias)
                if normalized_alias:
                    self._browser_target_alias_index.setdefault(normalized_alias, target)
                    browser_aliases.append(alias)
        escaped_browser_aliases = "|".join(re.escape(alias) for alias in sorted(set(browser_aliases), key=len, reverse=True))
        self._normalized_browser_target_suffix = re.compile(
            rf"\s+(?:in|using|with)\s+(?:the\s+)?(?:{escaped_browser_aliases})(?:\s+browser)?\s*$"
        )
        self._raw_browser_target_suffix = re.compile(
            rf"\s+(?:in|using|with)\s+(?:the\s+)?(?:{escaped_browser_aliases})(?:\s+browser)?\s*$",
            flags=re.IGNORECASE,
        )
        self._normalized_external_suffix = re.compile(
            r"\s+(?:in\s+(?:a\s+|the\s+)?browser|using\s+(?:a\s+|the\s+)?browser|externally|outside\s+(?:stormhelm|the deck))\s*$"
        )
        self._raw_external_suffix = re.compile(
            r"\s+(?:in\s+(?:a\s+|the\s+)?browser|using\s+(?:a\s+|the\s+)?browser|externally|outside\s+(?:Stormhelm|the Deck))\s*$",
            flags=re.IGNORECASE,
        )
        self._normalized_deck_suffix = re.compile(
            r"\s+(?:in\s+(?:the\s+)?deck|inside\s+(?:the\s+)?deck|inside\s+stormhelm|in\s+stormhelm)\s*$"
        )
        self._raw_deck_suffix = re.compile(
            r"\s+(?:in\s+(?:the\s+)?Deck|inside\s+(?:the\s+)?Deck|inside\s+Stormhelm|in\s+Stormhelm)\s*$",
            flags=re.IGNORECASE,
        )

    def intent_type(self, text: str) -> BrowserIntentType | None:
        normalized = normalize_phrase(text)
        if not normalized:
            return None
        stripped = self._strip_trailing_browser_clauses(normalized)
        if self._looks_like_search_request(stripped):
            return BrowserIntentType.SEARCH_REQUEST
        if self._looks_like_open_destination_request(normalized, stripped_text=stripped):
            return BrowserIntentType.OPEN_DESTINATION
        return None

    def parse(self, text: str, *, surface_mode: str = "ghost") -> BrowserDestinationRequest | None:
        normalized = normalize_phrase(text)
        if not normalized:
            return None
        stripped_text, browser_preference, explicit_browser = self._extract_browser_target(normalized)
        stripped_text = self._strip_trailing_browser_clauses(stripped_text)
        if not self._looks_like_open_destination_request(normalized, stripped_text=stripped_text):
            return None
        destination_phrase = self._extract_destination_phrase(stripped_text)
        if not destination_phrase:
            return None
        raw_without_browser = self._strip_trailing_browser_clauses_raw(text)
        raw_destination_phrase = self._extract_destination_phrase_raw(raw_without_browser) or destination_phrase
        scope = DestinationScope.PERSONAL if self._is_personal_scope(stripped_text) else DestinationScope.GENERAL
        open_target = self._resolve_open_target(
            normalized_text=normalized,
            stripped_text=stripped_text,
            surface_mode=surface_mode,
            explicit_browser=explicit_browser,
        )
        return BrowserDestinationRequest(
            raw_text=text,
            normalized_text=normalized,
            intent_type=BrowserIntentType.OPEN_DESTINATION,
            destination_phrase=destination_phrase,
            scope=scope,
            open_target=open_target,
            raw_destination_phrase=raw_destination_phrase,
            browser_preference=browser_preference,
            explicit_browser=explicit_browser,
        )

    def parse_search(self, text: str, *, surface_mode: str = "ghost") -> BrowserSearchRequest | None:
        normalized = normalize_phrase(text)
        if not normalized:
            return None
        stripped_text, browser_preference, explicit_browser = self._extract_browser_target(normalized)
        stripped_text = self._strip_trailing_browser_clauses(stripped_text)
        if not self._looks_like_search_request(stripped_text):
            return None
        raw_without_browser = self._strip_trailing_browser_clauses_raw(text)
        provider_key, provider_phrase, query = self._extract_search_provider_and_query(
            raw_text=raw_without_browser,
            normalized_text=stripped_text,
        )
        if provider_key is None and provider_phrase is None and not query:
            return None
        open_target = self._resolve_open_target(
            normalized_text=normalized,
            stripped_text=stripped_text,
            surface_mode=surface_mode,
            explicit_browser=explicit_browser,
        )
        return BrowserSearchRequest(
            raw_text=text,
            normalized_text=normalized,
            intent_type=BrowserIntentType.SEARCH_REQUEST,
            provider_key=provider_key,
            provider_phrase=provider_phrase,
            query=query,
            open_target=open_target,
            browser_preference=browser_preference,
            explicit_browser=explicit_browser,
        )

    def resolve(self, request: BrowserDestinationRequest) -> DestinationResolutionResult:
        lookup = self._destination_personal_alias_index if request.scope == DestinationScope.PERSONAL else self._destination_general_alias_index
        matched = lookup.get(request.destination_phrase)
        if matched is None and request.scope == DestinationScope.PERSONAL:
            matched = self._destination_general_alias_index.get(request.destination_phrase)
        if matched is not None:
            destination, matched_alias = matched
            host = destination.host()
            site_domain = None
            if host:
                site_domain = host[4:] if host.startswith("www.") else host
            return DestinationResolutionResult(
                success=True,
                request=request,
                destination=destination,
                url=destination.url,
                display_title=destination.title,
                resolution_kind="known_destination",
                site_domain=site_domain,
                matched_alias=matched_alias,
                notes=[f"known destination mapped to {destination.key}"],
            )
        direct_domain = self._resolve_direct_domain_destination(request.raw_destination_phrase or request.destination_phrase)
        if direct_domain is not None:
            url, site_domain, display_title = direct_domain
            return DestinationResolutionResult(
                success=True,
                request=request,
                url=url,
                display_title=display_title,
                resolution_kind="direct_domain",
                site_domain=site_domain,
                notes=[f"direct domain resolved to {site_domain}"],
            )
        return DestinationResolutionResult(
            success=False,
            request=request,
            failure_reason=BrowserOpenFailureReason.DESTINATION_UNRESOLVED,
            notes=["browser destination unresolved"],
        )

    def resolve_search(self, request: BrowserSearchRequest) -> SearchResolutionResult:
        if not request.query.strip():
            return SearchResolutionResult(
                success=False,
                request=request,
                failure_reason=BrowserSearchFailureReason.SEARCH_QUERY_MISSING,
                notes=["browser search query missing"],
            )
        provider = self._provider_for_key(request.provider_key)
        if provider is not None:
            return SearchResolutionResult(
                success=True,
                request=request,
                provider=provider,
                url=provider.build_url(request.query),
                display_title=provider.search_title(),
                resolution_kind="native_provider",
                notes=[f"native search provider mapped to {provider.key}"],
            )
        site_domain = self._site_search_domain_for_phrase(request.provider_phrase or request.provider_key or "")
        if site_domain:
            web_provider = self._search_provider_key_index["web"]
            return SearchResolutionResult(
                success=True,
                request=request,
                provider=web_provider,
                url=web_provider.build_url(f"site:{site_domain} {request.query}".strip()),
                display_title=f"{self._display_name_for_provider_phrase(request.provider_phrase or site_domain)} search",
                resolution_kind="site_search",
                site_domain=site_domain,
                notes=[f"site search fallback mapped to {site_domain}"],
            )
        return SearchResolutionResult(
            success=False,
            request=request,
            failure_reason=BrowserSearchFailureReason.SEARCH_PROVIDER_UNRESOLVED,
            notes=["search provider unresolved"],
        )

    def build_open_plan(self, resolution: DestinationResolutionResult) -> BrowserOpenPlan:
        if not resolution.success or resolution.url is None:
            raise ValueError("A successful destination resolution is required before building an open plan.")
        title = resolution.display_title or (resolution.destination.title if resolution.destination is not None else "Browser destination")
        response_contract = self.response_contract_for_success(resolution)
        tool_name = "deck_open_url" if resolution.request.open_target == "deck" else "external_open_url"
        latency_profile = get_subsystem_latency_profile("browser_destination")
        tool_arguments: dict[str, Any] = {
            "url": resolution.url,
            "label": title,
            "response_contract": dict(response_contract),
            "ack_stage": "open_requested",
            "external_load_blocking": False,
            "verification_stage": "separate_adapter_evidence",
            "provider_fallback_allowed": latency_profile.provider_fallback_allowed,
            "latency_mode": latency_profile.latency_mode.value,
            "cache_policy_id": latency_profile.cache_policy_id,
        }
        if tool_name == "external_open_url" and resolution.request.browser_preference != "default":
            tool_arguments["browser_target"] = resolution.request.browser_preference
        return BrowserOpenPlan(
            tool_name=tool_name,
            tool_arguments=tool_arguments,
            response_contract=response_contract,
            open_target=resolution.request.open_target,
            latency_mode=latency_profile.latency_mode.value,
            cache_policy_id=latency_profile.cache_policy_id,
            external_load_blocking=False,
            load_verification_required=True,
            provider_fallback_used=False,
        )

    def build_search_open_plan(self, resolution: SearchResolutionResult) -> BrowserOpenPlan:
        if resolution.provider is None or resolution.url is None:
            raise ValueError("A successful search resolution is required before building an open plan.")
        response_contract = self.response_contract_for_search_success(resolution)
        tool_name = "deck_open_url" if resolution.request.open_target == "deck" else "external_open_url"
        latency_profile = get_subsystem_latency_profile("browser_destination")
        tool_arguments: dict[str, Any] = {
            "url": resolution.url,
            "label": resolution.display_title or resolution.provider.search_title(),
            "response_contract": dict(response_contract),
            "ack_stage": "open_requested",
            "external_load_blocking": False,
            "verification_stage": "separate_adapter_evidence",
            "provider_fallback_allowed": latency_profile.provider_fallback_allowed,
            "latency_mode": latency_profile.latency_mode.value,
            "cache_policy_id": latency_profile.cache_policy_id,
        }
        if tool_name == "external_open_url" and resolution.request.browser_preference != "default":
            tool_arguments["browser_target"] = resolution.request.browser_preference
        return BrowserOpenPlan(
            tool_name=tool_name,
            tool_arguments=tool_arguments,
            response_contract=response_contract,
            open_target=resolution.request.open_target,
            latency_mode=latency_profile.latency_mode.value,
            cache_policy_id=latency_profile.cache_policy_id,
            external_load_blocking=False,
            load_verification_required=True,
            provider_fallback_used=False,
        )

    def response_contract_for_success(self, resolution: DestinationResolutionResult) -> dict[str, str]:
        title = resolution.display_title or (resolution.destination.title if resolution.destination is not None else "Browser destination")
        return self._success_response_contract(title, open_target=resolution.request.open_target)

    def response_contract_for_failure(self, reason: BrowserOpenFailureReason) -> dict[str, str]:
        if reason == BrowserOpenFailureReason.AMBIGUOUS_DESTINATION:
            return self._response_contract(
                title="Browser destination ambiguous",
                micro="I need a more specific site.",
                full="That browser destination matched more than one site.",
            )
        if reason == BrowserOpenFailureReason.BROWSER_OPEN_UNAVAILABLE:
            return self._response_contract(
                title="Browser opening unavailable",
                micro="Browser opening isn't available here.",
                full="Browser opening isn't available in the current environment.",
            )
        if reason == BrowserOpenFailureReason.BROWSER_OPEN_FAILED:
            return self._response_contract(
                title="Browser open failed",
                micro="I resolved the page, but couldn't open it.",
                full="The destination URL was resolved, but the browser open action failed.",
            )
        if reason == BrowserOpenFailureReason.EXPLICIT_BROWSER_UNAVAILABLE:
            return self._response_contract(
                title="Requested browser unavailable",
                micro="I couldn't use that browser target.",
                full="The destination was resolved, but the requested browser target wasn't available.",
            )
        return self._response_contract(
            title="Browser destination unresolved",
            micro="I couldn't resolve that site.",
            full="I couldn't resolve a browser destination for that request.",
        )

    def response_contract_for_search_success(self, resolution: SearchResolutionResult) -> dict[str, str]:
        title = resolution.display_title or (resolution.provider.search_title() if resolution.provider is not None else "Search")
        return self.response_contract_for_search_title(title, open_target=resolution.request.open_target)

    def response_contract_for_search_title(self, title: str, *, open_target: str) -> dict[str, str]:
        return self._success_response_contract(title, open_target=open_target)

    def _success_response_contract(self, title: str, *, open_target: str) -> dict[str, str]:
        if open_target == "deck":
            return self._response_contract(
                title=f"{title} queued",
                micro=f"Queued {title} for the Deck browser.",
                full=f"Queued {title} for the Deck browser.",
            )
        return self._response_contract(
            title=f"{title} requested",
            micro=f"Requested that {title} open externally.",
            full=f"Requested that {title} open externally.",
        )

    def response_contract_for_search_failure(self, reason: BrowserSearchFailureReason) -> dict[str, str]:
        if reason == BrowserSearchFailureReason.SEARCH_QUERY_MISSING:
            return self._response_contract(
                title="Search query missing",
                micro="I need a search query.",
                full="I couldn't open a browser search because the search query was missing.",
            )
        if reason == BrowserSearchFailureReason.BROWSER_OPEN_UNAVAILABLE:
            return self._response_contract(
                title="Browser opening unavailable",
                micro="Browser opening isn't available here.",
                full="Browser opening isn't available in the current environment.",
            )
        if reason == BrowserSearchFailureReason.BROWSER_OPEN_FAILED:
            return self._response_contract(
                title="Browser open failed",
                micro="I resolved the page, but couldn't open it.",
                full="The destination URL was resolved, but the browser open action failed.",
            )
        if reason == BrowserSearchFailureReason.EXPLICIT_BROWSER_UNAVAILABLE:
            return self._response_contract(
                title="Requested browser unavailable",
                micro="I couldn't use that browser target.",
                full="The search URL was resolved, but the requested browser target wasn't available.",
            )
        return self._response_contract(
            title="Browser search unresolved",
            micro="I couldn't determine the search route.",
            full="I couldn't determine which browser search route to use for that request.",
        )

    def _extract_browser_target(self, normalized_text: str) -> tuple[str, str, bool]:
        match = self._normalized_browser_target_suffix.search(normalized_text)
        if not match:
            return normalized_text, "default", False
        alias = normalize_phrase(match.group(0))
        alias = re.sub(r"^(?:in|using|with)\s+(?:the\s+)?", "", alias).strip()
        alias = re.sub(r"\s+browser$", "", alias).strip()
        target = self._browser_target_alias_index.get(alias)
        if target is None:
            return normalized_text, "default", False
        stripped = normalized_text[: match.start()].strip()
        return stripped, target.key, True

    def _strip_trailing_browser_clauses(self, text: str) -> str:
        stripped = self._normalized_external_suffix.sub("", text).strip()
        stripped = self._normalized_deck_suffix.sub("", stripped).strip()
        return stripped

    def _strip_trailing_browser_clauses_raw(self, text: str) -> str:
        stripped = self._raw_browser_target_suffix.sub("", str(text or "")).strip()
        stripped = self._raw_external_suffix.sub("", stripped).strip()
        stripped = self._raw_deck_suffix.sub("", stripped).strip()
        return stripped

    def _looks_like_open_destination_request(self, normalized_text: str, *, stripped_text: str) -> bool:
        if not re.match(r"^(?:open|show|bring up|pull up|go to|navigate to)\s+", stripped_text):
            return False
        destination_phrase = self._extract_destination_phrase(stripped_text)
        if not destination_phrase:
            return False
        if self._destination_for_phrase(destination_phrase, include_personal=True) is not None:
            return True
        if self._looks_like_direct_domain_destination(destination_phrase):
            return True
        if self._has_browser_surface_cue(normalized_text) and self._looks_like_webish_unknown_destination(
            destination_phrase,
            stripped_text=stripped_text,
        ):
            return True
        return False

    def _looks_like_search_request(self, stripped_text: str) -> bool:
        if re.match(r"^(?:look up|lookup|search the web for|search web for|search google for|google)\s+.+", stripped_text):
            return True
        match = re.match(r"^search\s+(.+?)(?:\s+for\s+(.+))?$", stripped_text)
        if not match:
            return False
        provider_phrase = normalize_phrase(match.group(1) or "")
        query = normalize_phrase(match.group(2) or "")
        if not provider_phrase or provider_phrase in LOCAL_SEARCH_PROVIDER_BLOCKLIST:
            return False
        if self._provider_for_key(provider_phrase) is not None:
            return True
        if self._site_search_domain_for_phrase(provider_phrase) is not None:
            return True
        if self._looks_like_domain(provider_phrase):
            return True
        return bool(query)

    def _extract_destination_phrase(self, stripped_text: str) -> str:
        candidate = re.sub(r"^(?:open|show|bring up|pull up|go to|navigate to)\s+", "", stripped_text).strip()
        candidate = re.sub(r"^(?:the\s+)", "", candidate).strip()
        candidate = re.sub(r"^(?:my\s+personal|my|personal)\s+", "", candidate).strip()
        candidate = re.sub(r"\s+(?:site|website|web site|homepage|home page|page)$", "", candidate).strip()
        return normalize_phrase(candidate)

    def _extract_destination_phrase_raw(self, stripped_text: str) -> str:
        candidate = re.sub(r"^(?:open|show|bring up|pull up|go to|navigate to)\s+", "", str(stripped_text or "").strip(), flags=re.IGNORECASE)
        candidate = re.sub(r"^(?:the\s+)", "", candidate, flags=re.IGNORECASE).strip()
        candidate = re.sub(r"^(?:my\s+personal|my|personal)\s+", "", candidate, flags=re.IGNORECASE).strip()
        candidate = re.sub(r"\s+(?:site|website|web site|homepage|home page|page)$", "", candidate, flags=re.IGNORECASE).strip()
        return " ".join(candidate.split()).strip(" .")

    def _extract_search_provider_and_query(self, *, raw_text: str, normalized_text: str) -> tuple[str | None, str | None, str]:
        raw_text = " ".join(str(raw_text or "").split()).strip(" .")
        normalized_text = normalize_phrase(normalized_text)
        del normalized_text
        web_match = re.match(r"^(?:look up|lookup|search the web for|search web for|search google for|google)\s+(.+)$", raw_text, flags=re.IGNORECASE)
        if web_match:
            query = " ".join(str(web_match.group(1) or "").split()).strip(" .")
            return "web", "web", query
        search_match = re.match(r"^search\s+(.+?)(?:\s+for\s+(.+))?$", raw_text, flags=re.IGNORECASE)
        if not search_match:
            return None, None, ""
        provider_raw = " ".join(str(search_match.group(1) or "").split()).strip(" .")
        query = " ".join(str(search_match.group(2) or "").split()).strip(" .")
        provider_phrase = normalize_phrase(provider_raw)
        if not provider_phrase:
            return None, None, query
        canonical_provider = self._canonical_search_provider_key(provider_phrase)
        return canonical_provider or provider_phrase, provider_phrase, query

    def _resolve_open_target(
        self,
        *,
        normalized_text: str,
        stripped_text: str,
        surface_mode: str,
        explicit_browser: bool,
    ) -> str:
        del stripped_text
        lower_surface = normalize_phrase(surface_mode or "ghost")
        if explicit_browser or self._normalized_external_suffix.search(normalized_text):
            return "external"
        if self._normalized_deck_suffix.search(normalized_text):
            return "deck"
        return "deck" if lower_surface == "deck" else "external"

    def _is_personal_scope(self, stripped_text: str) -> bool:
        return bool(re.search(r"\b(?:my|personal)\b", stripped_text))

    def _has_browser_surface_cue(self, normalized_text: str) -> bool:
        return bool(self._normalized_external_suffix.search(normalized_text) or self._normalized_browser_target_suffix.search(normalized_text))

    def _looks_like_webish_unknown_destination(self, destination_phrase: str, *, stripped_text: str) -> bool:
        if " " in destination_phrase:
            return True
        return bool(re.search(r"\b(?:site|website|web site|portal|homepage|home page|page)\b", stripped_text))

    def _destination_for_phrase(self, phrase: str, *, include_personal: bool) -> tuple[KnownWebDestination, str] | None:
        phrase = normalize_phrase(phrase)
        if not phrase:
            return None
        lookup = self._destination_personal_alias_index if include_personal else self._destination_general_alias_index
        return lookup.get(phrase)

    def _provider_for_key(self, provider_key: str | None) -> KnownWebSearchProvider | None:
        normalized_key = normalize_phrase(provider_key or "")
        if not normalized_key:
            return None
        direct = self._search_provider_key_index.get(normalized_key)
        if direct is not None:
            return direct
        return self._search_provider_alias_index.get(normalized_key)

    def _canonical_search_provider_key(self, provider_phrase: str) -> str | None:
        provider = self._provider_for_key(provider_phrase)
        return provider.key if provider is not None else None

    def _site_search_domain_for_phrase(self, provider_phrase: str) -> str | None:
        normalized_phrase = normalize_phrase(provider_phrase)
        if not normalized_phrase:
            return None
        direct_domain = self._resolve_direct_domain_destination(provider_phrase)
        if direct_domain is not None:
            _, site_domain, _ = direct_domain
            return site_domain
        matched = self._destination_general_alias_index.get(normalized_phrase)
        if matched is None:
            return None
        destination, _ = matched
        if destination.requires_signed_in_session:
            return None
        host = destination.host()
        if not host:
            return None
        return host[4:] if host.startswith("www.") else host

    def _looks_like_domain(self, value: str) -> bool:
        return self._normalize_direct_domain_phrase(value) is not None

    def _looks_like_direct_domain_destination(self, value: str) -> bool:
        return self._normalize_direct_domain_phrase(value) is not None

    def _resolve_direct_domain_destination(self, phrase: str) -> tuple[str, str, str] | None:
        normalized_phrase = self._normalize_direct_domain_phrase(phrase)
        if not normalized_phrase:
            return None
        parsed = urlparse(f"https://{normalized_phrase}")
        host = str(parsed.netloc or "").strip().lower()
        if not host:
            return None
        site_domain = host[4:] if host.startswith("www.") else host
        url = f"https://{normalized_phrase}"
        if not parsed.path and not parsed.params and not parsed.query and not parsed.fragment:
            url = f"{url}/"
        display_title = normalized_phrase.rstrip("/") or site_domain
        return url, site_domain, display_title

    def _normalize_direct_domain_phrase(self, value: str) -> str | None:
        candidate = " ".join(str(value or "").split()).strip().strip(".,;:!?")
        if not candidate:
            return None
        candidate = re.sub(r"^https?://", "", candidate, flags=re.IGNORECASE).lstrip("/")
        if not candidate:
            return None
        parsed = urlparse(f"https://{candidate}")
        host = str(parsed.netloc or "").strip().lower()
        if not host or not re.fullmatch(r"(?:[a-z0-9-]+\.)+[a-z]{2,}", host):
            return None
        top_level_suffix = host.rsplit(".", 1)[-1]
        if top_level_suffix in FILE_STYLE_DOMAIN_SUFFIX_BLOCKLIST:
            return None
        suffix = parsed.path or ""
        if parsed.params:
            suffix = f"{suffix};{parsed.params}"
        if parsed.query:
            suffix = f"{suffix}?{parsed.query}"
        if parsed.fragment:
            suffix = f"{suffix}#{parsed.fragment}"
        return f"{host}{suffix}"

    def _display_name_for_provider_phrase(self, provider_phrase: str) -> str:
        normalized_phrase = normalize_phrase(provider_phrase)
        provider = self._provider_for_key(normalized_phrase)
        if provider is not None:
            return provider.title
        matched = self._destination_general_alias_index.get(normalized_phrase) or self._destination_personal_alias_index.get(normalized_phrase)
        if matched is not None:
            return matched[0].title
        direct_domain = self._resolve_direct_domain_destination(provider_phrase)
        if direct_domain is not None:
            return direct_domain[2]
        return " ".join(part.capitalize() for part in normalized_phrase.split())

    def _response_contract(self, *, title: str, micro: str, full: str) -> dict[str, str]:
        return {
            "bearing_title": title,
            "micro_response": micro,
            "full_response": full,
        }

    def _open_surface_label(self, open_target: str) -> str:
        return "the Deck" if open_target == "deck" else "the browser"
