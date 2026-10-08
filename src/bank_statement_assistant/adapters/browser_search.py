"""Bounded Chromium search adapter for merchant evidence."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from time import monotonic
from typing import Any, Literal, Protocol
from urllib.parse import parse_qs, parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bank_statement_assistant.statements.merchant_evidence import (
    EvidenceSource,
    MerchantEvidence,
    MerchantLookupRequest,
    ResearchStatus,
    bounded_evidence_source,
)


@dataclass(frozen=True, slots=True)
class BrowserSearchResult:
    title: str
    url: str
    snippet: str


@dataclass(frozen=True, slots=True)
class BrowserSearchPage:
    results: tuple[BrowserSearchResult, ...] = ()
    outcome: Literal["results", "blocked", "error"] = "results"


class BrowserSearchPageFetcher(Protocol):
    def __call__(self, query: str, page_number: int) -> BrowserSearchPage: ...


BrowserFactory = Callable[[], BrowserSearchPageFetcher]


class BrowserSearchEvidenceProvider:
    """Search one fixed browser provider, escalating to one additional page."""

    _max_pages = 2

    def __init__(
        self,
        *,
        base_url: str = "https://html.duckduckgo.com/html/",
        timeout_seconds: float = 20,
        max_results: int = 5,
        max_snippet_length: int = 500,
        executable_path: str | None = None,
        browser_factory: BrowserFactory | None = None,
        total_timeout_seconds: float | None = None,
    ) -> None:
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("browser search base URL must be an HTTP(S) URL")
        if timeout_seconds <= 0:
            raise ValueError("browser search timeout must be positive")
        if max_results < 1 or max_results > 5:
            raise ValueError("browser search result count must be between 1 and 5")
        if max_snippet_length < 1:
            raise ValueError("browser search snippet length must be positive")
        total_timeout = total_timeout_seconds or timeout_seconds * self._max_pages
        if total_timeout <= 0:
            raise ValueError("browser search total timeout must be positive")
        self._base_url = base_url
        self._timeout_seconds = timeout_seconds
        self._max_results = max_results
        self._max_snippet_length = max_snippet_length
        self._executable_path = executable_path
        self._browser_factory = browser_factory
        self._total_timeout_seconds = total_timeout

    def lookup(self, request_data: MerchantLookupRequest) -> MerchantEvidence:
        query = " ".join(
            part
            for part in (request_data.merchant_name, request_data.city, request_data.country)
            if part
        )
        fetched_at = datetime.now(UTC)
        pages_fetched = 0
        escalation_reason: str | None = None
        sources: list[EvidenceSource] = []
        session: BrowserSearchPageFetcher | None = None
        deadline = monotonic() + self._total_timeout_seconds
        try:
            session = (self._browser_factory or self._default_browser_factory)()
            for page_number in range(1, self._max_pages + 1):
                if monotonic() >= deadline:
                    return MerchantEvidence(
                        status="unavailable",
                        provider="browser_search",
                        query=query,
                        fetched_at=fetched_at,
                        pages_fetched=pages_fetched,
                        escalation_reason="browser_total_timeout",
                    )
                pages_fetched = page_number
                page = session(query, page_number)
                if page.outcome == "error":
                    return MerchantEvidence(
                        status="unavailable",
                        provider="browser_search",
                        query=query,
                        fetched_at=fetched_at,
                        pages_fetched=pages_fetched,
                        escalation_reason="browser_provider_error",
                    )
                if page.outcome == "blocked":
                    if page_number == 1:
                        escalation_reason = "page_one_blocked"
                        continue
                    return MerchantEvidence(
                        status="ambiguous",
                        provider="browser_search",
                        query=query,
                        fetched_at=fetched_at,
                        pages_fetched=pages_fetched,
                        escalation_reason="page_two_blocked",
                    )
                sources = _deduplicate_sources(
                    (*sources, *self._bounded_sources(page.results)),
                    limit=10,
                )
                if _page_is_sufficient(request_data, sources):
                    return _evidence(
                        status="complete",
                        query=query,
                        sources=sources,
                        fetched_at=fetched_at,
                        pages_fetched=pages_fetched,
                        escalation_reason=escalation_reason,
                    )
                if page_number == 1:
                    escalation_reason = "insufficient_page_one_evidence"
            return _evidence(
                status="ambiguous" if sources else "not_found",
                query=query,
                sources=sources,
                fetched_at=fetched_at,
                pages_fetched=pages_fetched,
                escalation_reason="insufficient_page_two_evidence",
            )
        except Exception:
            return MerchantEvidence(
                status="unavailable",
                provider="browser_search",
                query=query,
                fetched_at=fetched_at,
                pages_fetched=pages_fetched,
                escalation_reason="browser_provider_error",
            )
        finally:
            close = getattr(session, "close", None)
            if callable(close):
                with suppress(Exception):
                    close()

    def _bounded_sources(self, results: Sequence[BrowserSearchResult]) -> list[EvidenceSource]:
        sources: list[EvidenceSource] = []
        for result in results[: self._max_results]:
            source = bounded_evidence_source(
                title=result.title,
                url=result.url,
                snippet=result.snippet,
                max_snippet_length=self._max_snippet_length,
            )
            if source is not None:
                sources.append(source)
        return sources

    def _default_browser_factory(self) -> BrowserSearchPageFetcher:
        return PlaywrightBrowserSearchSession(
            base_url=self._base_url,
            timeout_seconds=self._timeout_seconds,
            max_results=self._max_results,
            executable_path=self._executable_path,
        )


class PlaywrightBrowserSearchSession:
    """One isolated Playwright session with fixed navigation and extraction rules."""

    _max_page_text_length = 20_000

    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float,
        max_results: int,
        executable_path: str | None,
    ) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - depends on optional runtime install
            raise RuntimeError("Playwright is required for browser search") from exc
        self._base_url = base_url
        self._timeout_ms = int(timeout_seconds * 1000)
        self._operation_timeout_ms = max(1000, self._timeout_ms // 2)
        self._max_results = max_results
        self._playwright = sync_playwright().start()
        if executable_path:
            self._browser = self._playwright.chromium.launch(
                headless=True,
                executable_path=executable_path,
            )
        else:
            self._browser = self._playwright.chromium.launch(headless=True)
        self._context = self._browser.new_context(
            locale="en-US",
            service_workers="block",
        )
        self._allowed_host = urlsplit(base_url).hostname
        self._context.route("**/*", self._route)

    def __call__(self, query: str, page_number: int) -> BrowserSearchPage:
        page = self._context.new_page()
        try:
            page.goto(
                self._search_url(query, page_number),
                wait_until="domcontentloaded",
                timeout=self._operation_timeout_ms,
            )
            body_text = page.locator("body").inner_text(timeout=self._operation_timeout_ms)[
                : self._max_page_text_length
            ]
            if _looks_blocked(body_text):
                return BrowserSearchPage(outcome="blocked")
            return BrowserSearchPage(results=tuple(self._extract_results(page)))
        except Exception:
            return BrowserSearchPage(outcome="error")
        finally:
            page.close()

    def close(self) -> None:
        self._context.close()
        self._browser.close()
        self._playwright.stop()

    def _search_url(self, query: str, page_number: int) -> str:
        return build_browser_search_url(
            self._base_url,
            query=query,
            page_number=page_number,
            page_size=self._max_results,
        )

    def _route(self, route: Any) -> None:
        resource_type = route.request.resource_type
        if resource_type in {"image", "media", "font"}:
            route.abort()
            return
        hostname = urlsplit(route.request.url).hostname
        if hostname and hostname == self._allowed_host:
            route.continue_()
            return
        route.abort()

    def _extract_results(self, page: Any) -> list[BrowserSearchResult]:
        result_locator = page.locator(".result, article, [data-testid='result']")
        results: list[BrowserSearchResult] = []
        for index in range(min(result_locator.count(), self._max_results)):
            result = result_locator.nth(index)
            link = result.locator("a.result__a, h2 a, h3 a, a[href]").first
            href = link.get_attribute("href")
            if not isinstance(href, str):
                continue
            title = link.inner_text()
            snippet_locator = result.locator(".result__snippet, p").first
            snippet = snippet_locator.inner_text() if snippet_locator.count() else ""
            results.append(
                BrowserSearchResult(
                    title=title,
                    url=_resolve_result_url(self._base_url, href),
                    snippet=snippet,
                )
            )
        return results


def _evidence(
    *,
    status: ResearchStatus,
    query: str,
    sources: Sequence[EvidenceSource],
    fetched_at: datetime,
    pages_fetched: int,
    escalation_reason: str | None,
) -> MerchantEvidence:
    payload = [
        {
            "title": source.title,
            "url": source.url,
            "snippet": source.snippet,
        }
        for source in sources
    ]
    return MerchantEvidence(
        status=status,
        provider="browser_search",
        query=query,
        sources=tuple(sources),
        response_hash=sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
        fetched_at=fetched_at,
        pages_fetched=pages_fetched,
        escalation_reason=escalation_reason,
    )


def _page_is_sufficient(
    request_data: MerchantLookupRequest, sources: Sequence[EvidenceSource]
) -> bool:
    if len(sources) < 3:
        return False
    merchant_tokens = set(_tokens(request_data.merchant_name))
    if not merchant_tokens:
        return False
    matching_sources: list[EvidenceSource] = []
    for source in sources:
        source_tokens = set(_tokens(_source_text(source)))
        overlap = len(merchant_tokens & source_tokens)
        if overlap >= max(1, (len(merchant_tokens) + 1) // 2):
            matching_sources.append(source)
    if len(matching_sources) < 2:
        return False
    if request_data.city:
        city_tokens = set(_tokens(request_data.city))
        if not any(
            city_tokens <= set(_tokens(_source_text(source))) for source in matching_sources
        ):
            return False
    if not any(_country_matches(request_data.country, source) for source in matching_sources):
        return False
    if all(_is_generic_source(source) for source in matching_sources):
        return False
    business_types = {_business_type(source) for source in matching_sources}
    return len(business_types) == 1 and None not in business_types


def _source_text(source: EvidenceSource) -> str:
    return f"{source.title} {source.domain} {source.snippet}"


def _country_matches(country: str, source: EvidenceSource) -> bool:
    country_tokens = {
        "PT": {"pt", "portugal", "portuguese"},
        "ES": {"es", "spain", "spanish", "espana"},
        "FR": {"fr", "france", "french"},
        "GB": {"gb", "uk", "united", "kingdom", "british"},
    }.get(country.upper())
    if not country_tokens:
        return True
    source_tokens = set(_tokens(_source_text(source)))
    return source.domain.endswith(f".{country.casefold()}") or bool(country_tokens & source_tokens)


def _is_generic_source(source: EvidenceSource) -> bool:
    value = _source_text(source).casefold()
    return any(
        marker in value
        for marker in (
            "directory",
            "yellowpages",
            "tripadvisor",
            "yelp.",
            "facebook.",
            "instagram.",
        )
    )


def _business_type(source: EvidenceSource) -> str | None:
    value = set(_tokens(_source_text(source)))
    signals = {
        "pharmacy": {"pharmacy", "farmacia", "drugstore"},
        "restaurant": {"restaurant", "restaurante", "cafe", "café", "bar"},
        "grocery": {"grocery", "supermarket", "supermercado", "mercearia"},
        "hotel": {"hotel", "hostel", "guesthouse"},
        "salon": {"salon", "cabeleireiro", "hairdresser"},
    }
    matches = [name for name, terms in signals.items() if value & terms]
    return matches[0] if len(matches) == 1 else None


def _resolve_result_url(base_url: str, href: str) -> str:
    parsed = urlsplit(href)
    if parsed.path == "/l/":
        target = parse_qs(parsed.query).get("uddg", [None])[0]
        if isinstance(target, str) and target:
            return target
    return urljoin(base_url, href)


def build_browser_search_url(base_url: str, *, query: str, page_number: int, page_size: int) -> str:
    """Build the fixed DuckDuckGo HTML pagination contract used by the browser provider."""
    if page_number < 1:
        raise ValueError("browser search page number must be positive")
    if page_size < 1:
        raise ValueError("browser search page size must be positive")
    parsed = urlsplit(base_url)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    params["q"] = query
    params["s"] = str((page_number - 1) * page_size)
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(params), parsed.fragment)
    )


def _deduplicate_sources(sources: Sequence[EvidenceSource], *, limit: int) -> list[EvidenceSource]:
    deduplicated: list[EvidenceSource] = []
    seen: set[str] = set()
    for source in sources:
        key = _canonical_url(source.url)
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(source)
        if len(deduplicated) >= limit:
            break
    return deduplicated


def _canonical_url(value: str) -> str:
    parsed = urlsplit(value)
    query = sorted(
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_")
        and key.casefold() not in {"gclid", "fbclid", "ref"}
    )
    return urlunsplit(
        (
            parsed.scheme.lower(),
            (parsed.hostname or "").lower(),
            parsed.path,
            urlencode(query),
            "",
        )
    )


def _tokens(value: str) -> tuple[str, ...]:
    decomposed = unicodedata.normalize("NFKD", value)
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return tuple(re.findall(r"[a-z0-9]+", without_accents.casefold()))


def _looks_blocked(body_text: str) -> bool:
    text = body_text.casefold()
    return any(marker in text for marker in ("captcha", "unusual traffic", "verify you are human"))
