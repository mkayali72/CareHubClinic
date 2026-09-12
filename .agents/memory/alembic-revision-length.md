---
name: Alembic revision length
description: The project database stores Alembic revision identifiers in a 32-character column.
---

Migration revision identifiers must be no longer than 32 characters.

**Why:** A descriptive revision name longer than this caused the migration DDL to run inside a transaction and then fail while updating `alembic_version`, so the migration could not reach head.

**How to apply:** Use a short numeric-prefixed revision ID and keep the human-readable migration purpose in the module docstring.