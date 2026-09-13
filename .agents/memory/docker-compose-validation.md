---
name: Docker Compose validation
description: A host-specific limitation encountered while validating container healthchecks.
---

Docker healthchecks can report OCI `setns` exec failures in the development
container even when the database process is running and reachable. Treat the
healthcheck result separately from service startup: inspect container logs and
verify the app's database-backed endpoint before changing a valid PostgreSQL
healthcheck.

**Why:** The portable Compose stack built cleanly, PostgreSQL reached readiness,
and the app passed migrations and HTTP checks, while this Docker daemon could
not execute the healthcheck process reliably.

**How to apply:** Keep a normal `pg_isready` healthcheck with a startup grace
period and retries for Docker Desktop users; document the local daemon
limitation rather than weakening dependency ordering.