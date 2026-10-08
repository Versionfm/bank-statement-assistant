# Process Statements in independently retryable stages

Statement processing will separate deterministic PDF text extraction, verified bank-layout detection, registered deterministic parser extraction where a layout is supported, deterministic financial validation, local-LLM Classification, and whole-Statement review. Each completed stage will retain its result so a later failure can be inspected and retried without repeating successful earlier work. This costs more pipeline state than one model call, but it makes financial validation enforceable, failures understandable, and Classification retries independent of PDF extraction.

The worker depends only on the bank-neutral `StatementExtractor` interface. A `ParserRegistry` and `BankDetector` remain internal to the Statement Extraction module. A verified layout selects one registered parser with explicit parser identity and version. An unknown, ambiguous, unregistered, or drifted layout fails as unsupported; no language model is available in the parsing path.

Every extraction records detector version, detected bank and layout when available, routing evidence, parser identity and version, and extraction strategy. Validation remains centralized and parser-independent. MCP is not part of this critical path; its role remains the Financial Assistant adapter described by ADR 0004.
