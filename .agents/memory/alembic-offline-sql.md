---
name: Alembic offline SQL generation
description: Why offline SQL rendering cannot run through the full migration chain.
---

The migration history contains a data-dependent revision that queries existing clinic rows during `upgrade()`. A full offline `alembic upgrade head --sql` run therefore fails when the offline bind returns no query results.

**Why:** The historical data backfill needs a connected database result, so offline SQL generation cannot execute that migration as written.

**How to apply:** Do not use full-chain offline SQL generation as the validation gate for new revisions. Check the migration head, compile relevant model DDL, and validate a new revision independently with Alembic operations or against a disposable connected database.