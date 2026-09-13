# Manual Testing Notes

This file is the running list of manual verification steps for each feature
module. Append a dated section for every new feature or meaningful behavior.
Do not delete or rewrite earlier notes; keep steps short, reproducible, and
specific to the module being tested.

Recommended format:

```markdown
## YYYY-MM-DD — Feature or build prompt

- [ ] Start the documented development workflow.
- [ ] Exercise the primary user flow.
- [ ] Verify the expected success state.
- [ ] Verify validation and error states.
```

Automated tests run with:

```bash
python -m pytest -q
```

The pytest fixtures use a fresh in-memory SQLite database for every test and
override FastAPI's database dependency, so automated tests never touch the
development PostgreSQL database.

## Foundational schema and authentication

Use a development database and the current migration before following these
steps:

```bash
alembic upgrade head
```

- [ ] Create one development Clinic row.
- [ ] Create one User row for each role: `physician`, `nurse_ma`, `front_desk`,
      `billing_clerk`, and `clinic_admin`. Store only values produced by the
      Argon2 password helper.
- [ ] Visit `/login` and confirm each active user can sign in with valid
      credentials.
- [ ] Confirm the landing page says `Welcome, {name} ({role})`.
- [ ] Submit `/logout` and confirm the session is cleared.
- [ ] Confirm an anonymous request to `/welcome` redirects to `/login`.
- [ ] Soft-delete a test User through `soft_delete_record` as a
      `clinic_admin`, commit the transaction, and confirm a normal
      `select(User)` no longer returns it.
- [ ] Query the same record with
      `select(User).execution_options(include_deleted=True)` and confirm it is
      available for audit/recovery workflows.
- [ ] Attempt the same soft-delete operation as a non-admin and confirm the
      service raises `PermissionError`.

## Patient Demographics

Use a clinic with at least one active user for each role and run the current
migrations before testing:

```bash
alembic upgrade head
```

- [ ] Sign in as `physician`, `nurse_ma`, and `clinic_admin`; confirm
      `/patients` is visible and the patient table/detail shows the clinical
      fields allowed for those roles.
- [ ] Sign in as `front_desk` and `billing_clerk`; confirm `/patients` is
      visible but allergies, current medications, contraception, and emergency
      contact details are not present in the page or `/api/patients` and
      `/api/patients/{id}` responses.
- [ ] As a billing clerk, submit a crafted patient form containing allergy,
      medication, or contraception fields; confirm the API layer ignores those
      fields rather than relying only on template hiding.
- [ ] Use **Add patient** and **Edit demographics**; add multiple allergy and
      medication rows; confirm htmx updates the form/detail area without a full
      page reload and the rows are stored as structured objects.
- [ ] Open a patient detail page and confirm Summary, Visit History, Labs, and
      Prescriptions tabs render. Enable `Clinic.billing_module_enabled` and
      confirm Billing appears; disable it and confirm Billing is hidden.
- [ ] Confirm patient lists are clinic-scoped and newest records appear first.
- [ ] As a non-admin, confirm the delete action is absent and a direct delete
      request returns 403.
- [ ] As `clinic_admin`, soft-delete a patient; confirm the action writes an
      AuditLog row, sets `deleted_at` and `deleted_by_user_id`, removes the
      patient from normal list/API results, and retains it with
      `include_deleted=True`.

## 2026-09-11 — Prompt 4.T patient edge cases

- [ ] Confirm the product decision for duplicate detection. The current
      implementation intentionally has no duplicate-detection rule and accepts
      similar patient records; any future flag/block behavior should replace
      the corresponding automated expectation.
- [ ] For a deleted patient, use the administrative restore workflow backed by
      `restore_record`, then confirm the record returns to every role's list and
      retains its clinical data.

## 2026-09-12 — Scheduling

Use a clinic with at least one active physician and one active user for each
staff role. Apply the current migrations first:

```bash
alembic upgrade head
```

- [ ] As `clinic_admin`, open `/schedule`, create an appointment type, edit its
      name and default duration, and confirm the updated type is used by the
      booking form.
- [ ] As `front_desk`, book an existing patient for a physician; confirm the
      appointment appears in the calendar column at the requested time and
      uses the type's default duration when no override is entered.
- [ ] For every appointment type, create an appointment, edit its time or
      duration through the appointment edit action, then cancel it; confirm the
      same record retains its identity and ends with `cancelled` status.
- [ ] Create two overlapping appointments for the same physician; confirm the
      current intended behavior is that both are accepted because the product
      does not yet model rooms or block overlaps.
- [ ] Confirm the calendar date controls move between days and the schedule
      grid shows physician columns with appointment blocks sized by duration.
- [ ] As `front_desk`, submit the walk-in form with a new patient's name, date
      of birth, phone, physician, and type; confirm one Patient and one
      `checked_in` Appointment are created and appear in `/queue`.
- [ ] As `physician`, `nurse_ma`, and `front_desk`, open `/queue` and advance an
      appointment through `scheduled`, `checked_in`, `in_room`, `with_doctor`,
      and `done`; confirm each action updates the row and writes an AuditLog.
- [ ] Open the same queue in two actual browser sessions as different roles.
      Advance the appointment in one session, refresh or trigger the queue
      request in the other, and confirm the persisted status is visible. The
      current app uses htmx refreshes and does not provide server-pushed
      real-time updates without a browser request.
- [ ] Sign in as a physician and confirm `/welcome` is the physician's own
      today's queue; confirm queue patient links open the clinical workspace.
- [ ] Sign in as `billing_clerk`; confirm `/schedule`, `/queue`, and
      `/api/appointments` return 403.
- [ ] Confirm appointments, patients, physicians, and appointment types from a
      different clinic cannot be selected or retrieved through direct requests.

## 2026-09-12 — Visit Documentation

Apply all migrations and start the documented FastAPI workflow before testing:

```bash
alembic upgrade head
python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

- [ ] Sign in as `physician`, `nurse_ma`, and `clinic_admin`; open
      `/visits/patients/{patient_id}` and confirm the single scrolling visit
      workspace is available.
- [ ] Sign in as `front_desk` and `billing_clerk`; confirm the same clinical
      URL returns 403 and the patient detail page does not expose clinical
      fields.
- [ ] Create a pregnancy episode with an LMP and no EDD; confirm EDD is
      calculated as LMP + 280 days.
- [ ] Add a corrected EDD; confirm the original EDD remains stored and the
      workspace displays the corrected date for gestational-age context.
- [ ] Create a prenatal visit without an episode; confirm validation rejects it.
      Select an episode and save vitals, fundal height, fetal heart tones,
      fetal position, ultrasound values, HPI, assessment, plan, and one seeded
      ICD-10 code; confirm all sections reload from the saved note.
- [ ] Create a gyn annual, postpartum, and problem-focused note; confirm
      prenatal-only fields are not required and gyn screening fields are stored
      for the annual template.
- [ ] Attempt to submit an unavailable or inactive diagnosis ID directly;
      confirm the visit is rejected and no free-text diagnosis is accepted.
- [ ] Add each supported procedure type to an unlocked visit and confirm the
      structured detail and AuditLog row are present.
- [ ] Record a delivery outcome for an active pregnancy episode; confirm mode,
      complications, birth weight, Apgars, and delivered status are visible.
- [ ] Lock a note manually; confirm the original form is read-only and direct
      edits, phrase insertion, and procedures are rejected.
- [ ] Create an old note beyond the named 48-hour window; confirm it is treated
      as locked even when `locked_at` is null.
- [ ] Add an amendment to a locked note; confirm the amendment is visible with
      its timestamp and the original note fields have not changed.
- [ ] Create a phrase template, insert it into HPI/assessment/plan, edit the
      template, and confirm the existing note retains the original text snapshot.
- [ ] Use an episode at 24–28 weeks, 28–30 weeks, and 36–37 weeks; confirm the
      glucose, Rhogam, and Group B Strep prompts appear in their windows, become
      overdue after the window, and disappear after dismissal without changing
      screening completion data.
- [ ] Save multiple prenatal visits with weight, blood pressure, and fundal
      height; confirm the lightweight pregnancy trend renders the saved points.
- [ ] Save a visit and confirm the next-action prompt offers Schedule follow-up,
      Mark done, and Skip. Confirm follow-up returns to scheduling with the
      patient selected.
- [ ] Open the same patient in two browser sessions, save or amend in one, and
      refresh the other; confirm persisted data appears. The app intentionally
      uses refresh/htmx requests rather than server-pushed realtime updates.

## Route-level acceptance workflows

- [x] Run `python -m pytest -q tests/test_end_to_end_workflows.py` and confirm
      the New OB patient-day flow works through HTTP routes: front desk
      registration, New OB scheduling and check-in, nurse/M.A. episode and
      vitals intake, physician queue-to-visit opening, prenatal note save,
      New OB Panel ordering, prenatal-vitamin safety handling, next-action
      prompt, gestational-age follow-up cue, front-desk follow-up booking, and
      billing checkout. Confirm a billing clerk cannot view the clinical note.
- [x] In the same route-level suite, confirm clinic admin correction of a
      duplicate: soft-delete one patient, verify the deleted row is absent from
      every active role view, retain it for recovery, and verify the delete
      AuditLog actor, entity, and action.

## 2026-09-12 — Lab Orders

Apply all migrations and start the documented FastAPI workflow before testing:

```bash
alembic upgrade head
python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

- [ ] As a clinical user, open a saved visit and launch **Open lab ordering
      panel**. Confirm it opens as an inline slide-over without navigating away
      from the note.
- [ ] Order individual tests and a named order set. Confirm each order is
      attached to the current visit and patient, and appears in `/labs/pending`
      with status `ordered`.
- [ ] As `clinic_admin`, open `/admin/labs`; add, rename, describe, deactivate,
      and reactivate a test definition. Create and edit an order set and confirm
      its test membership controls what clinicians can order.
- [ ] Enter a manual result. Confirm the order changes to `resulted`, leaves
      Pending Labs, and clearly shows that physician review is still pending.
- [ ] Try to sign off a result as `nurse_ma`; confirm the action is rejected.
      Sign off as a physician and confirm the status becomes `reviewed` with the
      reviewing physician and timestamp visible.
- [ ] Upload a valid PDF and a valid PNG/JPEG/WEBP result. Confirm each can be
      downloaded by an authorized clinical role for that clinic and patient.
- [ ] Attempt uploads with an unsupported extension, an oversized body, a
      mismatched MIME type, and a renamed text file with a PDF extension.
      Confirm server-side validation rejects every one.
- [ ] Confirm uploaded files are not reachable through `/static`, the stored
      filename is not the client filename, and authorized download responses
      include attachment handling and `X-Content-Type-Options: nosniff`.
- [ ] As `front_desk` and `billing_clerk`, confirm the lab panel, Pending Labs,
      result download, and admin catalog routes are denied.

## 2026-09-12 — Prescriptions

Apply all migrations and start the documented FastAPI workflow before testing:

```bash
alembic upgrade head
python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

- [ ] As a `clinic_admin`, open `/admin/prescriptions`; confirm the seeded
      OB/GYN formulary is present and edit a medication's name, description,
      pregnancy flag, allergy category, and active status.
- [ ] Deactivate a formulary entry and confirm it no longer appears in the
      prescribing panel; reactivate it and confirm it returns. Confirm an
      existing prescription still displays its original formulary reference.
- [ ] As a physician, open a saved visit and launch **Open prescription panel**.
      Confirm the slide-over opens without navigating away or replacing the
      in-progress visit note.
- [ ] Confirm a prescription requires medication, dosage, frequency, and
      duration, is linked to both the current visit and patient, and appears
      on the patient Summary under **Active prescriptions** and on the
      Prescriptions tab.
- [ ] Give the patient an active pregnancy episode and select a formulary
      entry marked `false`; confirm a clear pregnancy warning appears before
      confirmation. Confirm `unknown` also produces an uncertainty warning.
- [ ] Attempt to submit a pregnancy-warning prescription without the
      acknowledgment checkbox; confirm the server rejects it and does not
      create a row. Acknowledge the warning and confirm the prescription is
      created with the acknowledgment recorded.
- [ ] Record an allergy such as `penicillin`, select a medication categorized
      as `penicillin`, and confirm the allergy warning appears. Confirm a
      missing allergy acknowledgment is rejected, then acknowledge it and
      confirm the prescription.
- [ ] Confirm an allergy warning and pregnancy warning can appear together and
      that both acknowledgments are required before the physician can confirm.
- [ ] Sign in as `nurse_ma` and `clinic_admin`; confirm they can review the
      panel/current medication history but a direct prescription confirmation
      request returns 403. Confirm front-desk and billing roles cannot access
      clinical prescription routes or sensitive medication data.
- [ ] Open **Print / save PDF** for a prescription. Confirm the standalone
      print view includes clinic name, configured `Clinic.branding_reference`
      logo, patient, visit date, prescriber, and full directions. Use the
      browser print dialog to save a PDF and confirm the toolbar is omitted
      from the printed page.
- [ ] Confirm prescription queries exclude soft-deleted rows, while the
      retained row and its audit history remain available through an
      administrative include-deleted inspection.

## 2026-09-12 — Optional Billing

Apply all migrations and start the documented FastAPI workflow before testing:

```bash
alembic upgrade head
python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

- [ ] As a `clinic_admin`, open `/admin/clinic-features` while Billing is
      disabled. Confirm the feature-settings page remains available, enable
      Billing, and confirm the Billing sidebar item appears for the admin and
      a `billing_clerk`.
- [ ] While Billing is disabled, request `/billing`,
      `/admin/billing`, a visit charge-entry URL, and a print-invoice URL
      directly. Confirm each returns HTTP 404 with the graceful
      **Billing is not available** state rather than a normal empty page.
- [ ] As a `clinic_admin`, open `/admin/billing`; add, edit, deactivate, and
      reactivate fee schedule items. Confirm non-admin users cannot change the
      catalog.
- [ ] As a `billing_clerk`, open a saved visit's charge-entry panel, select one
      or more active fee items, and create an invoice. Confirm the invoice is
      unpaid and every line links to the same visit and patient.
- [ ] Edit a fee after creating an invoice. Confirm the existing charge keeps
      its original description and price while future invoices use the new
      schedule value.
- [ ] Mark an invoice paid and unpaid from the ledger. Confirm both transitions
      are persisted and audited.
- [ ] Open the patient Billing tab and confirm invoice totals, visit links,
      status, and print links are visible only while the module is enabled.
- [ ] Open **Print / Save as PDF** and confirm the standalone HTML contains
      clinic name/branding, invoice number, patient, visit date, line items,
      total, and payment status.
- [ ] Disable Billing after creating an invoice. Confirm operational routes
      return 404 while the invoice row remains in the database. Re-enable the
      module and confirm the same invoice returns to the ledger unchanged.

## 2026-09-12 — Reporting

Apply all migrations and start the documented FastAPI workflow before testing:

```bash
alembic upgrade head
python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

Reporting uses inclusive date boundaries. Confirm the selected start date and
the entire selected end date are included; an appointment at 23:59 on the end
date must appear. The screening report uses visits inside the selected range,
and the active-pregnancy report is a snapshot as of the selected end date.

- [ ] Sign in as each role and open `/reports`. Confirm physicians and
      nurse/MAs see the clinical reports, front desk sees the schedule and
      no-show reports, and billing clerks see only the revenue report when
      Billing is enabled. Confirm a billing clerk cannot open clinical report
      URLs directly and a physician cannot open `/reports/revenue`.
- [ ] Disable Billing as `clinic_admin`. Confirm **Revenue summary** is absent
      from `/reports` and a direct request to `/reports/revenue` returns a
      deliberate unavailable/404 response. Re-enable Billing and confirm the
      report appears without restarting the app.
- [ ] Create a hand-counted sample for one two-day range:
      two active appointments on day one (one done and one no-show), one
      cancelled appointment, one appointment at 23:59 on the end date, and one
      soft-deleted appointment. Compare the Daily schedule & census totals and
      No-show rate to the sample. Confirm cancelled appointments are excluded
      from the no-show denominator and the deleted appointment is absent.
- [ ] Create two invoices with known line-item amounts, mark one paid, and
      create a soft-deleted invoice. Compare Revenue summary gross/paid/unpaid
      totals to a hand calculation from the active invoice snapshots. Confirm
      disabling Billing hides the report but does not delete the invoice rows.
- [ ] Record one Pap due date equal to the report end date and one future HPV
      due date. Confirm only Pap is reported overdue. Add a newer visit with
      revised due dates and confirm the latest non-empty in-range values are
      used; soft-delete the patient and confirm the patient disappears.
- [ ] Create active pregnancy episodes whose end-date gestational ages are
      13w6d, 14w0d, 27w6d, and 28w0d. Hand-count the first/second/third
      trimester cards and confirm the boundary transitions. Record a delivery
      outcome and confirm it leaves the active-pregnancy snapshot and appears
      once in the Delivery outcomes log.
- [ ] On every report detail page, set a start date and end date manually and
      confirm the page states the inclusive range. Click **Export PDF** and
      **Export Excel**; open both files and verify the title, date range, and
      detail rows match the hand-counted HTML report rather than only checking
      that a download occurred.

## 2026-09-12 — Licensing and subscription enforcement

Apply all migrations and start the documented FastAPI workflow before testing:

```bash
alembic upgrade head
python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

The local Licensing implementation is a placeholder for a future remote
license-server check-in. Use `/admin/license` as a `clinic_admin` to set
`expires_at`, `grace_period_days`, and the administrative state while testing.

- [ ] Confirm `0010_licensing` creates one License row for the clinic and that
      `/admin/license` shows status, days remaining, expiration, grace period,
      and last check-in.
- [ ] Set an expiration in the future. Confirm all existing authorized reads
      and writes continue to work.
- [ ] Set `expires_at` in the past but within `grace_period_days`. Confirm
      authenticated users can still open patients, visits, schedules, reports,
      and other read-only screens, while a direct POST/PUT/PATCH/DELETE request
      returns HTTP 423 with the clear read-only message.
- [ ] Set `expires_at` past the full grace period. Confirm reads still work and
      writes remain blocked. Confirm this works in an already-open browser
      session without logging in again.
- [ ] Submit an HTMX write while read-only. Confirm the response includes
      `HX-Reswap: none`, the page shows the calm read-only banner, and the
      submitted form is not replaced.
- [ ] Open a new or existing Visit Documentation note, enter unsaved HPI,
      assessment, and plan content, then force the license into read-only mode
      before submitting. Confirm the browser preserves the draft in the
      workspace/local storage, the note is not partially saved, and the content
      can be retried after renewal.
- [ ] As `clinic_admin`, renew the license from `/admin/license` while the
      clinic is read-only. Confirm the next write succeeds without restarting
      the app and the banner clears on the next page load.
- [ ] Sign in as a non-admin and confirm the license status/edit page returns
      HTTP 403 while the read-only banner still appears for all roles.
- [ ] Leave the app running for one scheduler interval or temporarily lower
      `LICENSE_CHECK_INTERVAL_SECONDS`; confirm `last_check_in_at` and the
      derived status update without a separate worker container.

## Security hardening

Apply the documented environment settings and start the FastAPI workflow before
testing. Use `APP_ENV=production` for the production-response checks.

### Prompt 12.T infrastructure and process boundaries

- **Test 34 — MANUAL/deployment:** Database encryption at rest cannot be
  meaningfully verified by application-level tests. Once real hosting is
  selected, verify encrypted database/storage volumes, encrypted backups, and
  key management at the infrastructure level.
- **Test 35 — MANUAL/deployment:** The local Uvicorn process intentionally
  serves HTTP for development and automated tests. Production must place it
  behind a TLS-terminating reverse proxy/load balancer that redirects HTTP to
  HTTPS, forwards the correct scheme, and keeps `Secure` session cookies
  enabled. The automated test verifies production cookies are `Secure`,
  `HttpOnly`, and `SameSite=Lax`; the external HTTP-to-HTTPS behavior requires
  the chosen hosting environment.
- **Test 43 — MANUAL/deployment:** Confirm the selected hosting providers have
  a BAA covering every service that handles ePHI. This is a contractual and
  deployment verification, not an application-unit-test assertion.
- **Test 44 — MANUAL/process:** Confirm test, staging, fixtures, backups, and
  support workflows never contain real PHI. This is an organizational
  data-handling requirement and must be verified through process controls.

### SQL injection and XSS

- [ ] Submit SQL-like values such as `' OR 1=1 --` through patient, scheduling,
      lab, prescription, billing, and report inputs. Confirm values are treated
      as data, no extra records are returned, and no database error reveals SQL.
- [ ] Submit `<script>alert(1)</script>` and an HTML attribute payload in patient
      names, lab text, appointment names, and report-visible fields. Confirm
      rendered pages show escaped text and do not execute markup.
- [ ] Confirm the application source contains no unsafe `|safe` template filter
      and that the only raw SQL is the constant `SELECT 1` health probe.
- [ ] Attempt to retrieve a lab result whose stored path contains `../` or an
      absolute path. Confirm the request returns a safe not-found/error response
      and cannot read outside the private upload directory.

### CSRF

- [ ] Open `/login`, remove the generated `_csrf_token`, and submit. Confirm
      HTTP 403 with a refresh message.
- [ ] Log in normally and submit a patient, appointment, visit, lab,
      prescription, billing, license, and logout form. Confirm each succeeds
      only with the current session token.
- [ ] Replay a token from a different browser/session or send a changed token.
      Confirm HTTP 403.
- [ ] Submit an HTMX write without the token. Confirm HTTP 403 and
      `HX-Reswap: none`; the existing form must not be replaced.

### Login lockout and session timeout

- [ ] Submit five incorrect passwords for one account. Confirm subsequent
      correct-password attempts remain rejected until the configured
      `LOGIN_LOCKOUT_SECONDS` period ends.
- [ ] Confirm the response does not reveal whether the email exists or whether
      the account is locked.
- [ ] Leave an authenticated session idle longer than
      `SESSION_INACTIVITY_SECONDS`. Confirm the next request redirects to
      `/login`, even though the cookie's maximum lifetime has not elapsed.
- [ ] Confirm logout invalidates the previous session cookie.

### Production error handling and logging

- [ ] Trigger a controlled unexpected application error with `APP_ENV=production`.
      Confirm the client receives only a generic error and no traceback,
      database URL, password, token, filesystem path, or exception message.
- [ ] Repeat in development mode and confirm debug detail is available only
      locally.
- [ ] Review application logs while submitting PHI-like names, clinical notes,
      passwords, invalid uploads, and malformed requests. Confirm names,
      medical details, passwords, session tokens, and credentials do not appear.
- [ ] Confirm scheduled background-task failures log only generic operational
      messages.

### URL and hosting boundary checks

- [ ] Inspect generated patient, visit, lab, prescription, and billing links.
      Confirm they contain identifiers and non-PHI filters only; patient names,
      allergies, medications, and clinical notes must not appear in URLs.
- [ ] Confirm production cookies include `Secure`, `HttpOnly`, and
      `SameSite=Lax`.
- [ ] Before go-live, verify the hosting provider offers a BAA covering every
      service that handles ePHI. Confirm encrypted volumes and backups, TLS,
      secret management, key rotation, least-privilege access, MFA for
      infrastructure operators, monitoring, retention, incident response, and
      disaster recovery are configured outside this application.
- [ ] For Test 34, record the selected hosting provider's encryption-at-rest
      and backup-encryption configuration before production data is loaded.
- [ ] For Test 35, run an external HTTP request against the production hostname
      and confirm it redirects to HTTPS; then confirm HTTPS pages retain the
      secure session-cookie attributes.
- [ ] For Test 43, retain the signed BAA/vendor coverage record for each
      production service that can process ePHI.
- [ ] For Test 44, verify non-production databases and support exports contain
      synthetic fixtures only and document the sanitization process.

## 2026-09-12 — Responsive, mobile, and accessibility pass

Start the documented FastAPI workflow and sign in with representative
`physician`, `front_desk`, `billing_clerk`, and `clinic_admin` accounts. Use the
browser responsive tools at 375px, 390px, 412px, 768px, and 1024px widths:

- [ ] Below **1024px**, confirm the desktop sidebar is replaced by a hamburger
      button. Open it, confirm the slide-out menu and backdrop do not clip the
      viewport, navigate from it, close it with the close button, and close it
      with Escape. Confirm the page behind it cannot scroll while it is open.
- [ ] At phone width, confirm the page header, title, accessibility controls,
      license banner, cards, forms, and tables do not create unintended
      horizontal page scrolling. Dense tables may use their own horizontal
      scroll region.
- [ ] Open the visit note at `/visits/patients/{patient_id}`. Confirm the note
      form, vitals, prenatal/gyn sections, diagnosis choices, pregnancy cards,
      draft-preservation behavior, saved-visit history, and action buttons remain
      usable at phone width.
- [ ] From a saved visit, open **Open lab ordering panel**. Confirm it becomes a
      full-screen modal below 640px, scrolls independently, keeps its Close
      control reachable, and allows selecting tests, ordering a bundle, entering
      a result, and returning to the note.
- [ ] From the same visit, open **Open prescription panel**. Confirm the
      medication selector, three direction fields, safety warnings,
      acknowledgment checkboxes, history, print link, and full-screen Close
      control remain usable without clipped content.
- [ ] When Billing is enabled, open the visit charge-entry panel at phone width
      and confirm it uses the same full-screen modal behavior.
- [ ] Open `/schedule` at phone width. Confirm the physician-grouped mobile
      agenda shows every appointment with time, patient, type, and status as a
      tappable card. At tablet/desktop width, confirm the full time grid remains
      available and can scroll horizontally when there are many physicians.
- [ ] Exercise Previous, Today, and Next schedule navigation, queue actions,
      patient tabs, reports, labs, prescriptions, billing, licensing, and admin
      forms at phone width. Confirm each primary action remains visible and
      tappable without relying on hover.
- [ ] Confirm primary buttons, close controls, menu links, appointment cards,
      checkboxes, selects, and form fields have comfortable touch targets and
      visible keyboard focus indicators.
- [ ] Toggle **Dark**, **Contrast**, and each text-size option from the shared
      header. Confirm the setting applies consistently to the visit note,
      calendar, panels, tables, login page, and admin screens, survives a page
      reload, and preserves readable status colors and focus indicators.
- [ ] Test with browser zoom and the platform text-size setting. Confirm large
      text reflows instead of hiding controls or creating unusable overlap.

The responsive preview is not sufficient for final sign-off. Spot-check the
complete checklist on a **real phone browser**—at minimum iOS Safari and
Android Chrome—before considering this pass done. Verify real touch scrolling,
keyboard behavior, safe-area/viewport handling, modal dismissal, and browser
autofill on both platforms.

## Prompt 13.T — Mobile/Responsive

QA plan reference: `04-qa-test-plan.md` was not present in the workspace. The
following checklist maps the requested Tests 97–101 to the current application.
Tests 97–99 are intentionally device-dependent. Tests 100–101 have automated
coverage and should still be spot-checked during the device pass.

### Test 97 — Complete visit notes on real phones

- [ ] **97.1 iOS Safari — prenatal:** On a real iPhone, sign in as a clinical
      user and complete one prenatal visit note. Reach and use the visit type,
      visit date, pregnancy episode, vitals, prenatal details, ultrasound
      findings, clinical narrative, diagnoses, save, and next-action controls.
- [ ] **97.2 iOS Safari — gyn annual:** Complete one gyn annual note on the same
      real iPhone. Confirm menstrual history, Pap/HPV dates, shared vitals,
      narrative, diagnoses, save, and next-action controls are reachable and
      usable.
- [ ] **97.3 iOS Safari — postpartum:** Complete one postpartum note. Confirm
      shared vitals, narrative, diagnoses, save, and next-action controls are
      reachable and usable without clipped fields or keyboard obstruction.
- [ ] **97.4 iOS Safari — problem-focused:** Complete one problem-focused note.
      Confirm shared vitals, narrative, diagnoses, save, and next-action
      controls are reachable and usable.
- [ ] **97.5 Android Chrome — prenatal:** Repeat a complete prenatal note on a
      real Android phone and verify every field listed in 97.1.
- [ ] **97.6 Android Chrome — gyn annual:** Repeat a complete gyn annual note
      and verify every field listed in 97.2.
- [ ] **97.7 Android Chrome — postpartum:** Repeat a complete postpartum note
      and verify every field listed in 97.3.
- [ ] **97.8 Android Chrome — problem-focused:** Repeat a complete
      problem-focused note and verify every field listed in 97.4.

### Test 98 — Full-screen clinical panels on real phones

- [ ] **98.1 Lab panel:** On a real iOS Safari phone, open the lab-order panel
      from a saved visit. Confirm it becomes a full-screen modal, the Close
      control remains reachable, the test list and bundle selector are usable,
      and the Create lab orders button is not clipped or hidden by the keyboard.
- [ ] **98.2 Prescription panel:** On the same iOS Safari phone, open the
      prescription panel. Confirm medication selection, dosage/frequency/
      duration fields, warning acknowledgments, history, print link, and
      confirmation button are all reachable.
- [ ] **98.3 Android Chrome repeat:** Repeat 98.1 and 98.2 on a real Android
      Chrome phone, including scrolling to the bottom of each modal and
      dismissing it without navigating away from the visit.

### Test 99 — One-handed navigation and touch targets

- [ ] **99.1 iOS Safari:** On a real iPhone, open and close the hamburger menu
      one-handed. Confirm the menu, backdrop, close control, navigation links,
      accessibility controls, and primary page actions can be tapped without
      precision tapping or accidental adjacent activation.
- [ ] **99.2 Android Chrome:** Repeat 99.1 on a real Android phone. Confirm
      menu scrolling, Escape-equivalent/back dismissal, and navigation work
      correctly with one-handed use.
- [ ] **99.3 Cross-screen spot check:** On both phones, spot-check the visit,
      calendar, queue, patient tabs, report filters, and panel buttons for
      comfortable touch targets and visible focus/active feedback.

### Test 100 — Automated theme coverage

- [ ] Run `python -m pytest -q tests/test_responsive.py -k test_100`.
      The automated test checks dark-mode selectors and toggle behavior in the
      shared CSS/JavaScript and spot-checks multiple authenticated pages, not
      only `/login`.

### Test 101 — Automated slow/lossy form retry coverage

- [ ] Run `python -m pytest -q tests/test_responsive.py -k test_101`.
      The automated test commits an appointment, simulates the first response
      being dropped, retries the same client request ID, and verifies that
      exactly one appointment exists. It also checks the loading, busy, and
      clear connection-error UI contract.
