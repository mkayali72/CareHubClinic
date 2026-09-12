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