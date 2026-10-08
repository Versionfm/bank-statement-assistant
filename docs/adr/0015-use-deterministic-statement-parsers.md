# Use deterministic statement parsers

Transaction extraction will use only registered deterministic parsers. An unsupported, ambiguous, or changed bank layout fails with an explicit unsupported-layout reason; it is never submitted to a language model as a parsing fallback.

This makes import completeness and financial reconciliation reproducible and audit-friendly. It also separates the extensibility seam from transaction semantics: each new bank or materially changed layout receives its own `BankLayoutId`, detector markers, parser adapter, and private fixture coverage before it is registered. Local models remain available for Classification, review, and Financial Assistant functions, but not for interpreting transaction rows.
