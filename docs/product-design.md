# Bank Statement Assistant Product Design

Status: confirmed design
Confirmed: 2026-09-01
Implementation authorization: granted 2026-09-01. Increment 1 and verified first vertical slices
of Increment 2 and Increment 3 are implemented; the remainder of Increment 2 and later increments
remain pending until their acceptance checks pass.

## 1. Product intent

Bank Statement Assistant is a private, single-user web application that runs entirely on the user's machine in k3s. It imports monthly bank-statement PDFs, uses a local language model to extract and classify Transactions, enforces deterministic financial validation, lets the user review and correct results, and presents live monthly reports answering: **Where did my money go this month?**

The first supported input is an unencrypted, text-based BPI PDF. The application is a Statement-analysis product, not a general ledger, payment system, budgeting platform, or financial adviser.

### MVP success

The MVP succeeds when the user can:

1. Drop one or more supported PDFs into the application.
2. See whether each import, extraction, validation, and Classification succeeded.
3. Review uncertain or invalid results and apply reversible Corrections.
4. Browse, filter, sort, and paginate Transactions.
5. Open a trustworthy Monthly Report with correct totals.
6. Upload the same Statement again without duplicating it or its Transactions.
7. Retain Corrections through retries, model upgrades, and report regeneration.
8. See reports ordered by booking-date month rather than upload order, so August remains before July even when July is imported later.
9. Ask the Financial Assistant grounded questions about the imported data and receive cited answers.

## 2. Scope

### Included

- Single user on one local machine
- Loopback or port-forward access to k3s
- Unencrypted, text-based BPI PDFs
- Multi-file drag-and-drop, with each Statement processed independently
- Bank Account identification and safe local naming
- Deterministic bank-layout extraction, local-LLM Classification, and whole-Statement review
- Deterministic validation and reconciliation
- Durable asynchronous processing and retries
- Transaction review, filtering, sorting, pagination, Corrections, and reversion
- User-approved Classification Rules
- Live EUR Monthly Reports
- A Financial Assistant page backed by cluster-local MCP tools
- Local encrypted backup and tested restoration

### Explicitly excluded

- Multiple users, tenancy, sharing, or authentication
- LAN or public exposure
- n8n and Google Drive
- Legacy-database migration or reuse of the predecessor workflow/schema
- OCR, scanned PDFs, and password-protected PDFs
- Banks or layouts beyond explicitly supported BPI formats
- Currency conversion
- Budgets, forecasting, payments, investment advice, tax advice, credit advice, or legal advice
- Native mobile applications
- Raw database administration in the product
- Autonomous model writes

Historical data enters by re-importing its source PDFs through the new pipeline. The predecessor repository may inform synthetic or redacted test scenarios, but its workflow-shaped implementation is not copied into this application.

## 3. User experience

The application has five first-class pages.

Interface copy is English in the MVP, while dates and euro amounts follow Portuguese display conventions. User-facing strings remain externalized so Portuguese translation can be added without rewriting screens.

### 3.1 Statements

- Accept one or more PDFs by drag-and-drop.
- Verify the PDF signature, generate a safe storage name, hash the content, and enforce configured file, page, and processing limits.
- Reject encrypted, malformed, scanned, and unsupported PDFs with a precise reason.
- Show the Statement Status, current stage, progress, Review Findings, Processing Attempts, and retry controls.
- Resolve the Bank Account from a fingerprint of the statement identifier. Ask the user to confirm a safe nickname for a new account; never let the model guess an account.
- Surface exact duplicate uploads by linking to the existing Statement rather than processing them again.
- Permit archive by default. Permanent deletion requires explicit confirmation and removes the source PDF and dependent financial history before reports are recalculated.

### 3.2 Transactions

- Search and filter by booking date, value date, amount, Bank Account, Statement, Counterparty, Reporting Category, Movement Kind, Payment Channel, and review state.
- Sort supported columns and paginate results.
- Display Original Values, Effective Values, Classification provenance, confidence, Review Findings, and Correction history.
- Permit Corrections to Counterparty, Reporting Category, Movement Kind, Payment Channel, Transfer Scope, note, and demonstrably incorrect financial facts.
- Render before/after values, record a reason, support reversion, and never erase history.
- Offer an explicit **Apply to future matches** action for a user-approved Classification Rule.

### 3.3 Reports

- Default to the newest booking-date month with data and show months in descending chronological order.
- Show Income, Gross Spending, Refunds, Net Spending, Net Cash Flow, and change from the preceding month.
- Break spending down by Reporting Category, Counterparty, largest Transactions, and Payment Channel.
- Show Transfers separately with incoming/outgoing direction and an explicit transfer scope (`own_account`, `external_party`, or `unknown`).
- Include all signed Transfers in Net Account Flow; keep Net Cash Flow focused on Income, Refunds, Expenses, and Fees.
- Make each category, Counterparty, Payment Channel, and transfer bucket open an exact, paginated Transaction drill-down.
- Show provisional totals and the unresolved amount/count when Needs Review data contributes.
- Keep non-EUR Transactions visible but separate from EUR aggregates.
- Recalculate live from Effective Values; do not persist duplicate report totals as authoritative records.

### 3.4 Rules

- List, create, preview, enable, disable, and delete Classification Rules.
- Match safe, typed conditions such as normalized raw description, Counterparty, Bank Account, Payment Channel, and optional amount range.
- Do not expose arbitrary regular expressions in the MVP.
- Before saving, preview matches and let the user choose future only, current and future, or historical and future application.

### 3.5 Financial Assistant

- Persist local conversations across reloads and restarts.
- Answer questions about Transactions, classifications, review findings, Monthly Reports, trends, recurring spending, and unusual spending.
- Cite the supporting Statement, Transaction, month, or report section with links.
- State when evidence is missing, provisional, or inconclusive.
- Use backend-computed aggregates rather than doing financial arithmetic in model text.
- May create a Correction Proposal, but cannot apply it.
- Show Correction Proposals as explicit before/after diffs for user approval or rejection.

## 4. Domain model and invariants

Canonical terms are defined in [`CONTEXT.md`](../CONTEXT.md). The essential relationships are:

```text
Bank Account
  └── Statement
        ├── source PDF
        ├── Processing Attempts
        ├── Review Findings
        └── Transactions
              ├── Original Values
              ├── Corrections → Effective Values
              ├── Classification results
              └── Classification Rules

Monthly Report ← Effective Transaction Values
Financial Assistant ← cited queries and Correction Proposals
```

### 4.1 Statement lifecycle

A Statement has one of four trust states:

- **Processing**: at least one stage is running or durably queued.
- **Needs Review**: processing completed, but one or more financial or Classification concerns remain.
- **Ready**: required extraction and reconciliation checks passed, and Classification uncertainty is resolved or explicitly accepted.
- **Failed**: no usable result can be produced from the current Processing Attempt.

A retry creates another Processing Attempt for the same Statement. It does not create another Statement or duplicate Transactions. Failed Statements do not contribute to reports. Needs Review Statements may contribute provisionally, with a prominent warning and quantified unresolved data.

The user may accept or correct Classification uncertainty. The user cannot dismiss inconsistent financial facts merely to force `Ready`; the questionable values must be corrected and validation rerun.

Each Bank Account retains a user-selected nickname, institution, masked identifier, currency, and a salted fingerprint of the bank identifier. The application does not display or retain the full identifier as ordinary structured account data after matching; the original Statement remains the source evidence.

### 4.2 Transaction evidence

Required Original Values are booking date, raw description, signed amount, and ISO currency. Retain value date, running balance, bank reference, source page, and source-text location when available.

Original Values are immutable. A Correction is an append-only, field-level event. Effective Values are derived from the latest active Corrections, falling back to Original Values. Reversion creates another event rather than deleting history.

All money uses exact decimal representations, never binary floating point. Booking and value dates are calendar dates. Processing and audit timestamps are UTC and display in `Europe/Lisbon`.

### 4.3 Duplicate identity

- The source PDF content hash makes exact uploads idempotent.
- Transaction source identity includes Bank Account and available bank/source evidence such as reference, dates, signed amount, balance, raw description, and occurrence position.
- Deduplication must not rely only on date, amount, and description because legitimate repeated purchases can share those values.
- Overlapping Statements add only previously unseen Transactions while preserving Statement lineage.

### 4.4 Classification

Classification has three independent dimensions:

- **Reporting Category**: why or how the movement is reported.
- **Movement Kind**: Expense, Income, Transfer, Refund, or Fee.
- **Payment Channel**: MB WAY, Card, Bank Transfer, Direct Debit, Cash Withdrawal, or another supported mechanism.
- **Transfer Scope**: `own_account` for movement between the user's accounts, `external_party` for money sent to or received from another person/entity, or `unknown` when review is required.

An MB WAY restaurant payment is therefore `Restaurants & Cafes` + `Expense` + `MB WAY`. `Transfer` is reserved for movement between Bank Accounts owned by the user; a bank transfer to a landlord, shop, or another person is normally an Expense.

The initial Reporting Categories are:

- Expenses: Groceries; Restaurants & Cafes; Housing; Utilities; Transport; Health; Insurance; Subscriptions; Shopping; Leisure; Travel; Education; Gifts & Donations; Taxes; Other Expense
- Income: Salary; Interest; Other Income
- Fees: Bank Fees
- Refunds: inherit the linked original category when possible; otherwise remain reviewable
- Transfers: no Reporting Category required

`Unclassified` is a review state, not a Reporting Category. `Other Expense` is an intentional valid category.

Classification responses pass through global deterministic normalization before validation. When a response marks a Transaction as `Transfer`, the effective Reporting Category is always `null`; any conflicting model-provided category is recorded as the `transfer_reporting_category_nullification_v1` rule. This rule is bank-agnostic and does not change the deterministic Statement parser.

Effective Classification precedence is:

```text
Manual Correction
  > user-approved Classification Rule
  > accepted LLM Classification
  > Unclassified
```

Reprocessing and model upgrades never overwrite a manual Correction. Every model, rule, or fallback result retains its model, model revision, prompt, taxonomy, rule, and application versions. Extraction routing retains detector, layout, parser, strategy, and routing-evidence provenance; validation retains its version and findings separately as the validation-stage result.

Approved Corrections may be retrieved as a small set of relevant prompt examples without silently becoming rules or model training data.

### 4.5 Monthly calculations

Reports use booking-date calendar months, never upload timestamps or value-date months.

- **Gross Spending** = Expenses + Fees
- **Net Spending** = Gross Spending - Refunds booked in the month
- **Net Cash Flow** = Income + Refunds - Expenses - Fees
- **Net Account Flow** = Net Cash Flow + Transfer In - Transfer Out
- Transfers are displayed separately; their signed direction contributes to Net Account Flow regardless of scope, while scope explains whether the movement is internal or with an external party.

A Refund is recorded in its booking month. When linked to its original Transaction, the relationship is shown without silently rewriting an earlier month's cash flow.

EUR is the Reporting Currency. Original non-EUR values are preserved and displayed separately; the application does not invent exchange rates or combine them into EUR totals.

## 5. Statement processing

```text
PDF upload
  → deterministic file and layout-preserving text extraction
  → deterministic BankDetector and ParserRegistry routing
  → registered bank-layout parser
  → deterministic schema and financial validation
  → Classification Rules
  → local-LLM Classification for unmatched Transactions
  → whole-Statement review
  → Ready | Needs Review | Failed
  → live Monthly Reports
```

### 5.1 Stages

1. **Accept**: validate the file envelope, hash and store it, resolve duplicate identity, and create or match a Bank Account.
2. **Extract text**: obtain deterministic text and source locations from the PDF. This stage is bank-neutral and does not decide financial meaning.
3. **Extract Transactions**: route a verified bank layout to its registered deterministic parser. Unknown, ambiguous, unregistered, or drifted layouts are rejected as unsupported and never sent to an LLM. Adding support requires a new parser adapter and fixture-backed validation before registration.
4. **Validate**: enforce types, dates, decimal formatting, signs, row count, opening/closing balance, and running-balance continuity when the Statement supplies that evidence.
5. **Classify**: apply human Corrections and Classification Rules first, then request structured LLM Classification for remaining Transactions.
6. **Review**: perform a separate evidence-based whole-Statement pass. The reviewer emits findings and proposals but never silently mutates evidence.
7. **Publish state**: mark Ready, Needs Review, or Failed and update live reports.

Each stage persists its result so later stages can retry without repeating earlier successes. Transient model/network/worker failures retry up to three times with backoff. Unsupported input, inconsistent financial facts, or repeatedly malformed model output creates a Review Finding or Failed result instead of an infinite retry loop.

The bank-neutral `StatementExtractor` interface is implemented only by registered deterministic parsers. `BankDetector` and `ParserRegistry` are internal to Statement Extraction, so the worker does not branch on bank names or call bank-specific methods. A verified `BankLayoutId` selects one registered parser with its own parser ID and version; ambiguous, unknown, or newly drifted layouts fail with an unsupported-layout reason. Adding another bank requires a new validated parser adapter and layout fixtures, not changes to Transaction, Classification, Correction, or Reporting semantics.

Review triggers include financial-reconciliation failures, missing or ambiguous facts, possible duplicate ambiguity, invalid model output, Unclassified results, and low-confidence Classification according to thresholds calibrated on the private evaluation corpus. An unfamiliar Counterparty alone does not flood the review queue.

## 6. Application architecture

The implementation is a modular monolith: deep Python modules own behaviour, while HTTP, worker, MCP, PostgreSQL, filesystem, and vLLM integrations are adapters at explicit seams.

### 6.1 Technology

- Python and FastAPI for the backend, worker, and MCP implementation
- PostgreSQL with versioned Alembic migrations
- React and TypeScript for the browser interface
- REST/JSON with generated OpenAPI types
- Server-Sent Events for Statement progress and streamed assistant responses
- k3s for local deployment
- vLLM for the OpenAI-compatible local-model endpoint

No Redis, external broker, object store, GraphQL, or WebSocket dependency is required for the MVP.

### 6.2 Deep modules

| Module | Small external interface | Invariants hidden by the implementation |
|---|---|---|
| Statements | ingest, inspect, retry, archive, permanently delete | file safety, Bank Account resolution, duplicate identity, Processing Attempts, stage transitions, parser routing, Review Findings |
| Transactions | search, inspect, correct, revert, manage rules | Original/Effective Values, append-only history, Classification precedence, Counterparty normalization |
| Classification | classify validated batches, review a Statement | prompt/schema versions, structured-output validation, approved examples, abstention, provenance |
| Reporting | calculate a Monthly Report | exact arithmetic, booking-month membership, Refund and Transfer treatment, provisional contribution, currency separation |
| Financial Assistant | stream an answer, inspect/resolve proposals | conversations, MCP orchestration, evidence citations, tool limits, stale proposals, audit trail |
| Inference | submit a role-profiled request with priority | one shared endpoint, bounded contexts, scheduling, cancellation/timeouts, model metadata, graceful failure |

Tests and adapters use these same interfaces. PostgreSQL or MCP adapters do not reimplement report arithmetic, Classification precedence, validation, or Correction rules.

### 6.3 Persistence

The logical relational records include:

- Bank Accounts
- Statements and source-file metadata
- Processing Attempts and durable jobs
- Transactions and Original Values
- Correction events and derived Effective Values
- Classification results and Classification Rules
- Review Findings
- Conversations, messages, tool-call audits, and cited record identifiers
- Correction Proposals and outcomes

Use explicit columns, constraints, relationships, and indexes for authoritative data. Raw model requests/responses may be retained as protected audit payloads but are not the authoritative financial model.

Original PDFs live on a dedicated local PVC with generated paths. PostgreSQL stores content hashes and metadata rather than PDF binaries. PostgreSQL jobs are claimed durably by one Statement worker; in-memory background tasks are insufficient.

### 6.4 k3s topology

```text
Browser on k3s host
        │ loopback / port-forward
        ▼
┌──────────────── Web Pod ────────────────┐
│ React + FastAPI                        │
│ Financial Assistant MCP client         │
│                 │ loopback HTTP        │
│                 ▼                      │
│ MCP sidecar: thin tool adapters        │
└─────────────────┬───────────────────────┘
                  │ shared application modules / PostgreSQL
        ┌─────────┴───────────┐
        ▼                     ▼
Statement worker          PostgreSQL StatefulSet
        │                     │ durable data PVC
        │                     └───────────────┐
        ▼                                     ▼
vLLM ClusterIP                         Statement PDF PVC
        │
        ▼
RTX 5070 Ti Laptop GPU, approximately 12 GB VRAM
```

The web application, Statement worker, and MCP sidecar use the same application image with different process commands and share the deep Python modules. PostgreSQL, vLLM, and MCP have no public ingress. A dedicated migration Job applies Alembic migrations before updated application processes become ready.

## 7. Local model architecture

One persistent, private vLLM endpoint serves Classification, review, and Financial Assistant roles. Request context comes from each request; the application does not restart the deployment or clear KV cache between Classification, review, and chat.

### 7.1 Model policy

- Baseline: `Qwen/Qwen3-8B-AWQ`
- Promotion candidate: `Qwen/Qwen3-14B-AWQ`
- 8B initial maximum context: 8,192 tokens
- 14B experiment: 4,096 tokens and one active sequence
- Non-thinking mode for all roles initially
- No automatic CPU offload; prefer the 8B baseline if 14B does not fit
- Pin vLLM image digest, model revision, parsers, and runtime configuration after exact-hardware smoke tests

The model name, endpoint, revision, context, and parser settings are centralized in application and vLLM configuration rather than hard-coded across callers.

### 7.2 Role profiles

| Role | Input/output contract | Tools | Priority |
|---|---|---|---|
| Transaction extraction | bounded source text to strict structured facts | none | background |
| Classification | validated Transactions and bounded merchant context to strict Classification results | internal bounded merchant lookup (feature-flagged) | background |
| Statement review | source evidence plus persisted results to Review Findings/proposals | none | background |
| Financial Assistant | bounded chat history and MCP results to cited text/tool calls | allowlisted MCP tools | interactive |

Only one model request runs at a time initially. Statement work uses bounded requests. A running request is not killed when chat arrives; chat is scheduled before the next background batch. Existing reports, Transactions, Rules, and Corrections remain usable when vLLM is unavailable. Statement work remains durable and retryable, while the assistant displays an unavailable state.

Classification research is an application-controlled enrichment step, not parser logic and not an MCP dependency. For each normalized merchant key, the worker performs at most one provider lookup, stores a TTL-bounded evidence snapshot, and sends bounded source titles/domains/snippets to the classifier as advisory context. The feature is disabled by default. Unavailable research is recorded in provenance and keeps the decision below the acceptance threshold; it never forces a category or bypasses deterministic validation. Source URLs and hashes are retained for review without logging private statement text.

The 14B candidate is promoted only when it materially improves the agreed evaluation measures without OOM, unacceptable instability, or unusable chat latency.

## 8. Financial Assistant and MCP

MCP is used only for the Financial Assistant. Statement extraction, validation, Classification, and review call internal module interfaces directly.

### 8.1 Deployment and transport

- Streamable HTTP
- Separate MCP process/container in the Web Pod
- Loopback binding only
- No Kubernetes Service, Ingress, browser access, or CORS
- Pinned compatible MCP client/server SDKs and protocol behavior
- No conversation or financial state in transport sessions

If MCP later moves to another Pod, that change requires a private ClusterIP, restrictive NetworkPolicy, conformant service authentication, and a renewed security decision.

### 8.2 Tool interface

| Tool | Behavior |
|---|---|
| `search_transactions` | typed filters, sorting, and cursor pagination; maximum 50 Transactions per page |
| `get_monthly_report` | authoritative backend-computed monthly totals and comparisons |
| `get_statement_review` | Statement Status, Review Findings, and validation evidence |
| `get_classification_details` | model, prompt, rule, Correction, confidence, and provenance details |
| `propose_correction` | creates one immutable non-binding Correction Proposal with an idempotency key |

The first four tools are read-only and closed-world. `propose_correction` is additive and non-destructive, but it is still a durable mutation. MCP annotations are hints, not security controls; typed application modules and database permissions enforce behavior.

Do not expose arbitrary SQL, generic filesystem access, infrastructure operations, or an `apply_correction` tool.

### 8.3 Agent controls

- At most five tool calls per assistant turn
- At most one outstanding Correction Proposal per turn
- Bounded report periods, result sizes, and timeouts
- Tool names and arguments validated before execution
- Transaction descriptions and Statement text treated as untrusted data, never instructions
- Financial claims grounded in fresh tool results
- Conversations retain messages, tool names/arguments, cited record IDs, returned aggregates, model/prompt versions, and proposal outcomes

### 8.4 Correction Proposal flow

1. The assistant queries evidence through read-only tools.
2. `propose_correction` records the Transaction ID and expected revision, before/after values, reason, cited evidence, idempotency key, and model/prompt identity.
3. Chat renders the diff.
4. The user approves or rejects it.
5. Approval goes through the ordinary application interface, checks for staleness, appends the Correction, reruns validation, and updates live reports.
6. Rejection records the outcome without changing the Transaction.

The assistant cannot confirm its own proposal or silently alter financial data.

## 9. Security and privacy

- Entire MVP runs locally in k3s and is reachable only through loopback or port-forwarding.
- No login system is added while the loopback-only trust assumption holds.
- LAN/public exposure is prohibited until authentication, HTTPS, CSRF protection, and a fresh review are designed.
- PostgreSQL, vLLM, and MCP remain internal.
- Credentials live in Kubernetes Secrets created from ignored local configuration; they never enter Git, frontend bundles, prompts, or logs.
- PDF handling verifies file signatures, generates paths, enforces resource limits, and runs as non-root.
- Logs omit PDFs, raw descriptions, amounts, prompts, and secrets by default. They contain record IDs, stages, durations, error codes, versions, and redacted diagnostics.
- Sensitive debugging is explicit, temporary, and visibly enabled.
- Real Statements, extracted records, and the private gold corpus never enter Git history.

## 10. Archive, deletion, backup, and recovery

Archive hides a Statement from ordinary views while preserving evidence and history. Permanent deletion is a separate confirmed action that removes the PDF, Transactions, Corrections, Classification history, Review Findings, and Processing Attempts, then recalculates reports. User-approved Classification Rules remain, although deleted source provenance becomes unavailable. Historical chat citations to deleted records display as unavailable rather than resolving to unrelated data.

PostgreSQL and the Statement PDF PVC are one logical backup/restore unit. Backups are encrypted, stored at a user-configured path outside k3s local-path storage, retain seven daily and four weekly generations, and support an on-demand run. Restoration must be tested and reestablish database-to-file relationships. A second path on the same disk protects against mistakes, not disk failure.

## 11. Verification and acceptance

### 11.1 Private gold corpus

Use six representative private BPI PDFs. Manually verify every Transaction in those Statements. Include, across the corpus, ordinary expenses, MB WAY ambiguity, owned-account Transfers, outbound payment Transfers, Refunds, Fees, duplicates/overlap, malformed or unsupported inputs, and Corrections. The corpus is configured or mounted locally and remains outside Git.

### 11.2 Accuracy release gates

- 100% schema-valid extraction and Classification responses
- 100% exact report arithmetic
- No silently accepted booking date, value date, amount, currency, sign, balance, or row-count errors
- At least 95% Movement Kind accuracy
- At least 95% Payment Channel accuracy
- At least 90% Reporting Category accuracy
- 100% valid MCP tool names and argument schemas in the evaluation scenarios
- No unauthorized mutation
- Uncertain cases reliably routed to Needs Review

A safe abstention or Review Finding is preferable to plausible but trusted wrong data.

### 11.3 Runtime requirements

Mandatory:

- No OOM at supported file, context, sequence, and batch limits
- No indefinite hangs; bounded timeouts and durable retry/failure states
- No data loss across backend, worker, MCP, vLLM, or Pod restarts
- Responsive enough for personal interactive use

Advisory measurements, not release blockers:

- Upload accepted and queued around 2 seconds
- Ordinary filters and reports around 500 ms at 10,000 Transactions
- Idle-chat first token around 5 seconds
- Chat first token around 15 seconds when background work is queued
- Typical monthly Statement processed around 5 minutes

Record actual hardware results and tune only after correctness and stability are established.

### 11.4 Test layers

- Unit tests through deep module interfaces
- PostgreSQL integration and migration tests
- REST/OpenAPI and MCP contract tests
- Gold-corpus extraction and Classification evaluation
- Browser end-to-end tests for upload, review, Correction, rule, report, and assistant flows
- k3s smoke tests for migrations, probes, GPU inference, restart recovery, PVC persistence, and backup restoration

Normal CI runs formatting, linting, type checks, unit/integration tests, frontend tests/build, and protocol contracts without private financial data or a GPU. GPU evaluation runs locally against the private corpus.

## 12. Delivery increments

### Increment 1: Foundation

- Repository structure and modular-monolith skeleton
- Python/FastAPI and React/TypeScript foundations
- PostgreSQL, Alembic migrations, durable jobs
- k3s base manifests, secrets, PVCs, probes, and CI

### Increment 2: Statements

- Upload and PDF safety
- Bank Account resolution
- Statement/source-file persistence
- Processing lifecycle, attempts, progress streaming, retry, archive/delete
- Bank-layout extraction through `ParserRegistry` and deterministic reconciliation

Implementation checkpoint (2026-09-02): the single-file vertical is complete through safe upload,
content-hash deduplication, generated source-PVC paths, durable stage jobs, deterministic text
extraction, strict-schema Qwen3-8B-AWQ extraction, exact Decimal reconciliation, visible review
state, bounded retry/failure, REST status, and the React upload/status interface. It passed a
synthetic exact-hardware run from upload to `Ready` on the pinned private vLLM deployment.

Implementation checkpoint (2026-09-03): extracted Transactions are persisted as provisional
Original Values with linked Review Findings and source page/line evidence. The Transactions view
supports statement and booking-date filters, sorting, pagination, and expandable evidence. Parser
routing and extraction provenance are now explicit; a verified deterministic parser is required
for automatic Ready publication. User Corrections, Effective Values, Classification, and reports
remain pending.

Still pending in Increment 2: private-corpus coverage beyond the available BPI fixture, Bank Account
fingerprint resolution and confirmation, explicit Processing Attempt history and progress
streaming, multi-file drag-and-drop, scanned-PDF detection, archive, confirmed permanent deletion,
and private-corpus acceptance.

### Increment 3: Transactions

- Transaction search/filter/sort/pagination
- Original and Effective Values
- Append-only Corrections and reversion
- Classification, provenance, review queue, and Classification Rules

### Increment 4: Reports

- Exact Monthly Report calculations
- Descending month timeline
- Category, Counterparty, Transaction, and Payment Channel breakdowns
- Provisional warnings and non-EUR separation

### Increment 5: Financial Assistant

- Persistent conversations
- Loopback Streamable HTTP MCP sidecar
- Five allowlisted tools
- Cited answers, tool audit, Correction Proposals, and confirmation flow

Each increment must be usable and verified before expanding. n8n and Google Drive are not delivery increments.

## 13. ADR traceability

| Decision area | ADR |
|---|---|
| Application owns workflow; no n8n/Drive dependency | [ADR 0001](adr/0001-application-backend-owns-domain-workflow.md) |
| Independently retryable processing stages | [ADR 0002](adr/0002-stage-statement-processing.md) |
| Immutable Original Values and separate Corrections | [ADR 0003](adr/0003-preserve-original-values.md) |
| MCP only for the Financial Assistant | [ADR 0004](adr/0004-use-mcp-for-the-financial-assistant.md) |
| Shared vLLM endpoint and Qwen model policy | [ADR 0005](adr/0005-share-one-vllm-endpoint.md) |
| Python, PostgreSQL, and React | [ADR 0006](adr/0006-use-python-postgres-and-react.md) |
| PostgreSQL-backed durable work | [ADR 0007](adr/0007-use-postgres-for-durable-work.md) |
| Modular monolith and process adapters | [ADR 0008](adr/0008-build-a-modular-monolith.md) |
| Relational records and PVC source storage | [ADR 0009](adr/0009-use-relational-records-and-pvc-file-storage.md) |
| Append-only Correction and Classification history | [ADR 0010](adr/0010-append-only-financial-history.md) |
| Coordinated database/source-file backups | [ADR 0011](adr/0011-back-up-database-and-source-files-together.md) |
| Loopback Streamable HTTP for MCP | [ADR 0012](adr/0012-use-loopback-streamable-http-for-mcp.md) |
| Exact money and enforced reconciliation | [ADR 0013](adr/0013-use-exact-money-and-enforced-reconciliation.md) |
| Loopback-only MVP without authentication | [ADR 0014](adr/0014-keep-the-mvp-loopback-only.md) |
| Deterministic bank-layout parsers | [ADR 0015](adr/0015-use-deterministic-statement-parsers.md) |
| Bounded research as advisory Classification context | [ADR 0016](adr/0016-bounded-research-for-classification.md) |

## 14. Supporting research

- [Qwen and vLLM on a 12 GB laptop GPU](research/qwen-vllm-shared-endpoint.md)
- [MCP transport and deployment for k3s](research/mcp-transport-k3s.md)
- [Bounded research for Classification](adr/0016-bounded-research-for-classification.md)

## 15. Deferred decisions

These are explicitly outside the MVP rather than unresolved requirements:

- LAN access and authentication
- Additional banks and statement layouts
- OCR and encrypted PDFs
- Currency conversion
- Custom Reporting Categories
- Budgets and forecasting
- Native mobile clients
- External document sources, including Google Drive
- n8n integration
- MCP deployment outside the Web Pod

Reintroducing any deferred item requires a new design decision and, when the three ADR criteria are met, a new ADR.
