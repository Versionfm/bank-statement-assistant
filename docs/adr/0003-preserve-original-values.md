# Preserve original values and apply corrections separately

Values extracted from a Statement will remain immutable source evidence, while user changes will be stored as reversible Corrections that produce Effective Values for review and reporting. Model output, Classification Rules, and later reprocessing may propose new values but cannot overwrite Original Values or manual Corrections. This requires explicit provenance and audit history, but prevents model upgrades, retries, or user mistakes from silently rewriting financial evidence.
