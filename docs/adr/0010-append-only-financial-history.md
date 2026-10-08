# Keep Corrections and Classification results append-only

Corrections and model, rule, or fallback Classification results will be appended with their provenance and versions rather than overwriting earlier records. Effective Values and the effective Classification will be derived by precedence from that history, and reverting a Correction will add another event. This increases query and projection work but ensures model upgrades, retries, and user actions remain explainable and recoverable.
