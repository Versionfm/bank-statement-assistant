# Use relational records and PVC storage for source files

Authoritative financial records, provenance, processing history, conversations, and Correction Proposals will use explicit PostgreSQL tables and relationships; raw model responses may be retained only as audit payloads. Original Statement PDFs will live on a dedicated local PVC with generated paths, content hashes, and metadata in PostgreSQL rather than as database binaries or in a separate object store. This keeps financial queries constrained and auditable while avoiding another stateful storage system in the single-node MVP.
