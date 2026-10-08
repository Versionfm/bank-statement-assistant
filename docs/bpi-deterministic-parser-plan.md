# Deterministic BPI parser plan

Status: BPI Extracto Integrado v1 implemented on 2026-09-03.

## Verified BPI layout contract

The available three-page BPI statement is a text-based `EXTRACTO INTEGRADO` current-account statement. Its verified characteristics are:

- a statement period in `Período De DD/MM/YYYY a DD/MM/YYYY` form;
- `DEPÓSITOS À ORDEM` movement pages with Portuguese decimal amounts;
- an opening `SALDO ANTERIOR CONTABILISTICO` and closing `SALDO ACTUAL CONTABILISTICO`;
- movement rows with booking date, value date, description, signed amount, and running balance;
- blank booking-date cells that inherit the prior printed booking date, including across page breaks.

The parser preserves pypdf layout extraction, validates every required marker, derives years only within the printed period, uses `Decimal` for money, retains line-level evidence, and reconciles opening balance plus signed rows to the closing balance. It ignores the separate scheduled-movements section.

## Implementation plan

1. Keep `BankDetector`, `BankLayoutId`, `ParserRegistry`, and `StatementExtractor` bank-neutral.
2. Register `bpi.extracto-integrado.current-account.v1` only when all four BPI markers uniquely match.
3. Parse its fixed movement table with the BPI adapter, then run the shared evidence and reconciliation validator.
4. Reject unknown, ambiguous, unregistered, and drifted layouts. There is no LLM parsing fallback.
5. Expand the private BPI corpus before promotion: cover month/year boundaries, multiple accounts, empty statements, fees, refunds, and any alternative BPI export layouts.

## Adding another bank

Create a new layout ID and adapter; do not add conditionals to the BPI parser. Supply private representative PDFs and tests for detection, all transaction rows, source evidence, balance reconciliation, duplicate/overlap behavior, and failure modes. Register the new layout only after every fixture passes. Shared Transaction, validation, reporting, and correction semantics remain unchanged.
