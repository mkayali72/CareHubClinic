---
name: Phone input validation
description: The clinic's phone fields accept conventional formatting but reject non-numeric content.
---

Phone numbers should use telephone-oriented browser controls and server validation. Accept an optional international `+` plus spaces, parentheses, and hyphens, while requiring the underlying value to contain at least seven digits.

**Why:** Phone numbers are identifiers rather than arithmetic values; treating them as numeric database values can remove leading zeroes, while existing clinic data uses formatted international numbers.

**How to apply:** Reuse the shared phone validator for patient, emergency-contact, walk-in, and future phone fields at the service boundary as well as in HTML controls.