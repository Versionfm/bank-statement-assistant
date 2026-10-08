"""PostgreSQL adapter for replayable merchant evidence snapshots."""

import json
import re
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any, cast

from sqlalchemy import create_engine, text

from bank_statement_assistant.statements.merchant_evidence import (
    EvidenceSource,
    MerchantEvidence,
)


class PostgresMerchantEvidenceCache:
    def __init__(self, database_url: str) -> None:
        self._engine = create_engine(database_url, pool_pre_ping=True)

    def get(self, key: str) -> MerchantEvidence | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT provider, status, query, evidence, response_hash, fetched_at
                        FROM merchant_evidence_cache
                        WHERE normalized_key = :normalized_key
                          AND expires_at > now()
                        """
                    ),
                    {"normalized_key": key},
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        evidence = cast(dict[str, Any], row["evidence"])
        stored_query = cast(str, row["query"])
        query_hash = (
            stored_query
            if re.fullmatch(r"[0-9a-f]{64}", stored_query)
            else sha256(stored_query.encode("utf-8")).hexdigest()
        )
        return MerchantEvidence(
            status=cast(Any, row["status"]),
            provider=cast(str, row["provider"]),
            query="[cached-query-redacted]",
            query_hash=query_hash,
            sources=tuple(
                EvidenceSource(
                    title=source["title"],
                    url=source["url"],
                    domain=source["domain"],
                    snippet=source["snippet"],
                    content_hash=source["content_hash"],
                )
                for source in cast(list[dict[str, str]], evidence.get("sources", []))
            ),
            response_hash=cast(str | None, row["response_hash"]),
            fetched_at=cast(datetime | None, row["fetched_at"]),
            pages_fetched=int(evidence.get("pages_fetched", 0)),
            escalation_reason=cast(str | None, evidence.get("escalation_reason")),
        )

    def put(self, key: str, evidence: MerchantEvidence, ttl_seconds: float) -> None:
        evidence_json = {
            "pages_fetched": evidence.pages_fetched,
            "escalation_reason": evidence.escalation_reason,
            "sources": [
                {
                    "title": source.title,
                    "url": source.url,
                    "domain": source.domain,
                    "snippet": source.snippet,
                    "content_hash": source.content_hash,
                }
                for source in evidence.sources
            ],
        }
        expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO merchant_evidence_cache (
                        normalized_key, query, provider, status, evidence,
                        response_hash, fetched_at, expires_at
                    ) VALUES (
                        :normalized_key, :query, :provider, :status,
                        CAST(:evidence AS jsonb), :response_hash, :fetched_at, :expires_at
                    )
                    ON CONFLICT (normalized_key) DO UPDATE SET
                        query = EXCLUDED.query,
                        provider = EXCLUDED.provider,
                        status = EXCLUDED.status,
                        evidence = EXCLUDED.evidence,
                        response_hash = EXCLUDED.response_hash,
                        fetched_at = EXCLUDED.fetched_at,
                        expires_at = EXCLUDED.expires_at
                    """
                ),
                {
                    "normalized_key": key,
                    "query": sha256(evidence.query.encode("utf-8")).hexdigest(),
                    "provider": evidence.provider,
                    "status": evidence.status,
                    "evidence": json.dumps(evidence_json),
                    "response_hash": evidence.response_hash,
                    "fetched_at": evidence.fetched_at,
                    "expires_at": expires_at,
                },
            )

    def dispose(self) -> None:
        self._engine.dispose()
