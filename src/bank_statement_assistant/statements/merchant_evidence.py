"""Bounded merchant research used as non-authoritative classification context."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from hashlib import sha256
from time import monotonic
from typing import Literal, Protocol, cast
from urllib.parse import urlsplit

from bank_statement_assistant.statements.classification import (
    CLASSIFICATION_CONFIDENCE_THRESHOLD,
    ClassificationDecision,
    ClassificationInput,
    ClassificationResearch,
    ClassificationResearchSource,
    ClassificationResult,
    TransactionClassifier,
)

ResearchStatus = Literal["complete", "not_found", "unavailable", "ambiguous", "disabled"]


@dataclass(frozen=True, slots=True)
class MerchantLookupRequest:
    merchant_name: str
    city: str | None
    country: str
    normalized_key: str


@dataclass(frozen=True, slots=True)
class EvidenceSource:
    title: str
    url: str
    domain: str
    snippet: str
    content_hash: str


def bounded_evidence_source(
    *,
    title: str,
    url: str,
    snippet: str,
    max_snippet_length: int,
) -> EvidenceSource | None:
    """Validate and bound one untrusted search result."""
    clean_title = _clean_external_text(title, 200)
    clean_url = _clean_external_text(url, 2048)
    clean_snippet = _clean_external_text(snippet, max_snippet_length)
    parsed = urlsplit(clean_url)
    if (
        not clean_title
        or not clean_snippet
        or parsed.scheme not in {"http", "https"}
        or not parsed.hostname
    ):
        return None
    return EvidenceSource(
        title=clean_title,
        url=clean_url,
        domain=parsed.hostname.lower(),
        snippet=clean_snippet,
        content_hash=_hash_text(clean_snippet),
    )


@dataclass(frozen=True, slots=True)
class MerchantEvidence:
    status: ResearchStatus
    provider: str
    query: str
    query_hash: str | None = None
    sources: tuple[EvidenceSource, ...] = ()
    response_hash: str | None = None
    fetched_at: datetime | None = None
    cache_hit: bool = False
    pages_fetched: int = 0
    escalation_reason: str | None = None

    def prompt_context(self) -> dict[str, object]:
        return {
            "status": self.status,
            "provider": self.provider,
            "sources": [
                {
                    "title": source.title,
                    "domain": source.domain,
                    "snippet": source.snippet,
                }
                for source in self.sources
            ],
        }


class MerchantEvidenceProvider(Protocol):
    def lookup(self, request: MerchantLookupRequest) -> MerchantEvidence: ...


class DisabledMerchantEvidenceProvider:
    def lookup(self, request: MerchantLookupRequest) -> MerchantEvidence:
        return MerchantEvidence(
            status="disabled",
            provider="disabled",
            query=request.merchant_name,
        )


class MerchantEvidenceCache(Protocol):
    def get(self, key: str) -> MerchantEvidence | None: ...

    def put(self, key: str, evidence: MerchantEvidence, ttl_seconds: float) -> None: ...


class InMemoryMerchantEvidenceCache:
    def __init__(self) -> None:
        self._values: dict[str, tuple[MerchantEvidence, float]] = {}

    def get(self, key: str) -> MerchantEvidence | None:
        value = self._values.get(key)
        if value is None or value[1] <= monotonic():
            return None
        return value[0]

    def put(self, key: str, evidence: MerchantEvidence, ttl_seconds: float) -> None:
        self._values[key] = (evidence, monotonic() + ttl_seconds)


class MerchantNormalizer:
    _bpi_prefix = re.compile(r"\bCOMPRA\s+ELON\b", re.IGNORECASE)
    _reference = re.compile(r"\b\d{5,}/\d{1,3}\b")
    _date = re.compile(r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{1,2}-\d{1,2})\b")
    _money = re.compile(
        r"(?<!\w)[+-]?(?:\d{1,3}(?:[.\s]\d{3})*|\d+)(?:,\d{2}|\.\d{2})"
        r"(?:\s?(?:EUR|€|USD|GBP))?(?!\w)",
        re.IGNORECASE,
    )
    _iban = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,}\b", re.IGNORECASE)
    _long_number = re.compile(r"(?<!\w)\d{3,}(?!\w)")
    _transaction_token = re.compile(
        r"\b(?:TRF|CR|SEPA|INST|LEV|ATM|DD|MB\s*WAY|COMPRA|ELON|PAGAMENTO|TRANSFER)\b",
        re.IGNORECASE,
    )
    _spaces = re.compile(r"\s+")

    @classmethod
    def normalize(cls, description: str, *, country: str = "PT") -> MerchantLookupRequest:
        value = cls._bpi_prefix.sub(" ", description)
        value = cls._reference.sub(" ", value)
        value = cls._date.sub(" ", value)
        value = cls._money.sub(" ", value)
        value = cls._iban.sub(" ", value)
        value = cls._long_number.sub(" ", value)
        value = cls._transaction_token.sub(" ", value)
        value = cls._spaces.sub(" ", value).strip(" -+")[:120]
        normalized = _normalize_key(value)
        return MerchantLookupRequest(
            merchant_name=value,
            city=None,
            country=country.upper(),
            normalized_key=f"{normalized}|{country.upper()}",
        )


class CachedMerchantEvidenceProvider:
    def __init__(
        self,
        *,
        cache: MerchantEvidenceCache,
        lookup: Callable[[MerchantLookupRequest], MerchantEvidence],
        ttl_seconds: float,
        cache_namespace: str = "default",
        negative_ttl_seconds: float = 3600,
        unavailable_ttl_seconds: float = 300,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("merchant evidence cache TTL must be positive")
        if not cache_namespace.strip():
            raise ValueError("merchant evidence cache namespace must not be empty")
        if negative_ttl_seconds <= 0 or unavailable_ttl_seconds <= 0:
            raise ValueError("merchant evidence negative TTLs must be positive")
        self._cache = cache
        self._lookup = lookup
        self._ttl_seconds = ttl_seconds
        self._cache_namespace = cache_namespace.strip()
        self._negative_ttl_seconds = negative_ttl_seconds
        self._unavailable_ttl_seconds = unavailable_ttl_seconds

    def lookup(self, request: MerchantLookupRequest) -> MerchantEvidence:
        cache_key = f"{self._cache_namespace}|{request.normalized_key}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return replace(cached, cache_hit=True)
        evidence = self._lookup(request)
        ttl_seconds = self._ttl_seconds
        if evidence.status in {"not_found", "ambiguous"}:
            ttl_seconds = self._negative_ttl_seconds
        elif evidence.status == "unavailable":
            ttl_seconds = self._unavailable_ttl_seconds
        self._cache.put(cache_key, evidence, ttl_seconds)
        return evidence


class ResearchAwareTransactionClassifier:
    """Enrich transactions with bounded evidence before strict classification."""

    def __init__(
        self,
        *,
        classifier: TransactionClassifier,
        provider: MerchantEvidenceProvider | Callable[[MerchantLookupRequest], MerchantEvidence],
        enabled: bool = True,
    ) -> None:
        self._classifier = classifier
        self._provider = provider
        self._enabled = enabled

    def classify(self, transactions: Sequence[ClassificationInput]) -> ClassificationResult:
        transaction_batch = tuple(transactions)
        if not self._enabled:
            result = self._classifier.classify(transaction_batch)
            return ClassificationResult(
                decisions=result.decisions,
                normalizations=result.normalizations,
                research=tuple(
                    ClassificationResearch(
                        source_ordinal=transaction.source_ordinal,
                        status="disabled",
                        provider="disabled",
                        query_hash=None,
                        response_hash=None,
                        source_count=0,
                        cache_hit=False,
                    )
                    for transaction in transaction_batch
                ),
            )
        enriched: list[ClassificationInput] = []
        research: list[ClassificationResearch] = []
        for transaction in transaction_batch:
            lookup = MerchantNormalizer.normalize(transaction.description)
            evidence = _safe_provider_lookup(self._provider, lookup)
            enriched.append(replace(transaction, merchant_evidence=evidence))
            research.append(
                ClassificationResearch(
                    source_ordinal=transaction.source_ordinal,
                    status=evidence.status,
                    provider=evidence.provider,
                    query_hash=evidence.query_hash or _hash_text(evidence.query),
                    response_hash=evidence.response_hash,
                    source_count=len(evidence.sources),
                    cache_hit=evidence.cache_hit,
                    pages_fetched=evidence.pages_fetched,
                    escalation_reason=evidence.escalation_reason,
                    fetched_at=evidence.fetched_at,
                    sources=tuple(
                        ClassificationResearchSource(
                            title=source.title,
                            url=source.url,
                            domain=source.domain,
                            content_hash=source.content_hash,
                        )
                        for source in evidence.sources
                    ),
                )
            )
        result = self._classifier.classify(tuple(enriched))
        decisions = tuple(
            _apply_research_safety_cap(decision, research) for decision in result.decisions
        )
        return ClassificationResult(
            decisions=decisions,
            normalizations=result.normalizations,
            research=tuple(research),
        )


def _provider_lookup(
    provider: MerchantEvidenceProvider | Callable[[MerchantLookupRequest], MerchantEvidence],
    request: MerchantLookupRequest,
) -> MerchantEvidence:
    lookup = getattr(provider, "lookup", None)
    if callable(lookup):
        return cast(Callable[[MerchantLookupRequest], MerchantEvidence], lookup)(request)
    return cast(Callable[[MerchantLookupRequest], MerchantEvidence], provider)(request)


def _safe_provider_lookup(
    provider: MerchantEvidenceProvider | Callable[[MerchantLookupRequest], MerchantEvidence],
    request: MerchantLookupRequest,
) -> MerchantEvidence:
    try:
        return _provider_lookup(provider, request)
    except Exception:
        return MerchantEvidence(
            status="unavailable",
            provider="provider_error",
            query=request.merchant_name,
        )


def _apply_research_safety_cap(
    decision: ClassificationDecision,
    research: list[ClassificationResearch],
) -> ClassificationDecision:
    event = next(
        (item for item in research if item.source_ordinal == decision.source_ordinal),
        None,
    )
    if event is None or event.status not in {"unavailable", "not_found", "ambiguous"}:
        return decision
    if decision.confidence < CLASSIFICATION_CONFIDENCE_THRESHOLD:
        return decision
    return decision.model_copy(update={"confidence": CLASSIFICATION_CONFIDENCE_THRESHOLD - 0.01})


def _normalize_key(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^A-Z0-9]+", " ", without_accents.upper()).strip()


def _clean_external_text(value: str, limit: int) -> str:
    return re.sub(r"[\x00-\x1f\x7f]", " ", value).strip()[:limit]


def _hash_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()
