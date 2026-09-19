---
name: Sample data lifecycle
description: How first-run demonstration records are identified and removed safely.
---

First-run sample records are tracked by stable IDs in the clinic settings JSON rather than by mutable display names. Sample removal must use the existing audit-preserving soft-delete policy.

**Why:** Display names and usernames can be edited, and the application explicitly forbids hard deletes for clinical and access records.

**How to apply:** Keep initialization idempotent through the clinic registry, restrict management to clinic administrators, and do not add physical row deletion paths for sample data.