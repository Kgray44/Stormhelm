from __future__ import annotations

from stormhelm.core.orchestrator.browser_destinations import BrowserDestinationResolver
from stormhelm.core.orchestrator.browser_destinations import BrowserIntentType
from stormhelm.core.orchestrator.browser_destinations import DestinationScope


def test_browser_destination_resolver_maps_personal_youtube_history_to_known_history_url() -> None:
    resolver = BrowserDestinationResolver()

    request = resolver.parse("open my personal youtube history in a browser", surface_mode="ghost")

    assert request is not None
    assert request.intent_type == BrowserIntentType.OPEN_DESTINATION
    assert request.scope == DestinationScope.PERSONAL
    assert request.destination_phrase == "youtube history"
    assert request.open_target == "external"

    resolution = resolver.resolve(request)

    assert resolution.success is True
    assert resolution.destination is not None
    assert resolution.destination.key == "youtube_history"
    assert resolution.url == "https://www.youtube.com/feed/history"


def test_browser_destination_resolver_maps_my_email_to_gmail() -> None:
    resolver = BrowserDestinationResolver()

    request = resolver.parse("open my email in a browser", surface_mode="ghost")

    assert request is not None
    assert request.intent_type == BrowserIntentType.OPEN_DESTINATION
    assert request.scope == DestinationScope.PERSONAL

    resolution = resolver.resolve(request)

    assert resolution.success is True
    assert resolution.destination is not None
    assert resolution.destination.key == "gmail"
    assert resolution.url == "https://mail.google.com/mail/u/0/#inbox"


def test_browser_destination_resolver_ignores_app_launch_and_search_phrasing() -> None:
    resolver = BrowserDestinationResolver()

    assert resolver.parse("open Chrome", surface_mode="ghost") is None


def test_browser_destination_resolver_maps_youtube_search_to_search_results_url() -> None:
    resolver = BrowserDestinationResolver()

    request = resolver.parse_search("search youtube for cats", surface_mode="ghost")

    assert request is not None
    assert request.intent_type == BrowserIntentType.SEARCH_REQUEST
    assert request.provider_key == "youtube"
    assert request.query == "cats"
    assert request.open_target == "external"

    resolution = resolver.resolve_search(request)

    assert resolution.success is True
    assert resolution.provider is not None
    assert resolution.provider.key == "youtube"
    assert resolution.url == "https://www.youtube.com/results?search_query=cats"


def test_browser_destination_resolver_maps_lookup_phrase_to_web_search_results_url() -> None:
    resolver = BrowserDestinationResolver()

    request = resolver.parse_search("look up OpenAI pricing", surface_mode="ghost")

    assert request is not None
    assert request.intent_type == BrowserIntentType.SEARCH_REQUEST
    assert request.provider_key == "web"
    assert request.query == "OpenAI pricing"

    resolution = resolver.resolve_search(request)

    assert resolution.success is True
    assert resolution.provider is not None
    assert resolution.provider.key == "web"
    assert resolution.url == "https://www.google.com/search?q=OpenAI+pricing"


def test_browser_destination_resolver_maps_stack_overflow_search_to_native_results_url() -> None:
    resolver = BrowserDestinationResolver()

    request = resolver.parse_search("search stack overflow for python dataclass", surface_mode="ghost")

    assert request is not None
    assert request.intent_type == BrowserIntentType.SEARCH_REQUEST
    assert request.provider_key == "stack_overflow"
    assert request.query == "python dataclass"

    resolution = resolver.resolve_search(request)

    assert resolution.success is True
    assert resolution.provider is not None
    assert resolution.provider.key == "stack_overflow"
    assert resolution.url == "https://stackoverflow.com/search?q=python+dataclass"


def test_browser_destination_resolver_maps_known_destination_search_to_site_search_url() -> None:
    resolver = BrowserDestinationResolver()

    request = resolver.parse_search("search openai for pricing", surface_mode="ghost")

    assert request is not None
    assert request.intent_type == BrowserIntentType.SEARCH_REQUEST
    assert request.provider_key == "openai"
    assert request.query == "pricing"

    resolution = resolver.resolve_search(request)

    assert resolution.success is True
    assert resolution.provider is not None
    assert resolution.provider.key == "web"
    assert resolution.url == "https://www.google.com/search?q=site%3Aopenai.com+pricing"


def test_browser_destination_resolver_maps_domain_phrase_to_site_search_url() -> None:
    resolver = BrowserDestinationResolver()

    request = resolver.parse_search("search docs.python.org for pathlib glob", surface_mode="ghost")

    assert request is not None
    assert request.intent_type == BrowserIntentType.SEARCH_REQUEST
    assert request.provider_key == "docs.python.org"
    assert request.query == "pathlib glob"

    resolution = resolver.resolve_search(request)

    assert resolution.success is True
    assert resolution.provider is not None
    assert resolution.provider.key == "web"
    assert resolution.url == "https://www.google.com/search?q=site%3Adocs.python.org+pathlib+glob"


def test_browser_destination_resolver_extracts_explicit_browser_target_from_open_request() -> None:
    resolver = BrowserDestinationResolver()

    request = resolver.parse("open gmail in firefox", surface_mode="ghost")

    assert request is not None
    assert request.intent_type == BrowserIntentType.OPEN_DESTINATION
    assert request.destination_phrase == "gmail"
    assert request.browser_preference == "firefox"
    assert request.explicit_browser is True


def test_browser_destination_resolver_extracts_explicit_browser_target_from_search_request() -> None:
    resolver = BrowserDestinationResolver()

    request = resolver.parse_search("search github for issue templates in chrome", surface_mode="ghost")

    assert request is not None
    assert request.intent_type == BrowserIntentType.SEARCH_REQUEST
    assert request.provider_key == "github"
    assert request.query == "issue templates"
    assert request.browser_preference == "chrome"
    assert request.explicit_browser is True


def test_browser_destination_resolver_reports_unknown_search_provider_as_unresolved() -> None:
    resolver = BrowserDestinationResolver()

    request = resolver.parse_search("search orbitz for flights", surface_mode="ghost")

    assert request is not None
    assert request.intent_type == BrowserIntentType.SEARCH_REQUEST
    assert request.provider_key == "orbitz"
    assert request.query == "flights"

    resolution = resolver.resolve_search(request)

    assert resolution.success is False
    assert resolution.failure_reason is not None
    assert resolution.failure_reason.value == "search_provider_unresolved"
