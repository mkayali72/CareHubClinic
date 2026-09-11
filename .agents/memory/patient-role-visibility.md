---
name: Patient role visibility
description: Durable access boundary for patient demographic and clinical fields.
---

Front-desk and billing staff may access patient records but must receive only
demographic, contact, and insurance data. Physician, nurse/MA, and clinic
administrator roles may receive and write emergency contact, allergy,
medication, and contraception fields.

**Why:** Direct API test requirements clarified that patient visibility must not
be inferred from the ability to open the patient workspace; clinical fields
need a stricter role boundary.

**How to apply:** Keep this distinction enforced in service-layer projections
and payload construction, then cover both direct API reads and crafted writes
when adding patient-related routes.