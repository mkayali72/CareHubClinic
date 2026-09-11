# Automated Test Results

This file is the append-only, authoritative history of every automated test
run throughout the build. Starting with the next test prompt, append a dated
section for each test batch. Name the build prompt it covers, then record one
line per case using this exact format:

```text
Test <number>: <PASS|FAIL|MANUAL> — <what was tested>
```

For every `FAIL` or `MANUAL` entry, add an explanation underneath describing
what was expected, what happened, and, once fixed, what the fix was. Never
overwrite previous entries.

## 2026-09-11 — Foundational database schema and session authentication

Test 1: PASS — Imported the FastAPI app and confirmed SQLAlchemy metadata contains clinics, users, and audit_logs.
Test 2: PASS — Applied the initial Alembic migration and confirmed 0001_foundational_schema is at the database head.
Test 3: PASS — Created one development user for each of the five allowed roles and verified Argon2 password authentication.
Test 4: PASS — Soft-deleted a user as clinic_admin and confirmed default ORM queries exclude it while include_deleted=True returns it.
Test 5: PASS — Confirmed non-admin soft-delete attempts raise PermissionError and admin restoration creates the restore path.
Test 6: PASS — Verified login, authenticated welcome page, logout, and anonymous redirect behavior over HTTP.
Test 7: PASS — Confirmed /health returns HTTP 200 with a successful PostgreSQL SELECT 1 probe after restart.
Test 8: PASS — Recompiled the app and confirmed the login page and database health endpoint remain healthy after the soft-deleted-session lookup hardening.

## Prompt 3.T — Foundation

Test 1: PASS — Verified users with all five allowed roles can log in through FastAPI TestClient.
Test 2: PASS — Verified logged-out access to /welcome redirects to /login and non-admin users receive 403 from the clinic_admin-only dependency while regular authenticated access remains allowed.
Test 8: PASS — Verified a session configured with a one-second max age is rejected after expiry.
Test 9: PASS — Verified logout increments the session version so replaying the previous cookie is rejected.
Test 10: PASS — Verified weak passwords are rejected and five failed login attempts lock the account.
Test 12: PASS — Verified changing a user's role takes effect immediately for role authorization.
Test 13: PASS — Verified a newly created user with no role is denied elevated access.
Test 14: PASS — Verified soft deletion sets deleted_at and deleted_by_user_id while retaining the database row.
Test 15: PASS — Verified soft-deleted users are excluded from default ORM queries.
Test 16: PASS — Verified soft deletion creates an AuditLog entry with actor and timestamp.
Test 19: PASS — Searched application code and found no true DELETE statement or session.delete/db.delete path for soft-deletable models.
Test 20: PASS — Verified create, update, and delete actions each create the expected AuditLog action.
Test 21: PASS — Verified AuditLog has no mutation route and the immutable mutation guard rejects every role.