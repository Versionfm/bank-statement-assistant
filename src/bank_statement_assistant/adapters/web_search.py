"""HTTP adapter for bounded merchant web research."""

import json
from datetime import UTC, datetime
from hashlib import sha256
from urllib import error, parse, request

from bank_statement_assistant.statements.merchant_evidence import (
    EvidenceSource,
    MerchantEvidence,
    MerchantLookupRequest,
    bounded_evidence_source,
)


class WebSearchMerchantEvidenceProvider:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_seconds: float = 8,
        max_results: int = 5,
        max_snippet_length: int = 500,
    ) -> None:
        if not base_url.strip():
            raise ValueError("web search base URL must not be empty")
        if not api_key.strip():
            raise ValueError("web search API key must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("web search timeout must be positive")
        if max_results < 1 or max_results > 10:
            raise ValueError("web search result count must be between 1 and 10")
        self._base_url = base_url
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._max_results = max_results
        self._max_snippet_length = max_snippet_length

    def lookup(self, request_data: MerchantLookupRequest) -> MerchantEvidence:
        query = " ".join(
            part
            for part in (request_data.merchant_name, request_data.city, request_data.country)
            if part
        )
        query_url = f"{self._base_url}?{parse.urlencode({'q': query, 'count': self._max_results})}"
        http_request = request.Request(
            query_url,
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": self._api_key,
            },
            method="GET",
        )
        try:
            with request.urlopen(http_request, timeout=self._timeout_seconds) as response:
                body = response.read()
            decoded = json.loads(body.decode("utf-8"))
            sources = self._sources(decoded)
        except (error.HTTPError, error.URLError, TimeoutError, OSError, json.JSONDecodeError):
            return MerchantEvidence(
                status="unavailable",
                provider="web_search",
                query=query,
                fetched_at=datetime.now(UTC),
            )
        if not sources:
            return MerchantEvidence(
                status="not_found",
                provider="web_search",
                query=query,
                response_hash=_hash_bytes(body),
                fetched_at=datetime.now(UTC),
            )
        return MerchantEvidence(
            status="complete",
            provider="web_search",
            query=query,
            sources=tuple(sources),
            response_hash=_hash_bytes(body),
            fetched_at=datetime.now(UTC),
        )

    def _sources(self, decoded: object) -> list[EvidenceSource]:
        if not isinstance(decoded, dict):
            return []
        web = decoded.get("web")
        if not isinstance(web, dict) or not isinstance(web.get("results"), list):
            return []
        sources: list[EvidenceSource] = []
        for item in web["results"][: self._max_results]:
            if not isinstance(item, dict):
                continue
            title_value: object = item.get("title")
            url_value: object = item.get("url")
            snippet_value: object = item.get("description")
            title = title_value if isinstance(title_value, str) else None
            url = url_value if isinstance(url_value, str) else None
            snippet = snippet_value if isinstance(snippet_value, str) else None
            if (
                not isinstance(title, str)
                or not isinstance(url, str)
                or not isinstance(snippet, str)
                or not title.strip()
                or not url.strip()
                or not snippet.strip()
            ):
                continue
            source = bounded_evidence_source(
                title=title,
                url=url,
                snippet=snippet,
                max_snippet_length=self._max_snippet_length,
            )
            if source is not None:
                sources.append(source)
        return sources


def _hash_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()
