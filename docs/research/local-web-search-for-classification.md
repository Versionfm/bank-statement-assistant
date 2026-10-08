# Methods to implement web search for the local LLM

Research date: 2026-09-06

## Decision

Use **host-controlled web search** for transaction classification. The worker decides when a bounded merchant lookup is allowed, executes a typed provider adapter, validates and limits the response, caches the evidence, and then sends only bounded snippets to the local LLM. The model may use the evidence as context, but it must not own network access or decide an unbounded browsing plan.

Keep MCP as a separate interface for the Financial Assistant. Do not make statement processing or classification depend on an MCP round trip. This preserves the existing application boundary and means a failed search never becomes an LLM or parser fallback: the transaction remains classifiable only under the existing validation/acceptance policy, otherwise it stays `Needs Review`.

## What the model can and cannot do

A local model does not acquire network access merely because it is running on the same machine. There are three distinct pieces:

```text
local LLM (vLLM/Qwen)
        ^ structured evidence or tool result
        |
application host  ---- HTTPS ----> search provider or SearXNG
        |
        +---- validation, limits, cache, provenance
```

Qwen describes function calling as an application providing functions, the model selecting a function and arguments, and the application invoking it and returning the result. Qwen also warns that malformed tool calls can occur and recommends application-side parsing for production. ([Qwen function calling](https://qwen.readthedocs.io/en/stable/framework/function_call.html))

vLLM implements the tool-call transport and schema constraints, but explicitly assigns tool definition, context, and execution to the caller. `tool_choice="auto"` permits the model to choose; named or `required` choices provide stronger schema guarantees, not better search judgment. ([vLLM tool calling](https://docs.vllm.ai/en/stable/features/tool_calling/))

Therefore, model-directed search is appropriate for an interactive assistant, but is a poor control loop for background classification: it adds an unbounded decision, variable latency, and another place where private transaction text could be disclosed. The worker should retain the host-controlled lookup policy.

## Candidate methods

| Method | Network owner | Strength | Boundary/risk | Decision |
| --- | --- | --- | --- | --- |
| Typed provider adapter in the worker | Application | Deterministic limits, easy provenance and retries policy | Provider-dependent quality and credentials | **Use for classification** |
| vLLM/Qwen function calling | Host executes model-selected calls | Natural for multi-step assistant workflows | Nondeterministic tool choice; malformed arguments; prompt injection in results | Use only behind a strict host loop for interactive assistant work |
| MCP web-search tool | MCP server/host | Portable tool contract and discovery | Extra process/transport; consent and authorization; not needed for worker | Keep for Financial Assistant only |
| Self-hosted SearXNG | Application calls local HTTP service | No per-request provider key; configurable metasearch | Requires Docker/Podman or another service runtime; queries are passed to configured external search services | Optional local provider |
| Managed Brave/Tavily adapter | Application calls hosted API | Operationally simple and stable JSON APIs | API key, cost/limits, transaction-derived query leaves the host | Optional provider with explicit user opt-in |

MCP defines tools as functions a server exposes for a model to execute, but its security guidance requires explicit consent and control before exposing user data or invoking tools. ([MCP specification: architecture and trust & safety](https://modelcontextprotocol.io/specification/2025-03-26/index)) That is appropriate for a user-facing assistant, not a hidden worker dependency.

## Provider findings

### SearXNG

SearXNG exposes `/` and `/search` over GET or POST. JSON output requires `format=json` to be enabled in the instance settings; public instances may disable machine-readable formats. Its own documentation states that the query is passed to external search services, so self-hosting reduces control-plane dependence but does not make the search query offline or guarantee that no upstream engine sees it. ([SearXNG Search API](https://github.com/searxng/searxng/blob/master/docs/dev/search_api.rst))

The official container documentation recommends Compose instancing and requires Docker or Podman. It also documents persistent configuration/data mounts and a separate service lifecycle. SearXNG is consequently a good local **service provider**, but not a self-contained single `.exe` dependency. ([SearXNG container installation](https://github.com/searxng/searxng/blob/master/docs/admin/installation-docker.rst))

Adapter contract:

```text
GET {base_url}/search
  ?q={urlencoded merchant query}
  &format=json
  &categories=general
  &safesearch=1

read only: results[].title, results[].url, results[].content
```

The adapter must enforce the same URL scheme, domain, result-count, snippet-length, timeout, and response-byte limits as every other provider. It must not accept provider-generated answer text as a classification decision.

### Brave Search

Brave's official API uses `GET https://api.search.brave.com/res/v1/web/search`, JSON responses, and the `X-Subscription-Token` header. The API documentation also says the key must remain confidential and must not be exposed in client-side code or public repositories. ([Brave Search API](https://brave.com/search/api/), [Brave authentication](https://api-dashboard.search.brave.com/documentation/guides/authentication))

The repository already implements this path in `src/bank_statement_assistant/adapters/web_search.py`. It is a suitable managed-provider adapter, but the key must stay in backend/Kubernetes secret configuration. The current invalid-key behavior was correctly treated as provider unavailability; it must not trigger a second model or parser path.

### Tavily as another managed adapter

Tavily's official endpoint is `POST /search` with Bearer authentication. It exposes explicit `search_depth`, `max_results`, domain filters, and optional answer/raw-content fields. For this application, use basic/fast search, a small result cap, and leave `include_answer` and `include_raw_content` disabled; only bounded source snippets should enter the classifier. ([Tavily Search API](https://docs.tavily.com/documentation/api-reference/endpoint/search))

The interface should not encode provider-specific authentication or response shapes. Each provider maps into the same `MerchantEvidence` result, with `provider`, `status`, source URL/domain/title/snippet, response hash, and fetch time.

## Recommended application architecture

The current flow should remain:

```text
PDF
  -> deterministic bank parser
  -> validated transaction records
  -> worker classification stage
  -> MerchantNormalizer
  -> at most one lookup per normalized merchant key
  -> ProviderAdapter (disabled | SearXNG | Brave | Tavily)
  -> bounded evidence cache
  -> local LLM structured classification
  -> schema/domain validation and provenance
  -> Ready or Needs Review
```

The existing seams are already visible in:

- `src/bank_statement_assistant/statements/merchant_evidence.py`: `MerchantEvidenceProvider`, normalization, cache wrapper, and research safety cap;
- `src/bank_statement_assistant/adapters/web_search.py`: current Brave HTTP adapter;
- `src/bank_statement_assistant/adapters/worker/main.py`: feature flag, provider construction, and classifier wiring;
- `src/bank_statement_assistant/adapters/postgres/merchant_evidence.py`: durable cache;
- `src/bank_statement_assistant/statements/classification.py`: bounded evidence payload sent to the model;
- `docs/adr/0016-bounded-research-for-classification.md`: advisory research policy;
- `docs/adr/0004-use-mcp-for-the-financial-assistant.md`: MCP exclusion from statement processing.

### Provider-neutral configuration

Replace the current implicit `enabled + API key => Brave` selection with an explicit provider registry:

```text
BSA_SEARCH_PROVIDER=disabled|searxng|brave|tavily
BSA_SEARCH_BASE_URL=...
BSA_SEARCH_API_KEY=...              # required only by managed providers
BSA_SEARCH_TIMEOUT_SECONDS=8
BSA_SEARCH_MAX_RESULTS=5
BSA_SEARCH_CACHE_TTL_SECONDS=604800
```

Only one provider is active per worker. `disabled` must be a valid production mode. A missing key, invalid response, timeout, rate limit, or malformed result yields `unavailable`; it does not invoke another LLM, another parser, or an uncontrolled provider chain.

### Query minimization

Only send a normalized merchant/provider query. Do not send account reference, account number, amount, balance, transaction date, counterparty's full name when it is not required, PDF text, or the complete original description. Do not log the raw query, API key, response body, or snippets containing unrelated personal data. Store hashes and bounded provenance instead.

OWASP recommends that access tokens, bank-account/payment-card data, sensitive personal data, and other secrets be removed, masked, hashed, or encrypted rather than recorded directly in logs. ([OWASP Logging Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html))

Self-hosted SearXNG is not automatically private: its documentation states that the query is passed to external search services. A local instance is still valuable because the app controls the instance and its configured engines, but the UI should describe this accurately and require an explicit research setting.

### Cache and freshness

Use a durable cache key based on normalized merchant, country, provider identity, and query-affecting options. Store positive and negative results, source hashes, provider status, fetched time, and expiry. The current seven-day TTL is a reasonable starting value for merchant identity, not a permanent truth.

HTTP caching standards define freshness as an explicit lifetime and allow a fresh response to satisfy later requests without contacting the origin. The application cache should apply the same explicit-TTL principle even when a provider does not expose useful cache headers. ([RFC 9111: HTTP Caching](https://www.rfc-editor.org/rfc/rfc9111.html))

For correctness:

1. Return a fresh cache hit without a network call.
2. On expiry, perform one bounded lookup; coalesce concurrent lookups for the same key if the worker is later parallelized.
3. Keep stale evidence distinguishable from fresh evidence; never silently present it as newly verified.
4. Cache `not_found` and `unavailable` only for a short negative/error TTL, or record the status without allowing it to suppress a later retry for the full seven days.
5. Keep classification acceptance independent of evidence freshness and provider availability.

### Evidence handling

Treat every title, URL, and snippet as untrusted external input. Validate HTTPS/HTTP URLs, cap lengths and count, strip control characters, and pass only source metadata/snippets to the classifier. The evidence may inform a category but may not alter the taxonomy, movement rules, reporting-category rules, reconciliation, or database state.

The model output still requires strict schema validation and domain validation. Web search improves context; it does not make the model authoritative.

### Deterministic two-page browser search

The browser provider should inspect the first result page, evaluate it locally, and fetch a second page only when the first page is insufficient. The model never chooses a page number or navigation action. The public tool input remains only normalized `provider_info`; page number, query construction, and continuation state are host-controlled.

Page one is insufficient when any of these deterministic checks holds:

- fewer than three valid results remain after URL and length validation;
- no result has an exact or close normalized provider-name match;
- no result is consistent with the requested country/city when that information exists;
- results disagree on the likely business type or identify multiple unrelated providers;
- the page contains only a block, consent wall, CAPTCHA, or generic directory content.

The host may then execute the same provider adapter once for page two using the provider's fixed pagination mechanism. Merge and deduplicate both pages by canonical URL, retain a maximum of ten bounded sources, and stop after page two. If evidence is still insufficient or conflicting, return `ambiguous` and route the transaction to `Needs Review`; do not continue browsing indefinitely or invoke an alternate LLM/parser path.

Persist the page number and deterministic insufficiency reason in research provenance. This makes the extra lookup observable and replayable while retaining a strict two-page/network/time budget.

## MCP exposure

Do not expose the classification search provider through MCP in the first implementation. The worker already has a direct typed interface and needs a bounded, repeatable workflow. Adding MCP would introduce a second network hop and a separate authorization/availability boundary without improving classification quality.

If the Financial Assistant later needs merchant research, expose a separate read-only, allowlisted `search_merchant` tool through the existing loopback Streamable HTTP MCP sidecar. The MCP handler should call the same provider service, apply the same query minimization and limits, and return cited evidence. It must not receive raw PDF text or expose arbitrary URL fetching, shell execution, generic HTTP, or arbitrary SQL.

For model-directed assistant calls, the host must validate the tool name and JSON arguments, execute only allowlisted handlers, append the tool result, and audit the call. MCP annotations and model intent are not authorization. The ordinary application remains responsible for any durable financial mutation.

## Portability and `.exe` distribution

SearXNG should be an optional provider, not a requirement for the application to start:

- **Default desktop mode:** `BSA_SEARCH_PROVIDER=disabled`; deterministic parsing and local classification work without an external search service.
- **User-managed hosted mode:** the user supplies a provider endpoint/key; keys are stored in local protected configuration and never shipped in the executable.
- **Advanced local mode:** an installer or setup wizard starts a pinned SearXNG Docker/Podman service and configures the executable to use `http://127.0.0.1/...`. This is a multi-process installation, not a single portable executable.
- **Offline enrichment:** ship a curated merchant registry and durable evidence cache; unknown merchants remain `Needs Review`.

Do not use a public SearXNG instance as the default for bank-derived queries. It creates an uncontrolled dependency, may disable JSON output, and can expose merchant queries to an unknown operator or upstream engines.

## Implementation sequence

1. Define `SearchRequest`, `SearchResult`, and provider error/status semantics in the domain module.
2. Rename the current generic web adapter to an explicit Brave adapter while preserving the `MerchantEvidenceProvider` interface.
3. Add a SearXNG adapter with `format=json`, no API-key header, strict response validation, configurable base URL, and deterministic page-one/page-two pagination.
4. Add a provider registry selected by explicit configuration; fail closed to `disabled` when configuration is absent or invalid.
5. Separate positive, negative, and unavailable cache TTLs and include provider/options in the cache key.
6. Add privacy tests proving account references, amounts, dates, and raw descriptions never leave the process or appear in logs.
7. Add provider contract fixtures for Brave, SearXNG, Tavily, malformed JSON, HTTP errors, timeouts, oversized results, invalid URLs, and empty results.
8. Add worker integration tests proving one lookup per normalized merchant key, page-two execution only after an insufficiency reason, result deduplication, durable cache reuse, bounded prompt payloads, provenance, and `Needs Review` on unavailable or ambiguous evidence where policy requires it.
9. Add an opt-in settings path for local SearXNG and document Docker/Podman lifecycle separately from the `.exe` workflow.
10. Only after classification is stable, consider an MCP `search_merchant` tool for the Financial Assistant, reusing the same service rather than duplicating provider logic.

## Acceptance gates

- Parser behavior is unchanged and remains deterministic/offline.
- No API key is present in frontend bundles, logs, source control, or a distributed executable.
- A provider failure never triggers an LLM fallback, parser fallback, or forced category.
- Every external lookup is bounded by query policy, timeout, result count, snippet size, and cache policy.
- Every classification can show provider, status, cache state, timestamps, and cited source hashes.
- Offline mode can import, parse, classify locally, and route unknown/low-confidence cases to review.
- SearXNG mode works only when its local service is healthy and its JSON format is enabled.
- Managed-provider mode works with a user-supplied secret and has a clear disabled state when no key is configured.
