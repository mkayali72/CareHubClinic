---
name: PostgreSQL enum migrations
description: Avoid duplicate PostgreSQL enum creation when Alembic creates an enum before a table.
---

When an Alembic migration explicitly creates a PostgreSQL enum with
`checkfirst=True` and then uses that enum in a table, set the enum's
`create_type=False` so SQLAlchemy does not try to create the same type again
during table creation.

**Why:** PostgreSQL raised a duplicate-type error when the explicit enum
creation and SQLAlchemy's table DDL both attempted to create the named type.

**How to apply:** Keep explicit enum creation and drop logic in the migration,
but disable implicit creation on the enum object used by `op.create_table`.