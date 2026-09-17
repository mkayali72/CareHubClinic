---
name: Staff account management boundaries
description: Keep clinic-admin authorization in the staff-management service rather than the generic user factory.
---

The generic user factory is also used by non-administrative fixture and domain setup flows, so clinic-admin authorization belongs in the dedicated staff-account management operations. Those operations must still enforce same-clinic scope.

**Why:** Applying admin-only checks to the shared factory broke existing clinical setup that creates related staff records with a non-admin actor.

**How to apply:** When extending staff administration, use the dedicated management service for authorization, lifecycle, and audit behavior; preserve the low-level factory's existing callers.