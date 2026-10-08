from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256

from bank_statement_assistant.adapters.browser_search import (
    BrowserSearchEvidenceProvider,
    BrowserSearchPage,
    BrowserSearchResult,
    build_browser_search_url,
)
from bank_statement_assistant.adapters.web_search import WebSearchMerchantEvidenceProvider
from bank_statement_assistant.statements.classification import ClassificationInput
from bank_statement_assistant.statements.merchant_evidence import (
    CachedMerchantEvidenceProvider,
    EvidenceSource,
    InMemoryMerchantEvidenceCache,
    MerchantEvidence,
    MerchantLookupRequest,
    MerchantNormalizer,
    ResearchAwareTransactionClassifier,
)


def test_normalizer_removes_bpi_reference_and_preserves_merchant_context() -> None:
    lookup = MerchantNormalizer.normalize("COMPRA ELON 7654321/00 FARMACIA EXEMPLO VILA NOVA")

    assert lookup == MerchantLookupRequest(
        merchant_name="FARMACIA EXEMPLO VILA NOVA",
        city=None,
        country="PT",
        normalized_key="FARMACIA EXEMPLO VILA NOVA|PT",
    )


def test_normalizer_removes_dates_amounts_and_account_identifiers() -> None:
    lookup = MerchantNormalizer.normalize(
        "01/09/2025 COMPRA ELON 7654321/00 FARMACIA EXEMPLO -12,34 EUR PT50000201231234567890154"
    )

    assert lookup.merchant_name == "FARMACIA EXEMPLO"


def test_normalizer_removes_transfer_boilerplate_and_long_references() -> None:
    lookup = MerchantNormalizer.normalize("TRF CR SEPA+ 0000001 DE ACME FARMACIA")

    assert lookup.merchant_name == "DE ACME FARMACIA"


def test_cached_provider_reuses_evidence_without_calling_underlying_provider() -> None:
    evidence = MerchantEvidence(
        status="complete",
        provider="fixture",
        query="FARMACIA EXEMPLO VILA NOVA",
        sources=(
            EvidenceSource(
                title="Farmácia Exemplo",
                url="https://example.test/pharmacy",
                domain="example.test",
                snippet="Pharmacy",
                content_hash="hash",
            ),
        ),
        response_hash="response",
        fetched_at=datetime(2026, 9, 6, tzinfo=UTC),
    )
    cache = InMemoryMerchantEvidenceCache()
    calls: list[str] = []

    def lookup(request: MerchantLookupRequest) -> MerchantEvidence:
        calls.append(request.normalized_key)
        return evidence

    provider = CachedMerchantEvidenceProvider(
        cache=cache,
        lookup=lookup,
        ttl_seconds=3600,
    )
    request = MerchantLookupRequest(
        merchant_name="FARMACIA EXEMPLO",
        city=None,
        country="PT",
        normalized_key="FARMACIA EXEMPLO|PT",
    )

    assert provider.lookup(request) == evidence
    cached = provider.lookup(request)
    assert cached == evidence.__class__(
        status=evidence.status,
        provider=evidence.provider,
        query=evidence.query,
        sources=evidence.sources,
        response_hash=evidence.response_hash,
        fetched_at=evidence.fetched_at,
        cache_hit=True,
    )
    assert calls == ["FARMACIA EXEMPLO|PT"]


def test_cached_provider_separates_evidence_by_provider_namespace() -> None:
    cache = InMemoryMerchantEvidenceCache()
    calls: list[str] = []
    request = MerchantLookupRequest(
        merchant_name="FARMACIA EXEMPLO",
        city=None,
        country="PT",
        normalized_key="FARMACIA EXEMPLO|PT",
    )
    evidence = MerchantEvidence(
        status="complete",
        provider="fixture",
        query=request.merchant_name,
    )

    def lookup(_request: MerchantLookupRequest) -> MerchantEvidence:
        calls.append("lookup")
        return evidence

    brave = CachedMerchantEvidenceProvider(
        cache=cache,
        lookup=lookup,
        ttl_seconds=3600,
        cache_namespace="brave",
    )
    browser = CachedMerchantEvidenceProvider(
        cache=cache,
        lookup=lookup,
        ttl_seconds=3600,
        cache_namespace="browser",
    )

    brave.lookup(request)
    brave.lookup(request)
    browser.lookup(request)

    assert calls == ["lookup", "lookup"]


class FakeClassifier:
    def classify(self, transactions: tuple[ClassificationInput, ...]):
        from bank_statement_assistant.statements.classification import (
            ClassificationDecision,
            ClassificationResult,
        )

        assert transactions[0].merchant_evidence is not None
        return ClassificationResult(
            decisions=(
                ClassificationDecision(
                    source_ordinal=transactions[0].source_ordinal,
                    reporting_category="Health",
                    movement_kind="Expense",
                    payment_channel="Card",
                    confidence=0.95,
                    rationale="Merchant evidence identifies a pharmacy",
                ),
            )
        )


def test_research_aware_classifier_attaches_evidence_and_audit_event() -> None:
    evidence = MerchantEvidence(
        status="complete",
        provider="fixture",
        query="FARMACIA EXEMPLO",
        sources=(),
        response_hash="response",
        fetched_at=datetime(2026, 9, 6, tzinfo=UTC),
    )
    base = ClassificationInput(
        source_ordinal=1,
        booking_date=datetime(2026, 9, 6, tzinfo=UTC).date(),
        description="COMPRA ELON 1234567/00 FARMACIA EXEMPLO",
        signed_amount=Decimal("-9.17"),
        currency="EUR",
    )
    classifier = ResearchAwareTransactionClassifier(
        classifier=FakeClassifier(),
        provider=lambda _request: evidence,
    )

    result = classifier.classify((base,))

    assert result.decisions[0].reporting_category == "Health"
    assert result.research[0].source_ordinal == 1
    assert result.research[0].status == "complete"
    assert result.research[0].query_hash == sha256(evidence.query.encode()).hexdigest()
    assert result.research[0].fetched_at == evidence.fetched_at


def test_unavailable_research_caps_confidence_for_review() -> None:
    unavailable = MerchantEvidence(
        status="unavailable",
        provider="web_search",
        query="FARMACIA EXEMPLO",
    )
    base = ClassificationInput(
        source_ordinal=1,
        booking_date=datetime(2026, 9, 6, tzinfo=UTC).date(),
        description="FARMACIA EXEMPLO",
        signed_amount=Decimal("-9.17"),
        currency="EUR",
    )

    result = ResearchAwareTransactionClassifier(
        classifier=FakeClassifier(),
        provider=lambda _request: unavailable,
    ).classify((base,))

    assert result.decisions[0].confidence < 0.7
    assert result.decisions[0].classification_status == "needs_review"


def test_ambiguous_research_caps_confidence_for_review() -> None:
    ambiguous = MerchantEvidence(
        status="ambiguous",
        provider="browser_search",
        query="FARMACIA EXEMPLO",
        pages_fetched=2,
        escalation_reason="insufficient_page_two_evidence",
    )
    base = ClassificationInput(
        source_ordinal=1,
        booking_date=datetime(2026, 9, 6, tzinfo=UTC).date(),
        description="FARMACIA EXEMPLO",
        signed_amount=Decimal("-9.17"),
        currency="EUR",
    )

    result = ResearchAwareTransactionClassifier(
        classifier=FakeClassifier(),
        provider=lambda _request: ambiguous,
    ).classify((base,))

    assert result.decisions[0].confidence < 0.7
    assert result.decisions[0].classification_status == "needs_review"


def test_provider_failure_is_recorded_as_unavailable_without_blocking_classification() -> None:
    base = ClassificationInput(
        source_ordinal=1,
        booking_date=datetime(2026, 9, 6, tzinfo=UTC).date(),
        description="COMPRA ELON FARMACIA EXEMPLO",
        signed_amount=Decimal("-9.17"),
        currency="EUR",
    )

    def broken_provider(_request: MerchantLookupRequest) -> MerchantEvidence:
        raise OSError("network unavailable")

    result = ResearchAwareTransactionClassifier(
        classifier=FakeClassifier(),
        provider=broken_provider,
    ).classify((base,))

    assert result.research[0].status == "unavailable"
    assert result.research[0].provider == "provider_error"


def test_web_search_adapter_returns_bounded_sources(monkeypatch) -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return (
                b'{"web":{"results":[{"title":"Farmacia Exemplo",'
                b'"url":"https://example.test/p",'
                b'"description":"Pharmacy in Paco de Arcos"}]}}'
            )

    captured = {}

    def urlopen(request, **_kwargs):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.headers)
        return Response()

    monkeypatch.setattr("bank_statement_assistant.adapters.web_search.request.urlopen", urlopen)
    provider = WebSearchMerchantEvidenceProvider(
        base_url="https://search.test/res/v1/web/search",
        api_key="secret",
        timeout_seconds=2,
        max_results=3,
    )

    evidence = provider.lookup(
        MerchantLookupRequest(
            merchant_name="FARMACIA EXEMPLO",
            city=None,
            country="PT",
            normalized_key="FARMACIA EXEMPLO|PT",
        )
    )

    assert evidence.status == "complete"
    assert evidence.sources[0].domain == "example.test"
    assert "q=FARMACIA+EXEMPLO+PT" in captured["url"]
    assert captured["headers"]["X-subscription-token"] == "secret"


def test_web_search_adapter_never_raises_provider_failure(monkeypatch) -> None:
    def urlopen(*_args, **_kwargs):
        raise OSError("network details must not escape")

    monkeypatch.setattr("bank_statement_assistant.adapters.web_search.request.urlopen", urlopen)
    provider = WebSearchMerchantEvidenceProvider(
        base_url="https://search.test/res/v1/web/search",
        api_key="secret",
        timeout_seconds=2,
        max_results=3,
    )

    evidence = provider.lookup(
        MerchantLookupRequest(
            merchant_name="UNKNOWN",
            city=None,
            country="PT",
            normalized_key="UNKNOWN|PT",
        )
    )

    assert evidence.status == "unavailable"


def test_browser_search_fetches_page_two_when_page_one_is_insufficient() -> None:
    pages: list[int] = []

    def search_page(query: str, page_number: int) -> BrowserSearchPage:
        assert query == "FARMACIA EXEMPLO PT"
        pages.append(page_number)
        if page_number == 1:
            return BrowserSearchPage(
                results=(
                    BrowserSearchResult(
                        title="Directory listing",
                        url="https://example.test/directory",
                        snippet="Businesses directory",
                    ),
                )
            )
        return BrowserSearchPage(
            results=tuple(
                BrowserSearchResult(
                    title=f"Farmacia Exemplo result {index}",
                    url=f"https://example.test/{index}",
                    snippet="Farmacia Exemplo pharmacy in Portugal",
                )
                for index in range(1, 4)
            )
        )

    provider = BrowserSearchEvidenceProvider(
        browser_factory=lambda: search_page,
        timeout_seconds=2,
        max_results=5,
    )

    evidence = provider.lookup(
        MerchantLookupRequest(
            merchant_name="FARMACIA EXEMPLO",
            city=None,
            country="PT",
            normalized_key="FARMACIA EXEMPLO|PT",
        )
    )

    assert pages == [1, 2]
    assert evidence.status == "complete"
    assert evidence.pages_fetched == 2
    assert evidence.escalation_reason == "insufficient_page_one_evidence"
    assert len(evidence.sources) == 4


def test_browser_search_stops_after_sufficient_page_one() -> None:
    pages: list[int] = []

    def search_page(_query: str, page_number: int) -> BrowserSearchPage:
        pages.append(page_number)
        return BrowserSearchPage(
            results=tuple(
                BrowserSearchResult(
                    title=f"Farmacia Exemplo result {index}",
                    url=f"https://example.test/{index}",
                    snippet="Farmacia Exemplo pharmacy in Portugal",
                )
                for index in range(1, 4)
            )
        )

    evidence = BrowserSearchEvidenceProvider(
        browser_factory=lambda: search_page,
        timeout_seconds=2,
        max_results=5,
    ).lookup(
        MerchantLookupRequest(
            merchant_name="FARMACIA EXEMPLO",
            city=None,
            country="PT",
            normalized_key="FARMACIA EXEMPLO|PT",
        )
    )

    assert pages == [1]
    assert evidence.status == "complete"
    assert evidence.pages_fetched == 1
    assert evidence.escalation_reason is None


def test_browser_search_marks_two_insufficient_pages_ambiguous() -> None:
    def search_page(_query: str, _page_number: int) -> BrowserSearchPage:
        return BrowserSearchPage(
            results=(
                BrowserSearchResult(
                    title="Unrelated result",
                    url="https://example.test/unrelated",
                    snippet="No merchant details",
                ),
            )
        )

    evidence = BrowserSearchEvidenceProvider(
        browser_factory=lambda: search_page,
        timeout_seconds=2,
        max_results=5,
    ).lookup(
        MerchantLookupRequest(
            merchant_name="FARMACIA EXEMPLO",
            city=None,
            country="PT",
            normalized_key="FARMACIA EXEMPLO|PT",
        )
    )

    assert evidence.status == "ambiguous"
    assert evidence.pages_fetched == 2
    assert evidence.escalation_reason == "insufficient_page_two_evidence"


def test_browser_search_retries_page_two_after_a_blocked_first_page() -> None:
    pages: list[int] = []

    def search_page(_query: str, page_number: int) -> BrowserSearchPage:
        pages.append(page_number)
        if page_number == 1:
            return BrowserSearchPage(outcome="blocked")
        return BrowserSearchPage(
            results=tuple(
                BrowserSearchResult(
                    title=f"Farmacia Exemplo result {index}",
                    url=f"https://example.test/{index}",
                    snippet="Farmacia Exemplo pharmacy in Portugal",
                )
                for index in range(1, 4)
            )
        )

    evidence = BrowserSearchEvidenceProvider(
        browser_factory=lambda: search_page,
        timeout_seconds=2,
        max_results=5,
    ).lookup(
        MerchantLookupRequest(
            merchant_name="FARMACIA EXEMPLO",
            city=None,
            country="PT",
            normalized_key="FARMACIA EXEMPLO|PT",
        )
    )

    assert pages == [1, 2]
    assert evidence.status == "complete"
    assert evidence.pages_fetched == 2
    assert evidence.escalation_reason == "page_one_blocked"


def test_browser_search_does_not_retry_transport_error_as_page_two() -> None:
    pages: list[int] = []

    def search_page(_query: str, page_number: int) -> BrowserSearchPage:
        pages.append(page_number)
        return BrowserSearchPage(outcome="error")

    evidence = BrowserSearchEvidenceProvider(
        browser_factory=lambda: search_page,
        timeout_seconds=2,
    ).lookup(
        MerchantLookupRequest(
            merchant_name="FARMACIA EXEMPLO",
            city=None,
            country="PT",
            normalized_key="FARMACIA EXEMPLO|PT",
        )
    )

    assert pages == [1]
    assert evidence.status == "unavailable"
    assert evidence.escalation_reason == "browser_provider_error"


def test_browser_search_url_uses_fixed_second_page_offset() -> None:
    assert (
        build_browser_search_url(
            "https://html.duckduckgo.com/html/",
            query="FARMACIA EXEMPLO PT",
            page_number=2,
            page_size=5,
        )
        == "https://html.duckduckgo.com/html/?q=FARMACIA+EXEMPLO+PT&s=5"
    )
