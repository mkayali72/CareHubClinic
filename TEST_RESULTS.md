# Automated Test Results

## Prompt 15.T — Export-Readiness Verification

Test 113: PASS — Re-ran the complete automated suite with `python -m pytest -q`; all 161 tests passed with zero failures. The run produced the same three existing dependency deprecation warnings.

Test 114: PASS — Applied the complete Alembic chain through `0010` against a fresh PostgreSQL database, populated it with clinic, user, patient, appointment type, appointment, and backfilled license rows, applied `0011_request_idempotency`, verified the new column and constraint, downgraded the latest migration, confirmed all populated rows remained and the latest objects were removed, then upgraded again and confirmed the rows and final revision were restored.

Test 115: MANUAL — `docker compose build` passed and produced the app image. In this Replit Docker daemon, normal `docker compose up` could not pass the PostgreSQL healthcheck because healthcheck exec returned an OCI `setns` error even though PostgreSQL logs showed it ready to accept connections. The app/database direct-start sanity check had already returned healthy `/health` and HTTP 200 from `/login`; repeat the normal dependency-ordered `docker compose up --build` check on Docker Desktop.

Test 116: MANUAL — Deployment metadata reports no published environment in this workspace, so rollback/data-retention verification cannot be executed here. The intended backup-first, application-image rollback, schema-compatibility, data-count verification, and post-rollback smoke-test procedure is documented in `TESTING.md` under “Prompt 15.T — Export-readiness rollback procedure.”

README Docker Desktop instructions: PASS — Confirmed the “Run Locally with Docker Desktop” section covers cloning, `.env` creation, secret replacement, the `db` hostname, build/start, health verification, login, shutdown/volume behavior, host-test setup, and startup-log troubleshooting without requiring Replit context.

## Final export-readiness rollup — Prompt 14.T

- **Automated cases executed:** 161 total — **161 PASS, 0 FAIL**
  - Prompt 3.T–13.T cross-module regression: 159 PASS
  - Prompt 14.T end-to-end workflows: 2 PASS
- **Manual/deployment checks still open:** 7 — Tests 34, 35, 43, 44, 97, 98,
  99. These are infrastructure, organizational data-handling, or real-device
  checks and are not application-test failures.

| Module / section | Automated PASS | FAIL | MANUAL |
| --- | ---: | ---: | ---: |
| Prompt 3.T — Foundation | 17 | 0 | 0 |
| Prompt 4.T — Patient demographics | 24 | 0 | 0 |
| Prompt 5.T — Scheduling | 12 | 0 | 0 |
| Prompt 6.T — Clinical documentation | 29 | 0 | 0 |
| Prompt 7.T — Lab orders | 15 | 0 | 0 |
| Prompt 8.T — Prescriptions | 11 | 0 | 0 |
| Prompt 9.T — Billing | 11 | 0 | 0 |
| Prompt 10.T — Reporting | 10 | 0 | 0 |
| Prompt 11.T — Licensing | 14 | 0 | 0 |
| Prompt 12.T — Security hardening | 14 | 0 | 4 |
| Prompt 13.T — Mobile/responsive | 2 | 0 | 3 |
| Prompt 14.T — Cross-module end-to-end | 2 | 0 | 0 |
| **Total** | **161** | **0** | **7** |

**MANUAL items requiring completion before export:** Test 34 — verify database
encryption at rest and encrypted backups with the chosen hosting provider; Test
35 — verify HTTPS redirect/rejection at the production TLS boundary; Tests 43
and 44 — verify BAA/vendor coverage and that non-production environments
contain no real PHI; Tests 97–99 — exercise visit notes, clinical slide-over
modals, and touch navigation on real iOS Safari and Android Chrome devices.

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

## Patient Demographics

Test 1: PASS — Verified all five allowed staff roles can access the clinic-scoped patient list.
Test 2: PASS — Verified billing_clerk API projections include name, contact, insurance, and date of birth while omitting emergency contact and clinical fields.
Test 3: PASS — Verified htmx create and edit submissions persist structured allergy and medication objects.
Test 4: PASS — Verified billing_clerk cannot write sensitive fields even when those fields are posted directly.
Test 5: PASS — Verified the Billing tab appears only when Clinic.billing_module_enabled is true and the future-module placeholder renders.
Test 6: PASS — Verified patient API ordering is newest-first and patient data is clinic-scoped.
Test 7: PASS — Verified only clinic_admin can soft-delete a patient, the delete is audited, the row is retained, and active list/API results exclude it.

## 2026-09-11 — Prompt 4.T — Patient Demographics

Test 3: PASS — Verified front_desk direct patient API responses include permitted demographics but exclude emergency contact, allergies, current medications, and contraception.
Test 5: PASS — Verified billing_clerk direct patient API responses include name, date of birth, contact, and insurance while excluding all clinical fields.
Test 6: PASS — Verified physician, nurse_ma, front_desk, and clinic_admin can view any active patient in their clinic without per-doctor restrictions.
Test 7: PASS — Exercised every patient list, detail, form, create, update, and delete route directly for every staff role; only clinic_admin deletion was accepted.
Test 17: PASS — Verified soft-deleted patients immediately disappear from HTML and API list/detail views for every role, then restored the record through the existing clinic_admin-only restore service with all data intact.
Test 18: PASS — Verified patient deletion retains the database row, clinic association, and create/delete audit history without orphaned linked state.
Test 58: PASS — Verified omitting each required create field, name and date_of_birth, returns HTTP 422 with a field-specific validation response and creates no incomplete record.
Test 59: PASS — Verified the current documented behavior: similar patients are accepted because duplicate detection is not implemented; no accidental error or silent data loss occurs.
Test 60: PASS — Verified multiple allergy and medication entries plus contraception save and reload correctly through the direct API.

Prompt 3.T Test 1: PASS — Full regression run retained login coverage for all five roles.
Prompt 3.T Test 2: PASS — Full regression run retained authentication and clinic-admin authorization coverage.
Prompt 3.T Test 8: PASS — Full regression run retained session expiration coverage.
Prompt 3.T Test 9: PASS — Full regression run retained logout session-version invalidation coverage.
Prompt 3.T Test 10: PASS — Full regression run retained password complexity and failed-login lockout coverage.
Prompt 3.T Test 12: PASS — Full regression run retained immediate role-change authorization coverage.
Prompt 3.T Test 13: PASS — Full regression run retained safe unassigned-role denial coverage.
Prompt 3.T Test 14: PASS — Full regression run retained soft-delete field retention coverage.
Prompt 3.T Test 15: PASS — Full regression run retained default soft-delete filtering coverage.
Prompt 3.T Test 16: PASS — Full regression run retained soft-delete audit coverage.
Prompt 3.T Test 19: PASS — Full regression run retained no-hard-delete implementation coverage.
Prompt 3.T Test 20: PASS — Full regression run retained create/update/delete audit coverage.
Prompt 3.T Test 21: PASS — Full regression run retained immutable audit-log protection coverage.
Full regression suite: PASS — `python -m pytest -q` completed with 41 passed and 3 existing dependency deprecation warnings.

## 2026-09-12 — Scheduling

Test 1: PASS — Verified AppointmentStatus preserves the exact required order from scheduled through no_show.
Test 2: PASS — Verified physician, nurse_ma, front_desk, and clinic_admin can access scheduling and queue views while billing_clerk receives 403.
Test 3: PASS — Verified front_desk can create an existing-patient appointment with the appointment type's default duration and an audit record.
Test 4: PASS — Verified physician and nurse_ma cannot create appointments through the direct POST route.
Test 5: PASS — Verified a walk-in creates a Patient and checked_in Appointment together with the submitted contact information.
Test 6: PASS — Verified queue actions advance one status at a time through done and audit each transition; terminal appointments cannot advance.
Test 7: PASS — Verified clinic_admin can create and edit appointment types while front_desk cannot manage them.
Test 8: PASS — Verified physician welcome pages show the signed-in physician's own today's queue and omit another physician's appointments.
Test 9: PASS — Verified patient, physician, and appointment-type references from another clinic are rejected with no appointment created.
Migration: PASS — Applied `0004_scheduling` and confirmed it is the Alembic database head.
Workflow: PASS — Restarted the OB-GYN Clinic App workflow; local `/health` returned `{"status":"ok","database":"ok"}` and `/login` returned HTTP 200.

## 2026-09-12 — Prompt 6.T — Clinical Visit Documentation

Test 63: PASS — Created prenatal, gyn_annual, postpartum, and problem_focused visits and confirmed shared vitals persist while only the correct type-specific structured section is populated.
Test 64: PASS — Verified gestational age at early pregnancy, near-term dating, and after a corrected EDD is applied; corrected dating changes the calculated gestational age while the original EDD remains stored.
Test 65: PASS — Saved and reloaded ultrasound EFW, AFI, placenta location, presentation, and biometry in the prenatal structured section.
Test 66: PASS — Created prenatal visits out of entry order and confirmed trend data is ordered by explicit visit date and includes every visit.
Test 67: PASS — Confirmed glucose, Rhogam, and Group B Strep reminders trigger at the appropriate gestational age, do not appear too early, and are suppressed for gyn_annual visits.
Test 68: PASS — Dismissed a screening reminder and confirmed only the audited UI dismissal is stored; no screening completion state or clinical visit is created.
Test 69: PASS — Created two pregnancy episodes for one patient and confirmed each episode's visit history and trend contain only its own prenatal visits.
Test 70: PASS — Created a delivery outcome and confirmed it remains linked to the episode and is rendered alongside that episode's clinical visit context.
Test 71: PASS — Confirmed an invalid ICD-10 identifier is rejected while a valid structured diagnosis saves and renders on the visit.
Test 72: PASS — Created a phrase as one physician, inserted it as another physician in the same clinic, edited the template, and confirmed the saved note retains the original text snapshot.
Test 73: PASS — Attempted a direct HTTP update after the lock window elapsed and confirmed the API rejected the edit while preserving the original note.
Test 74: PASS — Added an amendment to a locked visit and confirmed the original content remains unchanged while the amendment shows its content, author, and timestamp.
Test 75: PASS — Created IUD insertion, IUD removal, colposcopy, and endometrial biopsy procedure records and confirmed each is linked to the correct visit.
Test 76: PASS — Saved a partial problem-focused note with only available fields and confirmed the entered values persisted without requiring unrelated fields.
Migration: PASS — Added and applied `0006_visit_dates` after `0005_clinical_documentation`; Alembic reports the new migration at head.
Prompt 3.T regression: PASS — Re-ran foundation tests as part of the combined regression command; all foundation cases passed.
Prompt 4.T regression: PASS — Re-ran patient tests as part of the combined regression command; all patient cases passed.
Prompt 5.T regression: PASS — Re-ran scheduling tests as part of the combined regression command; all scheduling cases passed.
Clinical suite: PASS — `python -m pytest -q tests/test_clinical.py` completed with 29 passed and 2 existing dependency deprecation warnings.
Combined regression: PASS — `python -m pytest -q tests/test_foundation.py tests/test_patients.py tests/test_scheduling.py tests/test_clinical.py` completed with 82 passed and 3 existing dependency deprecation warnings.

## 2026-09-12 — Lab Orders

Test 1: PASS — Seeded the clinic-editable starter catalog, restricted catalog changes to clinic_admin, and verified deactivation removes a test from ordering choices without deleting it.
Test 2: PASS — Created a named order set, ordered its multiple tests against one visit and patient, and confirmed each order starts as `ordered` and appears in Pending Labs.
Test 3: PASS — Entered a manual result, confirmed the order becomes `resulted` and leaves the outstanding queue, rejected nurse/M A sign-off, and confirmed physician review changes the order to `reviewed` with reviewer and timestamp.
Test 4: PASS — Validated a private PDF upload, generated a server-side filename, enforced private filesystem permissions, and served it only through the authorized patient-scoped clinical route.
Test 5: PASS — Confirmed front desk access to a stored lab file is rejected.
Test 6: PASS — Edited order-set membership as clinic_admin and confirmed the updated bundle persists.
Test 7: PASS — Confirmed the clinic-admin lab catalog route is available to clinic_admin and denied to physicians.
Migration: PASS — Applied `0007_lab_orders`; Alembic reports `0007_lab_orders (head)` and the migration seeds the starter list for existing clinics.
Full regression suite: PASS — `python -m pytest -q` completed with 89 passed and 3 existing dependency deprecation warnings.
Full regression suite: PASS — `python -m pytest -q` completed with 50 passed and 3 existing dependency deprecation warnings.

## 2026-09-12 — Prompt 7.T — Lab Orders

Test 39: PASS — Posted disallowed and oversized files directly to the LabResult endpoint and confirmed both were rejected server-side; valid PDF and JPG uploads succeeded, were retrievable by clinical roles for the clinic, and were denied to front_desk.
Test 40: PASS — Sent SQL-injection and XSS payloads through test name/description, order-set name/description, and manual result fields; parameterized queries treated SQL as data and Jinja escaped rendered payloads rather than emitting executable markup.
Test 77: PASS — Ordered one LabTestDefinition and a complete “New OB Panel” from the same visit; confirmed the single order and every bundle order were linked to that visit and patient with the correct order-set references.
Test 78: PASS — Simulated opening and submitting the HTMX slide-over while a note was in progress; confirmed the response was a scoped lab fragment, excluded note fields, returned no navigation/reset response, and preserved the visit’s lab context.
Test 79: PASS — Stored and reloaded manual-only, file-only, and combined manual-plus-file results; confirmed values, file metadata, and rendered retrieval links were retained.
Test 80: PASS — Re-fetched an uploaded result after a delay and a database re-query boundary; response bytes remained identical to the original file.
Test 81: PASS — Confirmed an unreviewed result has null reviewer metadata and `resulted` status, while physician sign-off sets `reviewed_by`, `reviewed_at`, and `reviewed` status.
Test 82: PASS — Confirmed Pending Labs initially returned only orders without results and removed an order immediately after result creation on the next request without cache-busting.
Prompt 3.T regression: PASS — Re-ran the complete foundation suite as part of the combined regression command; all 3.T cases passed.
Prompt 4.T regression: PASS — Re-ran the complete patient demographics suite as part of the combined regression command; all 4.T cases passed.
Prompt 5.T regression: PASS — Re-ran the complete scheduling suite as part of the combined regression command; all 5.T cases passed.
Prompt 6.T regression: PASS — Re-ran the complete clinical visit documentation suite as part of the combined regression command; all 6.T cases passed.
Combined Prompt 3.T–6.T regression: PASS — `python -m pytest -q tests/test_foundation.py tests/test_patients.py tests/test_scheduling.py tests/test_clinical.py` completed with 82 passed and 3 existing dependency deprecation warnings.
Prompt 7.T suite: PASS — `python -m pytest -q tests/test_labs.py` completed with 15 passed and 2 existing dependency deprecation warnings.

## 2026-09-12 — Prompt 5.T — Scheduling

Test 50: PASS — For every appointment type, created an appointment, edited its scheduled time and duration through the appointment endpoint, then cancelled it; each record retained its identity, type, edited values, and final `cancelled` status.
Test 51: PASS — Created two overlapping appointments for the same physician and confirmed both were accepted; this explicitly matches the current behavior because the schema has no room field or overlap-blocking rule.
Test 52: PASS — As `front_desk`, created a new walk-in patient and checked-in appointment through one request; confirmed the Patient, Appointment, contact data, today's date, and `checked_in` status persisted together.
Test 53: PASS — Advanced `checked_in` → `in_room` → `with_doctor` → `done` through the intended queue endpoint and confirmed a second authenticated role saw each persisted status after re-querying the queue.
Prompt 3.T regression: PASS — Re-ran `tests/test_foundation.py` and confirmed 41 tests passed with 3 existing dependency deprecation warnings.
Prompt 4.T regression: PASS — Re-ran `tests/test_patients.py` as part of the full patient regression group and confirmed 41 combined foundation/patient tests passed with 3 existing dependency deprecation warnings.
Full regression suite: PASS — `python -m pytest -q` completed with 53 passed and 3 existing dependency deprecation warnings.

## 2026-09-12 — Visit Documentation

Test 1: PASS — Verified only physician, nurse_ma, and clinic_admin can open the clinical workspace; front_desk and billing_clerk receive 403.
Test 2: PASS — Verified LMP dating calculates EDD as 280 days and corrected EDD drives gestational-age context without replacing the original value.
Test 3: PASS — Verified prenatal and gyn annual templates persist their type-specific structured JSON sections.
Test 4: PASS — Verified active ICD-10 lookup rows can be linked to a visit, unavailable IDs are rejected, and visit creation is audited.
Test 5: PASS — Verified supported procedure records persist and delivery outcomes move an episode to delivered with structured outcome fields.
Test 6: PASS — Verified the 48-hour lock window rejects direct edits and locked visits accept amendment-only changes.
Test 7: PASS — Verified phrase insertion stores a text snapshot that remains unchanged after the source template is edited.
Test 8: PASS — Verified gestational-age screening reminders calculate, dismiss, and remain separate from screening completion state.
Test 9: PASS — Verified the browser save flow redirects to the saved visit and renders the schedule-follow-up, mark-done, and skip next-action prompt.
Migration: PASS — Applied `0005_clinical_documentation` and confirmed it is the Alembic database head.
Clinical suite: PASS — `python -m pytest -q tests/test_clinical.py` completed with 9 passed and 2 existing dependency deprecation warnings.
Full regression suite: PASS — `python -m pytest -q` completed with 62 passed and 3 existing dependency deprecation warnings.
Workflow: PASS — Restarted the OB-GYN Clinic App workflow; local `/health` returned `{"status":"ok","database":"ok"}` and `/login` returned HTTP 200.

## 2026-09-12 — Prompt 8.T — Prescriptions

Test 83: PASS — Submitted a prescription through the authenticated inline visit slide-over POST and confirmed the persisted Prescription references the selected Visit, Patient, and MedicationDefinition.
Test 84: PASS — Confirmed an unsafe medication raises a pregnancy warning for a patient with an active PregnancyEpisode, then explicitly confirmed the same medication produces no pregnancy warning and can be prescribed for a patient without an active pregnancy.
Test 85: PASS — Confirmed a medication matching the patient's recorded penicillin allergy raises an allergy warning and cannot be confirmed without acknowledgment, while a non-conflicting vitamin-category medication produces no allergy warning and can be prescribed.
Test 86: PASS — Rendered the print prescription view and asserted the actual HTML contains clinic name and branding reference, patient name, medication, dosage, frequency, duration, and prescriber identification.
Test 87: PASS — Confirmed the Patient Summary immediately displays a newly added prescription, then removes it from the active current-medications projection after the intended soft-discontinuation while retaining the database record and deletion timestamp.
Prompt 3.T regression: PASS — `python -m pytest -q tests/test_foundation.py` completed with 17 passed and 3 existing dependency deprecation warnings.
Prompt 4.T regression: PASS — `python -m pytest -q tests/test_patients.py` completed with 24 passed and 2 existing dependency deprecation warnings.
Prompt 5.T regression: PASS — `python -m pytest -q tests/test_scheduling.py` completed with 12 passed and 2 existing dependency deprecation warnings.
Prompt 6.T regression: PASS — `python -m pytest -q tests/test_clinical.py` completed with 29 passed and 2 existing dependency deprecation warnings.
Prompt 7.T regression: PASS — `python -m pytest -q tests/test_labs.py` completed with 15 passed and 2 existing dependency deprecation warnings.
Combined Prompt 3.T–7.T plus Prompt 8.T regression: PASS — `python -m pytest -q tests/test_foundation.py tests/test_patients.py tests/test_scheduling.py tests/test_clinical.py tests/test_labs.py tests/test_prescriptions.py` completed with 108 passed and 3 existing dependency deprecation warnings.

## Prompt 9.T — Billing Module Toggle

Test 45: PASS — With Billing disabled, every operational Billing route returned HTTP 404 with the disabled response, while the Billing sidebar link and patient-chart Billing tab were absent.
Test 46: PASS — With Billing disabled, no Reporting or financial-report surface was exposed; the current application has no Reporting section or available report list.
Test 47: PASS — Toggling `billing_module_enabled` on took effect immediately without restart, and existing patient and visit records remained unchanged.
Test 48: PASS — Invoice and charge history remained in the database after Billing was toggled off and became available again unchanged after re-enabling.
Test 49: PASS — A `billing_clerk` received a graceful “Billing is not available” HTTP 404 response from disabled Billing screens instead of a blank page or server error.
Test 88: PASS — With Billing enabled, a visit-linked charge used the selected clinic fee schedule amount and retained the correct fee reference.
Test 89: PASS — Marking an invoice paid persisted the state and displayed `paid` in the Billing ledger.
Test 90: PASS — The printed invoice contained clinic branding, invoice number, patient/visit context, fee itemization, amount, and payment status.
Test 91: PASS — Editing a fee schedule item after invoice creation changed future pricing without changing the existing invoice or charge amount.
Prompt 3.T–8.T regression: PASS — `python -m pytest -q tests/test_foundation.py tests/test_patients.py tests/test_scheduling.py tests/test_clinical.py tests/test_labs.py tests/test_prescriptions.py` completed with 108 passed and 3 existing dependency deprecation warnings.
Prompt 9.T Billing suite: PASS — `python -m pytest -q tests/test_billing.py` completed with 11 passed and 2 existing dependency deprecation warnings.
Migration: PASS — Applied `0009_billing`; Alembic reports `0009_billing (head)`.
Compilation and diff checks: PASS — `python -m compileall -q app alembic tests` and `git diff --check` completed without errors.
Full regression suite: PASS — `python -m pytest -q` completed with 119 passed and 3 existing dependency deprecation warnings.

## 2026-09-12 — Reporting

Reporting query, RBAC, date-boundary, soft-delete, clinical calculation, and
export route tests: PASS — `python -m pytest -q tests/test_reporting.py`
completed with 5 passed and 2 existing dependency deprecation warnings.
Full regression suite: PASS — `python -m pytest -q` completed with 124 passed
and 3 existing dependency deprecation warnings.
Compilation and diff checks: PASS — `python -m compileall -q app tests alembic`
and `git diff --check` completed without errors.

## Prompt 11.T — Licensing Enforcement

QA plan reference: `04-qa-test-plan.md` was not present in the workspace; the
requested Test 26–33 cases were implemented against the current Licensing
contract.

Test 26: PASS — With a valid, non-expired License, exercised representative
HTTP writes and reads across Patients, Scheduling, Visits, Labs,
Prescriptions, and enabled Billing using the appropriate clinic roles.
Test 27: PASS — With expiration in an active grace period, reads across all
six modules remained available while representative patient, scheduling,
visit, lab, prescription, and billing writes returned HTTP 423 read-only
responses.
Test 28: PASS — Verified the exact grace boundary evaluates as grace at the
boundary and expired immediately after it; writes succeed on the active side
before expiration and are rejected both inside read-only grace and past grace.
This follows the existing product rule that grace is read-only.
Test 29: PASS — Renewed a clinic from an already authenticated read-only
session and confirmed writes resumed immediately without an app restart.
Test 30: PASS — Confirmed the visit workspace includes localStorage draft
capture/restoration, blocked a transitioned visit save with `HX-Reswap: none`,
and confirmed the draft content was not persisted as a partial visit.
Test 31: PASS — Parsed the clinic-admin license page and confirmed displayed
days remaining and expiration match the database state before and immediately
after renewal.
Test 32: PASS — Sent active-license client headers while the server-side
License was expired past grace; the server rejected the write with HTTP 423.
Test 33: PASS — Added a physician beyond the current clinic user set and
confirmed creation succeeds because no licensed physician-count restriction
has been implemented; License status remained active.
Prompt 3.T–10.T full regression: PASS — `python -m pytest -q` completed with
143 passed and 3 existing dependency deprecation warnings.
Licensing suite: PASS — `python -m pytest -q tests/test_licensing.py`
completed with 14 passed and 2 existing dependency deprecation warnings.
Compilation and diff checks: PASS — `python -m compileall -q app tests alembic`
and `git diff --check` completed without errors.

## 2026-09-12 — Licensing and subscription enforcement

Focused Licensing suite: PASS — `python -m pytest -q tests/test_licensing.py`
completed with 6 passed and 2 existing dependency deprecation warnings.
Full regression suite: PASS — `python -m pytest -q` completed with 135 passed
and 3 existing dependency deprecation warnings.
Migration: PASS — Applied `0010_licensing`; Alembic reports
`0010_licensing (head)`.
Compilation and diff checks: PASS — `python -m compileall -q app tests alembic`
and `git diff --check` completed without errors.
Coverage: PASS — License status evaluation, grace and expiry boundaries,
server-side stale-session write blocking, HTMX no-swap behavior, admin renewal
recovery, scheduler check-ins, read-only banners, notification-bell access,
and visit draft preservation are covered in `tests/test_licensing.py`.
Migration: PASS — Alembic reports `0009_billing (head)`; Reporting requires no
schema migration.
Workflow: PASS — Restarted the OB-GYN Clinic App workflow; local `/health`
returned `{"status":"ok","database":"ok"}`, `/login` returned HTTP 200, and
anonymous `/reports` returned HTTP 303 to authentication.

## Prompt 10.T — Reporting

QA plan reference: `04-qa-test-plan.md` was not present in the workspace; the
requested Test 92–96 cases were implemented against the current Reporting
contract.

Test 92: PASS — Seeded exactly 3 appointments (2 no-shows), 1 screening visit,
1 invoice, 1 delivery outcome, and 1 active pregnancy; asserted exact schedule,
revenue, no-show, screening, pregnancy, and delivery report values.
Test 93: PASS — Seeded appointments at start-of-day and end-of-day boundaries
plus one record immediately before and after; asserted the inclusive
`start_date <= value <= end_date` behavior and the half-open appointment
datetime window.
Test 94: PASS — Generated PDF and Excel exports, parsed Excel with openpyxl and
PDF text with pypdf, and compared extracted values against the report rows.
Test 95: PASS — A `front_desk` user received HTTP 403 for the direct revenue
report route and its Excel export route.
Test 96: PASS — Soft-deleted an appointment that initially counted and asserted
the report count and detail rows excluded it while the database record remained.

Prompt 3.T–9.T full regression: PASS — `python -m pytest -q
tests/test_foundation.py tests/test_patients.py tests/test_scheduling.py
tests/test_clinical.py tests/test_labs.py tests/test_prescriptions.py
tests/test_billing.py tests/test_reporting.py` completed with 129 passed and 3
existing dependency deprecation warnings.
Compilation and diff checks: PASS — `python -m compileall -q app tests alembic`
and `git diff --check` completed without errors.

## Prompt 12.T — Security Hardening

QA plan reference: `04-qa-test-plan.md` was not present in the workspace; the
requested Test 34–44 cases were implemented against the current application
security contract. Tests 34, 35, 43, and 44 are explicitly deferred to
deployment or organizational infrastructure/process verification.

Test 34: MANUAL — Database encryption at rest and encrypted backups require the selected hosting provider's infrastructure configuration; application-level automated tests cannot verify disk or managed-database encryption.
Test 35: MANUAL — The local app intentionally serves HTTP for development. Automated coverage confirms production session cookies are Secure, HttpOnly, and SameSite=Lax; an external TLS terminator must be tested for HTTP-to-HTTPS redirect at deployment.
Test 36: PASS — Triggered unexpected 500, missing-CSRF, and authentication error conditions and confirmed passwords, session tokens, and PHI-like values were absent from responses and captured logs.
Test 37: PASS — Rendered the built route set with PHI sentinel data and confirmed generated URL paths, query strings, hrefs, and form actions contained no patient names or clinical details.
Test 38: PASS — Forced a production-configured 500 and confirmed the response contained no exception message, traceback, application path, or site-packages path.
Test 39: PASS — Re-tested allowed PDF validation, rejected extension/type, invalid signature, and oversized upload cases.
Test 40: PASS — Exercised SQL/XSS payloads across patient structured text, scheduling, clinical notes, lab catalog/order sets, prescriptions, and billing text; persisted values remained data and rendered output was escaped.
Test 41: PASS — Submitted a state-changing request without a valid CSRF token and confirmed HTTP 403; valid session-bound tokens continued to submit successfully.
Test 42: PASS — Repeated rapid failed logins until the configured account lockout engaged; subsequent correct-password login remained rejected while locked.
Test 43: MANUAL — BAA coverage for production hosting and every ePHI-handling service requires deployment/vendor verification.
Test 44: MANUAL — Ensuring test and staging environments never contain real PHI requires organizational data-handling controls and cannot be proven by application tests.

Prompt 3.T regression: PASS — Included in the final full-suite run.
Prompt 4.T regression: PASS — Included in the final full-suite run.
Prompt 5.T regression: PASS — Included in the final full-suite run.
Prompt 6.T regression: PASS — Included in the final full-suite run.
Prompt 7.T regression: PASS — Included in the final full-suite run.
Prompt 8.T regression: PASS — Included in the final full-suite run.
Prompt 9.T regression: PASS — Included in the final full-suite run.
Prompt 10.T regression: PASS — Included in the final full-suite run.
Prompt 11.T regression: PASS — Included in the final full-suite run.

## Prompt 13.T — Mobile/Responsive

QA plan reference: `04-qa-test-plan.md` was not present in the workspace. Tests
97–99 remain intentionally device-dependent; Tests 100–101 have automated
coverage in `tests/test_responsive.py`.

Test 97: MANUAL — Complete visit notes for prenatal, gyn annual, postpartum, and problem-focused visit types on real iOS Safari and Android Chrome devices; see `TESTING.md`, Prompt 13.T, Test 97.1–97.8.
Test 98: MANUAL — Open lab-order and prescription panels on real iOS Safari and Android Chrome phones and confirm full-screen, unclipped modal behavior; see `TESTING.md`, Prompt 13.T, Test 98.1–98.3.
Test 99: MANUAL — Verify one-handed hamburger navigation and touch-target usability on real iOS Safari and Android Chrome devices; see `TESTING.md`, Prompt 13.T, Test 99.1–99.3.
Test 100: PASS — Automated `tests/test_responsive.py::test_100_theme_controls_and_dark_mode_contract_span_shared_pages` checks dark-mode CSS selectors, JavaScript toggle/localStorage behavior, and shared controls across welcome, patients, patient detail, schedule, reports, labs, prescriptions, and licensing pages.
Test 101: PASS — Automated `tests/test_responsive.py::test_101_dropped_first_response_retry_does_not_duplicate_appointment` simulates a committed appointment whose first response is dropped, retries the same client request ID, verifies exactly one appointment exists, and checks loading/error-state hooks and copy.

## 2026-09-13 — End-to-end clinic workflows

Test 102: PASS — `tests/test_end_to_end_workflows.py::test_new_ob_patient_day_through_browser_routes` exercised the New OB patient-day flow through registration, scheduling, check-in, nurse/M.A. intake, physician queue-to-visit opening, prenatal note save, New OB Panel ordering, prenatal-vitamin safety behavior, next-action follow-up handoff, gestational-age interval suggestion, front-desk follow-up booking, billing checkout, and billing-clerk note isolation.
Test 103: PASS — `tests/test_end_to_end_workflows.py::test_clinic_admin_corrects_duplicate_patient_through_delete_route` exercised duplicate correction through the patient delete route and confirmed active-view hiding, retained soft-deleted data, and the actor/entity/action delete audit event.
Test 104: PASS — Queue links now open the latest active visit documented for the selected queue date when one exists; otherwise they retain the patient-workspace link for starting a new note.
Test 105: PASS — Prenatal follow-up recommendations use 4 weeks before 28 weeks, 2 weeks from 28 through 35 weeks, and 1 week from 36 weeks onward; booking remains restricted to scheduling-write roles.

## Prompt 14.T — Cross-Module End-to-End

QA plan reference: `04-qa-test-plan.md` is not present in the workspace; this
regression ledger follows the numbered cases recorded in the prior Prompt
3.T–13.T results and the requested Prompt 14.T cases.

### Prompt 3.T — Foundation regression

Test 1: PASS — All five allowed roles logged in through the authenticated HTTP route.
Test 2: PASS — Authenticated-only and clinic-admin-only access controls rejected anonymous and unauthorized roles.
Test 8: PASS — Expired inactive sessions were rejected.
Test 9: PASS — Logout invalidated the prior session cookie.
Test 10: PASS — Weak passwords were rejected and repeated failed logins locked the account.
Test 12: PASS — Immediate role changes affected authorization.
Test 13: PASS — Unassigned roles failed closed without elevated access.
Test 14: PASS — Soft deletion retained the row with deletion metadata.
Test 15: PASS — Soft-deleted rows were excluded from default queries.
Test 16: PASS — Soft deletion created the correct audit event.
Test 19: PASS — No hard-delete path for soft-deletable models was found.
Test 20: PASS — Create, update, and delete operations wrote the expected audit events.
Test 21: PASS — Audit logs remained immutable for every role.

### Prompt 4.T — Patient demographics regression

Test 3: PASS — Front-desk projections excluded clinical fields.
Test 5: PASS — Billing projections exposed permitted demographics and excluded sensitive clinical fields.
Test 6: PASS — Clinical and operational staff could view active patients within their clinic according to the access design.
Test 7: PASS — Patient CRUD routes matched the role permission matrix.
Test 17: PASS — Soft-deleted patients disappeared from active views for every role and restored with data intact.
Test 18: PASS — Patient deletion retained linked state and audit history without orphaned records.
Test 58: PASS — Missing required patient fields returned clear validation errors without incomplete records.
Test 59: PASS — Similar patients followed the documented duplicate behavior without silent data loss.
Test 60: PASS — Structured allergies, medications, and contraception saved and reloaded correctly.

### Prompt 5.T — Scheduling regression

Test 50: PASS — Appointment types supported create, edit, and cancel while preserving identity and final status.
Test 51: PASS — Overlapping appointments followed the documented current policy.
Test 52: PASS — Walk-in creation persisted patient and checked-in appointment data atomically.
Test 53: PASS — Queue status transitions were ordered, audited, and visible to another authenticated viewer.

### Prompt 6.T — Clinical documentation regression

Test 63: PASS — All four visit types persisted their correct structured field sets.
Test 64: PASS — Gestational-age and corrected-EDD calculations were correct at the tested points.
Test 65: PASS — Structured ultrasound fields saved and reloaded correctly.
Test 66: PASS — Pregnancy trends included all visits in visit-date order.
Test 67: PASS — Gestational-age reminders triggered only at the correct points and not for gyn-annual visits.
Test 68: PASS — Reminder dismissal remained a UI dismissal and did not claim screening completion.
Test 69: PASS — Separate pregnancy episodes kept their visit histories isolated.
Test 70: PASS — Delivery outcomes remained linked to the correct pregnancy episode and history.
Test 71: PASS — Invalid ICD-10 codes were rejected and valid diagnoses saved.
Test 72: PASS — Shared phrase templates were snapshotted into notes.
Test 73: PASS — Locked visits rejected direct field edits.
Test 74: PASS — Amendments preserved the original note and recorded attribution.
Test 75: PASS — All supported procedure types linked to the correct visit.
Test 76: PASS — Partial notes preserved the fields that had already been entered.

### Prompt 7.T — Lab orders regression

Test 39: PASS — Lab upload type, signature, size, private-storage, and role-access checks passed.
Test 40: PASS — SQL-injection and XSS payloads remained data and rendered escaped across the tested text fields.
Test 77: PASS — Individual and New OB Panel orders linked to the correct visit and patient.
Test 78: PASS — Inline lab ordering returned a scoped fragment without resetting the note.
Test 79: PASS — Manual, file, and combined lab results persisted correctly.
Test 80: PASS — Uploaded result bytes remained stable after delay and re-query.
Test 81: PASS — Result review metadata and status transitioned correctly.
Test 82: PASS — Pending Labs reflected result creation immediately.

### Prompt 8.T — Prescriptions regression

Test 83: PASS — Inline prescription creation linked the prescription to visit, patient, and medication.
Test 84: PASS — Unsafe or unknown pregnancy classifications required acknowledgment while non-pregnant patients did not receive a pregnancy warning.
Test 85: PASS — Allergy conflicts required acknowledgment and non-conflicting vitamins remained confirmable.
Test 86: PASS — Printed prescriptions contained branding, patient, medication, dosage, duration, and prescriber information.
Test 87: PASS — Patient medication projections updated after soft discontinuation while retaining the record.

### Prompt 9.T — Billing regression

Test 45: PASS — Disabled Billing returned disabled/not-found responses and hid Billing UI surfaces.
Test 46: PASS — Disabled Billing exposed no financial reports.
Test 47: PASS — Enabling Billing took effect immediately without changing patient or visit data.
Test 48: PASS — Existing invoice and charge history survived disabling and re-enabling Billing.
Test 49: PASS — Billing clerks received a graceful disabled-module response.
Test 88: PASS — Charges used the selected clinic fee schedule amount.
Test 89: PASS — Paid invoice state persisted and appeared in the ledger.
Test 90: PASS — Printed invoices contained branding, context, itemization, amount, and status.
Test 91: PASS — Fee schedule changes were not retroactive to existing invoices.

### Prompt 10.T — Reporting regression

Test 92: PASS — Schedule, revenue, no-show, screening, pregnancy, and delivery reports returned exact seeded values.
Test 93: PASS — Report date boundaries included the documented endpoints and excluded neighboring records.
Test 94: PASS — PDF and Excel exports matched the report rows.
Test 95: PASS — Front desk could not access financial report data or exports.
Test 96: PASS — Soft-deleted appointments were excluded from report counts while retained in storage.

### Prompt 11.T — Licensing regression

Test 26: PASS — Active licenses allowed representative reads and writes across all enabled modules.
Test 27: PASS — Grace-period licenses allowed reads and blocked writes with the documented read-only response.
Test 28: PASS — License expiry and grace boundaries evaluated at the exact tested timestamps.
Test 29: PASS — Clinic-admin renewal restored writes without an app restart.
Test 30: PASS — Visit drafts remained available while transitioned saves were blocked.
Test 31: PASS — License page days-remaining and expiry values matched the database before and after renewal.
Test 32: PASS — Stale client license claims could not bypass server-side write enforcement.
Test 33: PASS — Physician creation followed the current contract because no seat-count rule is implemented.

### Prompt 12.T — Security hardening regression

Test 34: MANUAL — Database encryption at rest and encrypted backups require verification from the selected hosting provider.

The application-level suite cannot verify storage-provider encryption or backup
encryption.

Test 35: MANUAL — Production HTTPS redirect/rejection requires verification at the deployment TLS boundary; local development intentionally serves HTTP.

Test 36: PASS — Error responses and captured logs excluded passwords, session tokens, and PHI-like values.
Test 37: PASS — Rendered route URLs, query strings, links, and form actions excluded PHI.
Test 38: PASS — Production-configured 500 responses excluded tracebacks and internal paths.
Test 39: PASS — File-upload validation continued to reject disallowed, malformed, and oversized files.
Test 40: PASS — Comprehensive injection and XSS coverage passed across patient, scheduling, clinical, labs, prescriptions, and billing text.
Test 41: PASS — State-changing requests without a valid CSRF token were rejected.
Test 42: PASS — Repeated failed logins engaged account lockout.
Test 43: MANUAL — BAA coverage for hosting and every ePHI-handling service requires deployment/vendor verification.

Test 44: MANUAL — Keeping real PHI out of test and staging environments requires organizational data-handling controls.

### Prompt 13.T — Mobile/responsive regression

Test 97: MANUAL — Real iOS Safari and Android Chrome validation of all visit-note types remains required.

Test 98: MANUAL — Real-device validation of full-screen, unclipped lab-order and prescription panels remains required.

Test 99: MANUAL — Real-device validation of one-handed navigation and touch-target usability remains required.

Test 100: PASS — Automated theme-control and dark-mode contracts passed across shared pages.
Test 101: PASS — Dropped-response retry protection prevented duplicate appointments.

### Prompt 14.T — Requested cross-module workflows

Test 106: PASS — `tests/test_end_to_end_workflows.py::test_106_new_ob_patient_day_end_to_end` scripted registration, New OB scheduling, check-in, nurse/M.A. vitals and pregnancy episode intake, physician prenatal note completion, New OB Panel ordering, unsafe pregnancy-warning behavior, safe prenatal-vitamin prescribing, next-action follow-up handoff, the gestational-age-based four-week recommendation, front-desk follow-up booking, and Billing checkout. It asserted the final clinic, patient, appointment, episode, visit, lab-order, prescription, follow-up appointment, invoice, and charge links plus paid invoice state.
Test 111: PASS — `tests/test_end_to_end_workflows.py::test_111_clinic_admin_corrects_duplicate_patient_end_to_end` scripted duplicate correction through the clinic-admin delete route, verified immediate hiding from every role's patient list, confirmed the retained row could be restored, checked the actor/entity/action AuditLog fields, and confirmed linked appointment and visit rows remained intact and correctly associated.

Prompt 3.T–13.T full regression: PASS — `python -m pytest -q tests/test_foundation.py tests/test_patients.py tests/test_scheduling.py tests/test_clinical.py tests/test_labs.py tests/test_prescriptions.py tests/test_billing.py tests/test_reporting.py tests/test_licensing.py tests/test_security.py tests/test_responsive.py` completed with 159 passed and 3 existing dependency deprecation warnings.
Prompt 14.T end-to-end suite: PASS — `python -m pytest -q tests/test_end_to_end_workflows.py` completed with 2 passed and 2 existing dependency deprecation warnings.