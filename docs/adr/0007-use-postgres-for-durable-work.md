# Use PostgreSQL for durable background work

Statement processing jobs and stage progress will be stored in PostgreSQL and consumed by a dedicated worker so Pod or backend restarts do not lose work. The single-user, single-GPU MVP will not add Redis or an external broker: PostgreSQL already provides the required durability and claiming semantics, while one worker keeps GPU scheduling predictable. A separate broker can be introduced later only if measured concurrency or throughput requires it.
