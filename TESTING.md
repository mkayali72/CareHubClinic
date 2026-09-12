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
