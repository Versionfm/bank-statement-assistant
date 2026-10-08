# Use exact money and enforced Statement reconciliation

Transaction amounts and balances will use exact decimal representations with their stated ISO currencies, never binary floating point, and Monthly Reports will aggregate only EUR in the MVP. Supported Statements must reconcile their opening balance, ordered signed movements, running balances when present, closing balance, row count, and debit or credit formatting before becoming Ready. This may send more imports to review, but it prevents plausible-looking model output from silently becoming trusted financial totals.
