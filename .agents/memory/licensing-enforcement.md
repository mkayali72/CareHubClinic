---
name: Licensing enforcement
description: Local license-state enforcement and the isolated future remote check-in seam.
---

License validity is evaluated from the clinic's local License row on every
authenticated request; login-time checks or cached session state are not
sufficient. Reads remain available during grace/expired states, while writes
are blocked server-side and the clinic-admin renewal route remains exempt so
an expired clinic can recover.

**Why:** Subscription state can change while a browser session is still open,
and clinical notes must not be silently discarded when saving becomes
unavailable.

**How to apply:** Keep the remote integration isolated behind
`perform_license_check_in`; preserve the request-level guard, HTMX no-swap
response, shared banner, and browser draft preservation when changing the
license provider.