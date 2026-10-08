# Application backend owns the domain workflow

The predecessor automation uses n8n as its central orchestrator, but the web application needs one stable owner for Statement processing, persistence, Corrections, and reporting. The application backend will own that workflow and its state; n8n and Google Drive are outside the current scope and will not be dependencies of any MVP path. This keeps the product interface and domain model independent of predecessor workflow internals while leaving any future external-source adapter as a separate decision.
