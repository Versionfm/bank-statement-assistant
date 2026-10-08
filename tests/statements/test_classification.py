import json
from dataclasses import replace
from datetime import date
from decimal import Decimal
from urllib import error

import pytest

from bank_statement_assistant.statements.classification import (
    ClassificationDecision,
    ClassificationError,
    ClassificationInput,
    ClassificationResult,
    OpenAICompatibleTransactionClassifier,
    normalize_classification_result,
)
from bank_statement_assistant.statements.merchant_evidence import EvidenceSource, MerchantEvidence


def transaction_input(ordinal: int = 1) -> ClassificationInput:
    return ClassificationInput(
        source_ordinal=ordinal,
        booking_date=date(2026, 9, 1),
        description="Restaurante Lisboa",
        signed_amount=Decimal("-12.50"),
        currency="EUR",
    )


def test_classification_decision_requires_category_except_for_transfers() -> None:
    transfer = ClassificationDecision(
        source_ordinal=1,
        reporting_category=None,
        movement_kind="Transfer",
        payment_channel="Bank Transfer",
        confidence=0.91,
        rationale="Own-account transfer description",
    )

    assert transfer.reporting_category is None
    with pytest.raises(ValueError):
        ClassificationDecision(
            source_ordinal=1,
            reporting_category=None,
            movement_kind="Expense",
            payment_channel="Card",
            confidence=0.91,
            rationale="Missing category",
        )


def test_classifier_accepts_a_complete_json_response(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return (
                b'{"choices":[{"message":{"content":"{\\"items\\":[{'
                b'\\"source_ordinal\\":1,\\"reporting_category\\":'
                b'\\"Restaurants & Cafes\\",\\"movement_kind\\":\\"Expense\\",'
                b'\\"payment_channel\\":\\"Card\\",\\"confidence\\":0.88,'
                b'\\"rationale\\":\\"Restaurant description\\"}]}"}}]}'
            )

    monkeypatch.setattr(
        "bank_statement_assistant.statements.classification.request.urlopen",
        lambda *_args, **_kwargs: Response(),
    )

    result = OpenAICompatibleTransactionClassifier(
        base_url="http://vllm:8000/v1", model="bank-statement-qwen"
    ).classify((transaction_input(),))

    assert isinstance(result, ClassificationResult)
    assert result.decisions[0].reporting_category == "Restaurants & Cafes"
    assert result.decisions[0].movement_kind == "Expense"
    assert result.normalizations == ()


def test_classifier_sends_bounded_merchant_evidence_to_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "items": [
                                            {
                                                "source_ordinal": 1,
                                                "reporting_category": "Health",
                                                "movement_kind": "Expense",
                                                "payment_channel": "Card",
                                                "confidence": 0.95,
                                                "rationale": "Pharmacy evidence",
                                            }
                                        ]
                                    }
                                )
                            }
                        }
                    ]
                }
            ).encode()

    captured: dict[str, object] = {}

    def urlopen(req: object, **_kwargs: object) -> Response:
        captured.update(json.loads(req.data))  # type: ignore[attr-defined]
        return Response()

    monkeypatch.setattr(
        "bank_statement_assistant.statements.classification.request.urlopen",
        urlopen,
    )
    enriched = replace(
        transaction_input(),
        merchant_evidence=MerchantEvidence(
            status="complete",
            provider="fixture",
            query="FARMACIA EXEMPLO PT",
            sources=(
                EvidenceSource(
                    title="Farmacia Exemplo",
                    url="https://example.test/pharmacy",
                    domain="example.test",
                    snippet="Pharmacy",
                    content_hash="hash",
                ),
            ),
        ),
    )

    OpenAICompatibleTransactionClassifier(
        base_url="http://vllm:8000/v1", model="bank-statement-qwen"
    ).classify((enriched,))

    user_content = json.loads(captured["messages"][1]["content"])
    assert user_content["transactions"][0]["merchant_evidence"]["status"] == "complete"
    assert (
        user_content["transactions"][0]["merchant_evidence"]["sources"][0]["snippet"]
        == "Pharmacy"
    )


def test_classification_normalization_is_idempotent() -> None:
    result = ClassificationResult(
        decisions=(
            ClassificationDecision(
                source_ordinal=1,
                reporting_category=None,
                movement_kind="Transfer",
                payment_channel="Bank Transfer",
                confidence=0.88,
                rationale="Own-account movement",
            ),
        )
    )

    normalized = normalize_classification_result(result)

    assert normalized == result


def test_classifier_normalizes_transfer_reporting_category(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "items": [
                                            {
                                                "source_ordinal": 1,
                                                "reporting_category": "Other Expense",
                                                "movement_kind": "Transfer",
                                                "payment_channel": "Bank Transfer",
                                                "confidence": 0.88,
                                                "rationale": "Own-account movement",
                                            }
                                        ]
                                    }
                                )
                            }
                        }
                    ]
                }
            ).encode()

    monkeypatch.setattr(
        "bank_statement_assistant.statements.classification.request.urlopen",
        lambda *_args, **_kwargs: Response(),
    )

    result = OpenAICompatibleTransactionClassifier(
        base_url="http://vllm:8000/v1", model="bank-statement-qwen"
    ).classify((transaction_input(),))

    assert result.decisions[0].movement_kind == "Transfer"
    assert result.decisions[0].reporting_category is None
    assert len(result.normalizations) == 1
    assert result.normalizations[0].source_ordinal == 1
    assert result.normalizations[0].rule_id == ("transfer_reporting_category_nullification_v1")


def test_classifier_rejects_a_response_with_missing_transactions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"choices":[{"message":{"content":"{\\"items\\":[]}"}}]}'

    monkeypatch.setattr(
        "bank_statement_assistant.statements.classification.request.urlopen",
        lambda *_args, **_kwargs: Response(),
    )

    with pytest.raises(ClassificationError, match="did not cover") as raised:
        OpenAICompatibleTransactionClassifier(
            base_url="http://vllm:8000/v1", model="bank-statement-qwen"
        ).classify((transaction_input(),))

    assert raised.value.error_code == "classify_coverage_mismatch"


def test_classifier_canonicalizes_atm_and_requests_strict_enum_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "items": [
                                            {
                                                "source_ordinal": 1,
                                                "reporting_category": "Transport",
                                                "movement_kind": "Expense",
                                                "payment_channel": "ATM",
                                                "confidence": 0.88,
                                                "rationale": "Cash machine",
                                            }
                                        ]
                                    }
                                )
                            }
                        }
                    ]
                }
            ).encode()

    captured: dict[str, object] = {}

    def urlopen(req: object, **_kwargs: object) -> Response:
        captured.update(json.loads(req.data))  # type: ignore[attr-defined]
        return Response()

    monkeypatch.setattr(
        "bank_statement_assistant.statements.classification.request.urlopen",
        urlopen,
    )

    result = OpenAICompatibleTransactionClassifier(
        base_url="http://vllm:8000/v1", model="bank-statement-qwen"
    ).classify((transaction_input(),))

    assert result.decisions[0].payment_channel == "Cash Withdrawal"
    response_format = captured["response_format"]
    assert isinstance(response_format, dict)
    assert response_format["type"] == "json_schema"
    schema = response_format["json_schema"]
    assert isinstance(schema, dict)
    payment_channel_enum = schema["schema"]["properties"]["items"]["items"]["properties"][
        "payment_channel"
    ]["enum"]
    assert payment_channel_enum == [
        "MB WAY",
        "Card",
        "Bank Transfer",
        "Direct Debit",
        "Cash Withdrawal",
        "Other",
    ]


def test_classifier_reports_safe_validation_location(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "items": [
                                            {
                                                "source_ordinal": 1,
                                                "reporting_category": "Transport",
                                                "movement_kind": "Expense",
                                                "payment_channel": "Mobile",
                                                "confidence": 0.88,
                                                "rationale": "Unknown channel",
                                            }
                                        ]
                                    }
                                )
                            }
                        }
                    ]
                }
            ).encode()

    monkeypatch.setattr(
        "bank_statement_assistant.statements.classification.request.urlopen",
        lambda *_args, **_kwargs: Response(),
    )

    with pytest.raises(
        ClassificationError, match=r"items\.0\.payment_channel:literal_error"
    ) as raised:
        OpenAICompatibleTransactionClassifier(
            base_url="http://vllm:8000/v1", model="bank-statement-qwen"
        ).classify((transaction_input(),))

    assert "Mobile" not in str(raised.value)
    assert "Unknown channel" not in str(raised.value)
    assert raised.value.error_code == "classify_invalid_response"


def test_classifier_reports_unreachable_inference_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def urlopen(*_args: object, **_kwargs: object) -> object:
        raise OSError("connection details must not escape")

    monkeypatch.setattr(
        "bank_statement_assistant.statements.classification.request.urlopen",
        urlopen,
    )

    with pytest.raises(ClassificationError, match="classification request failed") as raised:
        OpenAICompatibleTransactionClassifier(
            base_url="http://vllm:8000/v1", model="bank-statement-qwen"
        ).classify((transaction_input(),))

    assert raised.value.error_code == "classify_inference_unreachable"


def test_classifier_reports_an_http_error_as_an_invalid_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def urlopen(*_args: object, **_kwargs: object) -> object:
        raise error.HTTPError("http://vllm:8000/v1/chat/completions", 400, "bad request", {}, None)

    monkeypatch.setattr(
        "bank_statement_assistant.statements.classification.request.urlopen",
        urlopen,
    )

    with pytest.raises(ClassificationError) as raised:
        OpenAICompatibleTransactionClassifier(
            base_url="http://vllm:8000/v1", model="bank-statement-qwen"
        ).classify((transaction_input(),))

    assert raised.value.error_code == "classify_invalid_response"
