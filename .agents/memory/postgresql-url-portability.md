---
name: PostgreSQL URL portability
description: Why generic PostgreSQL connection URLs need normalization in this scaffold
---

The app should accept standard `postgresql://` and `postgres://` environment
values but normalize them to `postgresql+psycopg://` before SQLAlchemy creates
an engine.

**Why:** The Replit environment provided a generic PostgreSQL URL while the
portable app intentionally uses psycopg 3. SQLAlchemy otherwise selects the
legacy psycopg2 dialect and the app fails before startup.

**How to apply:** Preserve this normalization when changing connection
configuration or adding local/Docker database environments.