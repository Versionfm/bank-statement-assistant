# Back up financial records and source files together

PostgreSQL data and the Statement PDF PVC will be treated as one logical backup and restore unit because either half alone is incomplete: database-only recovery loses source evidence, while file-only recovery loses provenance and Corrections. Backups will be encrypted, retain multiple generations, and require a tested restoration procedure that reestablishes the relationships between records and generated file paths.
