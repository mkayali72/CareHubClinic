# OB/GYN Clinic Management App

This repository contains the portable foundation for a web application that
  supports OB/GYN clinic operations. It includes foundational tenancy,
  authentication, auditing, soft-delete infrastructure, the Patient Demographics,
  Scheduling, Visit Documentation, Lab Orders, Prescriptions, optional Billing,
  RBAC-protected Reporting, and clinic Licensing enforcement modules.

## Stack

- **Backend:** Python and FastAPI
- **Templates:** Server-rendered Jinja2 HTML
- **Interactivity:** htmx loaded from its CDN
- **Styling:** Tailwind CSS loaded from its CDN
- **Database:** PostgreSQL through SQLAlchemy and psycopg
- **Migrations:** Alembic
- **Services:** Exactly two Docker Compose services: `app` and `db`
- **Authentication:** Signed sessions with Argon2 password hashing and role
  dependencies

The stack is deliberately minimal. There is no separate frontend build system,
Redis instance, worker, or reverse proxy. Future background jobs can run as
in-process scheduled tasks inside FastAPI.

## Project structure

```text
app/
  config.py             Environment-backed settings
  database.py           SQLAlchemy engine, ORM sessions, and soft-delete filter
  main.py               FastAPI application factory and entry point
  models/               Clinic, Patient, User, scheduling, and clinical entities
  routes/               Health, authentication, patient, scheduling, clinical, billing, reporting, licensing, and page routers
  schemas/              Reserved for future request/response schemas
  services/             Authentication, scheduling, clinical, patient, billing, reporting, licensing, and audit logic
  static/               CSS and future static assets
  templates/            Login, patient, scheduling, visit, billing, reports, licensing, welcome, and shared shell
alembic/
  env.py                Migration environment wired to DATABASE_URL
  versions/             Foundational, auth-security, patient, scheduling, clinical, lab, prescription, and billing migrations
docker-compose.yml      Portable app + PostgreSQL development environment
Dockerfile              Container image for the FastAPI app
requirements.txt        Pinned Python dependencies
requirements-dev.txt    Test dependencies for pytest and FastAPI TestClient
tests/                  Isolated automated foundation tests
```

## Run Locally with Docker Desktop

Docker Desktop is the supported portable runtime. The Compose project contains
exactly two services: `app` and `db`. The app container runs database migrations
before starting FastAPI, and PostgreSQL data is stored in the named
`postgres_data` volume.

1. Clone the repository and enter it:

   ```bash
   git clone <repository-url> obgyn-clinic
   cd obgyn-clinic
   ```

2. Create the local environment file:

   ```bash
   cp .env.example .env
   ```

3. Open `.env` and replace `SESSION_SECRET` with a long random value. Adjust
   the PostgreSQL username, password, or database name only if needed. Keep
   `DATABASE_URL` pointed at the Compose service name `db`.

4. Build and start both services:

   ```bash
   docker compose up --build
   ```

5. In a second terminal, confirm the app and database are healthy:

   ```bash
   curl http://localhost:8000/health
   ```

   Expected response:

   ```json
   {"status":"ok","database":"ok"}
   ```

6. Open `http://localhost:8000/login` in a browser. Stop the stack with
   `Ctrl+C`, or run `docker compose down`. The named database volume remains
   until it is explicitly removed with `docker compose down -v`.

To run the Python tests on the host, install the development requirements and
point `DATABASE_URL` at a PostgreSQL instance reachable from the host:

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

For a host process outside Docker, use a database URL with `localhost` instead
of `db`, for example:

```text
postgresql+psycopg://clinic:clinic@localhost:5432/obgyn
```

## Data Model

The migrations create the following foundational and patient tables:

- **Clinic** represents one tenant/customer and stores its name, branding
  reference, creation timestamp, extensible JSON settings, and the explicit
  `billing_module_enabled` opt-in flag, which defaults to `False`.
- **License** stores one clinic-scoped local subscription record with
  `status`, `expires_at`, `last_check_in_at`, and `grace_period_days`. It is the
  current placeholder for a future license-server response.
- **User** represents a staff account with a clinic, email, Argon2 password
  hash, full name, active status, creation timestamp, and exactly one of:
  `physician`, `nurse_ma`, `front_desk`, `billing_clerk`, or `clinic_admin`.
- **AuditLog** is a generic, immutable lifecycle log that records the actor,
  action, entity type, entity ID, timestamp, and JSON details/diff.
- **Patient** is a clinic-scoped soft-deletable demographic record with
  structured contact, insurance, emergency contact, allergy, and medication
  JSON data plus a standing contraception field. Patient API responses are
  projected by role; `front_desk` and `billing_clerk` receive only name, date
  of birth, contact, and insurance information, while clinical roles also
  receive emergency contact and clinical standing fields.
- **AppointmentType** is a clinic-scoped soft-deletable lookup row with a
  unique name and default duration. Only `clinic_admin` can create or edit
  appointment types.
- **Appointment** is a clinic-scoped soft-deletable scheduling record that
  references an existing Patient, a physician User, an AppointmentType,
  clinic-local scheduled time, duration, and an ordered status.
- **PregnancyEpisode** groups prenatal care for one patient. It stores the LMP,
  calculated original EDD, optional corrected EDD, and an active/delivered/ended
  status.
- **Visit** is a clinic-scoped structured note with a visit type, shared vitals,
  type-specific prenatal or gynecologic JSON sections, HPI, assessment, plan,
  diagnosis links, and a lock timestamp.
- **DiagnosisCode** is an active ICD-10 lookup row. Common OB/GYN codes are
  seeded by the clinical migration, and visits reference selected lookup rows
  through **VisitDiagnosis** rather than accepting free-text codes.
- **VisitAmendment** stores post-lock clarifications without mutating original
  visit fields. **ProcedureRecord** stores structured IUD, colposcopy, and
  endometrial-biopsy documentation.
- **DeliveryOutcome** closes a pregnancy episode with delivery date, mode,
  complications, birth weight, and Apgar values.
- **PhraseTemplate** stores reusable clinic phrases. **VisitPhraseUse** stores
  the exact text snapshot inserted into a note, so later template edits do not
  change existing documentation.
- **ReminderDismissal** records that a calculated pregnancy screening prompt was
  dismissed without claiming that the screening was completed.
- **SoftDeleteMixin** adds `deleted_at` and `deleted_by_user_id`. SQLAlchemy
  SELECT statements exclude soft-deleted rows by default; callers must
  explicitly opt in with `include_deleted=True` to inspect them.

The application never hard-deletes clinical or financial data. Only the
`clinic_admin` role may trigger soft deletion or restoration, and that rule is
enforced in the service layer rather than only in the UI. Deletable clinical
records reuse the mixin.

## Authentication

`/login` provides a Jinja2 and htmx login form. Successful login stores only
the user ID and role in a signed session cookie. Passwords are hashed with
Argon2 and are never stored in plaintext. `/welcome` is protected by the
authentication dependency and displays the signed-in user's name and role.
`/logout` clears the session. The reusable `require_roles(...)` dependency is
available for every future route that needs role-based access control.

Security controls, deployment limitations, and HIPAA BAA hosting requirements
are documented in [`SECURITY.md`](SECURITY.md). Manual security verification
steps are in `TESTING.md`.

## Licensing

Licensing is enforced server-side on every request, not only during login. The
app-level request dependency reads the current clinic License row on every
authenticated request. GET and other read-only requests remain available in
all non-revoked license states. POST, PUT, PATCH, and DELETE requests are
allowed while the license is active and return HTTP 423 with a clear
read-only message after expiration or revocation.

The local state rules are:

- **Active:** `now <= expires_at`; all authorized reads and writes work.
- **Grace:** after `expires_at` through
  `expires_at + grace_period_days`; reads work and writes are blocked.
- **Expired:** after the grace period; reads still work and writes are blocked.
- **Revoked:** an administrative inactive state; reads work and writes are
  blocked.

The in-process scheduler starts with FastAPI and periodically runs a local
check-in. Its interval is controlled by `LICENSE_CHECK_INTERVAL_SECONDS`
(default: 300 seconds). It updates `last_check_in_at` and the derived status;
it does not require a worker container, Redis, or another service.

This is intentionally a portable placeholder. The isolated
`perform_license_check_in` function in `app/services/licensing.py` is the
single replacement point for a future remote license-server check-in call.
The current implementation does not contact an external licensing service.
Migration `0010_licensing` backfills existing clinics with a one-year local
placeholder license. Older or test-created clinics without a row are lazily
given the same safe local placeholder when the admin view is opened.

Clinic administrators can view and manually configure the local record at
`/admin/license`. The notification-bell link is visible to clinic
administrators, and the page shows status, days remaining, expiration, grace
period, and last check-in. The admin route remains writable during read-only
enforcement so a renewal can recover the clinic.

When the state changes during an open browser session, the shared shell shows a
calm read-only banner. HTMX write responses use `HX-Reswap: none`, so the
current form is not replaced. The visit note workspace additionally stores
the submitted draft in browser `localStorage` before submission and restores it
when the workspace is reopened. A failed save therefore does not discard an
in-progress unsaved clinical note; the user can renew the license and retry.

## Patient Demographics

The `/patients` workspace is visible to `physician`, `nurse_ma`, `front_desk`,
`billing_clerk`, and `clinic_admin`. It is ordered most-recent-first and
supports htmx create/edit forms without full-page form submissions. Allergies
and current medications are stored as structured lists of objects rather than
free-text fields. Only `physician`, `nurse_ma`, and `clinic_admin` can view or
write emergency contact, allergy, medication, and contraception fields.

Patient detail pages include Summary, Visit History, Labs, and Prescriptions
tabs. A Billing tab is rendered only when the owning Clinic has
`billing_module_enabled=True` and shows active patient invoices. Billing
navigation is available to billing clerks and clinic administrators only when
the module is enabled.
Only `clinic_admin` can soft-delete a patient. Deletion writes an AuditLog row,
retains the database record, and removes it from normal patient queries.

## Scheduling

The `/schedule` workspace is the primary Google Calendar-style grid. It uses
server-rendered Jinja2 and a small amount of vanilla layout styling rather than
a heavy calendar dependency. Date navigation reloads only the calendar region
through htmx where appropriate. The grid shows a physician column for each
active physician and places appointments by their clinic-local start time and
duration.

The `/queue` workspace shows the selected day's patient flow for physicians,
nurses/MAs, front desk staff, and clinic administrators. Queue actions advance
one status at a time through `scheduled`, `checked_in`, `in_room`,
`with_doctor`, and `done`; `cancelled` and `no_show` remain terminal values.
Every status change is written to the immutable audit log. A physician's
`/welcome` landing page is their own today's queue, and queue patient links
open the real Visit Documentation workspace for clinical roles; front desk
links fall back to the demographic patient page.

Front desk and clinic administrators can book an existing patient through
`POST /schedule/appointments`. The type's default duration is used when no
override is entered. The same roles can use `POST /schedule/walk-ins` to create
a new Patient and a `checked_in` Appointment in one transaction. The physician
must be an active physician in the same clinic, and all patient, doctor, and
appointment-type references are clinic-scoped in the service layer.

Active appointments can be edited through
`POST /schedule/appointments/{appointment_id}/edit` and cancelled through
`POST /schedule/appointments/{appointment_id}/cancel`; cancellation preserves
the row and changes its status to `cancelled`. Completed, cancelled, and
no-show appointments cannot be edited or cancelled again.

The current scheduling policy allows overlapping appointments for the same
physician. There is no room field or overlap-blocking rule yet, so direct
creation of overlapping appointments succeeds. This behavior is covered by
the automated scheduling tests and should be revisited when room allocation
requirements are defined.

Clinic administrators can manage appointment types directly in the Schedule
workspace. Billing clerks do not have scheduling or queue access.

## Clinical Documentation

The Visit Documentation workspace is available at
`/visits/patients/{patient_id}` to `physician`, `nurse_ma`, and `clinic_admin`.
Front desk and billing roles are denied at the route and do not receive
clinical fields through a crafted request. The workspace is a single scrolling
page rather than a multi-step wizard so a clinician can document the complete
encounter without losing context.

### Pregnancy episodes and dating

- Create a pregnancy episode with an LMP. If an EDD is not supplied, the
  service calculates LMP + 280 days.
- Store an optional corrected EDD separately from the original calculation.
- The workspace displays gestational age as weeks and days and uses the
  corrected EDD when present.
- Prenatal visits must select a pregnancy episode. Gyn annual, postpartum, and
  problem-focused visits cannot be linked to an episode unless the visit type
  is prenatal.
- Delivery outcomes record mode, complications, birth weight, and Apgars, then
  move the episode to `delivered`.

### Structured visit notes

Every visit includes vitals, HPI, assessment, plan, and diagnoses selected from
the ICD-10 lookup. Visit templates add the appropriate fields:

- **Prenatal:** fundal height, fetal heart tones, fetal position,
  presentation, and ultrasound findings including estimated fetal weight, AFI,
  placenta location, presentation, and biometry.
- **Gyn annual:** menstrual history, Pap due date, and HPV due date.
- **Postpartum/problem-focused:** shared vitals and narrative fields without
  prenatal-only data.

Supported procedures are IUD insertion/removal, colposcopy, and endometrial
biopsy. Procedure details are structured records attached to the visit and
are audited on creation.

### Locking and amendments

The named lock policy is a configurable **48-hour window** beginning at visit
creation. A clinician can also lock a visit immediately. Once the manual lock
is set or the window expires:

- Direct note edits, phrase insertion, and new procedure records are rejected.
- The original HPI, assessment, plan, structured sections, and diagnosis links
  remain unchanged.
- A clinical user can add an amendment containing the correction or clarification.
- Lock, edit, and amendment actions are written to the immutable audit log.

### Phrases, reminders, and trends

Physicians can create clinic phrase templates and insert them into HPI,
assessment, or plan. Insertion appends a text snapshot to the note and records
which template and field were used. Editing a template later does not rewrite
old notes.

The pregnancy workspace calculates prompts for glucose tolerance testing
(24–28 weeks), Rhogam review (28–30 weeks), and Group B Strep culture
(36–37 weeks). Prompts become overdue after their window and can be dismissed;
dismissal is audited and is not a screening-completion record.

The lightweight trend view uses the explicit clinical visit date—not database
entry order—to show recorded weight over time. Each note retains fundal height
and blood pressure for clinical review without adding a heavy charting
dependency. Gyn annual visits do not show prenatal screening prompts.

After a visit saves, the screen offers three next actions: schedule a follow-up,
mark done, or skip. Schedule follow-up returns to the scheduling workspace with
the patient selected. For an active prenatal episode, the clinical scheduling
cue recommends every four weeks before 28 weeks, every two weeks from 28
through 35 weeks, and weekly from 36 weeks onward. Physicians and nurses can
review the cue; front desk or clinic admin staff complete the appointment
booking. When intake has already created a visit for the queue date, the
clinical queue opens that saved visit directly.

## Lab Orders

Lab ordering is clinic-scoped and starts from a saved visit. The visit workspace
opens an HTMX slide-over so clinicians can order individual tests or a named
`LabOrderSet` without leaving the note. A starter catalog includes CBC,
urinalysis, glucose screen, Rh/blood type, STI panel, Pap/HPV, and TSH.
`clinic_admin` users can edit the active catalog and maintain order-set
membership at `/admin/labs`.

Each `LabOrder` belongs to the visit and patient and moves through three
deliberately separate states:

1. `ordered` — the test is outstanding and appears in `/labs/pending`.
2. `resulted` — a clinician entered a manual value or uploaded a result file.
3. `reviewed` — a physician signed off the result with `reviewed_by` and
   `reviewed_at`. A resulted value is not treated as reviewed automatically.

Lab result files are private application data. They are not placed under
`/static`, and the database stores only a server-generated filename plus
original display metadata. The server rejects files above 10 MB, extensions
outside PDF/PNG/JPEG/WEBP, content types that do not match the extension, and
files whose magic bytes do not match the declared type. Stored directories use
0700 permissions and files use 0600 permissions when the filesystem supports
those modes. Download routes resolve the generated path beneath the configured
private root and require a clinical role in the same clinic before returning
the file with `nosniff` protection. The root defaults to `var/lab_results` and
can be changed with `LAB_UPLOAD_DIR`; mount that directory on a persistent
Docker volume for deployments where result files must survive container
replacement.

## Lab schema sequencing

`0007_lab_orders` creates the clinic test catalog, order sets, order-set
membership, soft-deletable lab orders, result metadata, review sign-off fields,
and the PostgreSQL lab status enum. It also seeds the starter test list for
clinics that already exist. New clinics are lazily seeded on first lab catalog
access so the same behavior works for local and Docker-created tenants.

## Prescriptions

The Prescriptions module starts from a saved visit and opens an HTMX slide-over
at `/visits/{visit_id}/prescriptions/order-panel`, so a physician can select a
clinic formulary medication and enter dosage, frequency, and duration without
leaving the note. Prescription confirmation is physician-only; clinical
support roles can review the current medication history but cannot confirm a
new prescription.

Each clinic receives a seeded OB/GYN-relevant formulary on first access. A
`clinic_admin` can edit the medication name, description, active status,
pregnancy-safety classification (`true`, `false`, or `unknown`), and
`allergy_category` at `/admin/prescriptions`. Deactivating a medication removes
it from future prescribing without changing existing prescription history.

### Patient-safety checks

The server recalculates warnings for every confirmation request; browser
checkboxes are not trusted. A pregnancy warning appears when the patient has
an active `PregnancyEpisode` and the selected formulary entry is marked
`false` (unsafe) or `unknown` (not classified). A separate allergy warning
appears when a structured patient allergy matches the medication name or
`allergy_category`, using case/punctuation normalization and known aliases
such as penicillin, sulfa, and NSAID labels. Reactions and severity are shown
as patient context but do not independently create a match.

These are explicit soft warnings, not hard blocks. The physician must
acknowledge every warning that is present before the server creates the
prescription, and the acknowledgment is stored on the prescription and in the
AuditLog details. The workflow does not hard-block because a broad formulary
classification cannot account for dose, gestational timing, alternatives, or
patient-specific clinical necessity; a physician may knowingly prescribe an
exception. The prompts are not a drug-interaction service and do not replace
clinical judgment or a patient-specific reference check.

Active prescriptions appear on the clinical Patient Summary and the
Prescriptions tab. Each has a print-friendly, clinic-branded view at
`/prescriptions/{id}/print` with the `Clinic.branding_reference` logo when
configured. Use the browser's **Print / Save as PDF** control to produce a
PDF without adding a non-portable PDF runtime dependency. Prescription rows
are soft-deletable and remain linked to their original visit and formulary
definition for audit history.

## Prescription schema sequencing

`0008_prescriptions` creates the tri-state pregnancy-safety enum, clinic
medication formulary, soft-deletable prescriptions, warning acknowledgment
fields, indexes, and starter medication rows for clinics that already exist.
New clinics are lazily seeded when the formulary is first read.

## Optional Billing

Billing is opt-in per Clinic and defaults to disabled. Clinic administrators
manage the flag from `/admin/clinic-features`, which remains available while
Billing is disabled so the module can be re-enabled. Every operational Billing
route checks the flag on the server; a disabled route returns HTTP 404 with a
graceful “Billing is not available” page rather than relying on hidden links.

When enabled, billing clerks and clinic administrators can use:

- `/billing` for the clinic invoice ledger and paid/unpaid transitions.
- Visit charge entry at `/visits/{visit_id}/billing/charge-panel`, with HTMX
  creation of unpaid invoices from the active fee schedule.
- `/admin/billing` for the clinic-admin-only fee schedule editor.
- `/billing/invoices/{id}/print` for a clinic-branded HTML invoice with browser
  **Print / Save as PDF** output.

`FeeScheduleItem` is a clinic-scoped soft-deletable catalog row. `Invoice` and
`Charge` are clinic-, patient-, and visit-linked soft-deletable financial
records. Each charge snapshots the fee name/description and price when it is
created, so later fee edits never rewrite historical invoices. Disabling the
module pauses new Billing operations but retains existing invoices, charges,
and audit history.

## Billing schema sequencing

`0009_billing` creates the PostgreSQL invoice-status enum, clinic fee schedule,
soft-deletable invoices and charges, indexes, and starter prices for existing
clinics. New clinics are lazily seeded on first enabled fee-schedule access.

## Licensing schema sequencing

`0010_licensing` creates the PostgreSQL `license_status` enum and one-to-one
clinic License table, then backfills existing clinics with local placeholder
licenses. Apply it with:

```bash
alembic upgrade head
```

## Reporting

The `/reports` workspace lists only reports allowed for the signed-in staff
role. Scheduling reports are available to physicians, nurse/MAs, front desk, and
clinic administrators. Clinical reports are available to physicians, nurse/MAs,
and clinic administrators. Revenue is restricted to billing clerks and clinic
administrators and is omitted from the report list, route, and exports while
`billing_module_enabled` is false.

The available reports are:

- **Daily schedule & census** (`/reports/schedule`) — appointments by day,
  status mix, and unique active census. Cancelled and no-show appointments stay
  in the schedule status mix but do not count toward active census.
- **Revenue summary** (`/reports/revenue`) — active invoice count, gross,
  paid, and unpaid totals using non-deleted charge snapshots. Deleted invoices,
  charges, visits, and patients are excluded, and Billing's feature gate still
  applies when reading retained history.
- **No-show rate** (`/reports/no-show-rate`) — no-shows divided by eligible
  appointments. Cancelled appointments are excluded from both numerator and
  denominator; soft-deleted appointments and patients are excluded.
- **Patients due for screening** (`/reports/screening`) — the latest non-empty
  Pap and HPV due dates documented by an active visit in the selected range,
  with dates on or before the range end marked overdue.
- **Active pregnancies by trimester** (`/reports/pregnancies`) — active,
  non-deleted pregnancy episodes as of the range end, using corrected EDD when
  present. First trimester is under 14 weeks, second is 14–27 weeks, and third
  is 28 weeks or more.
- **Delivery outcomes log** (`/reports/deliveries`) — one row per delivery
  outcome whose delivery date is in the selected range, joined only to active
  pregnancy episodes and patients.

All report date ranges are **inclusive on both boundaries**. Date fields use
`start_date <= value <= end_date`; appointment timestamps use midnight at the
start date through, but not including, midnight after the end date. This means
an appointment at 23:59 on the end date is included. The screening report uses
the selected visit-date range, while the pregnancy report is an end-date
snapshot by design.

Each report page offers browser-independent **Export PDF** and **Export Excel**
downloads. PDF output uses ReportLab and XLSX output uses openpyxl; both
serializers consume the same tested service result as the HTML view.

## Clinical schema sequencing

`0005_clinical_documentation` creates the pregnancy, visit, diagnosis,
amendment, procedure, delivery, phrase, and reminder tables and seeds common
ICD-10 choices. `0006_visit_dates` adds the explicit date used for visit
history and pregnancy trend ordering. Apply both with:

```bash
alembic upgrade head
```

Clinical and financial records remain clinic-scoped, auditable, and portable to
Docker Desktop.

## Responsive layout, theming, and accessibility

The shared Jinja shell is responsive without adding a frontend build system:

- **Below 1024px (`lg`)** the desktop sidebar is replaced by a hamburger button,
  a focusable slide-out navigation drawer, and a dismissible backdrop. The
  drawer closes with its close button, a navigation link, the backdrop, or the
  Escape key.
- **Below 768px (`md`)** the scheduling time grid becomes a physician-grouped
  mobile agenda. The wider grid remains available from tablet width upward
  inside a horizontal scroll container so no appointment columns are clipped.
- **Below 640px (`sm`)** lab, prescription, and billing slide-over panels become
  full-screen modal surfaces. At larger widths they remain right-side panels
  capped at 36rem. Phone panels include safe-area padding for notches and home
  indicators, and Escape dismisses an open panel.
- Shared controls and form fields use approximately 44px minimum touch targets.
  Tables retain an intentional horizontal scroll region where a dense tabular
  layout is more useful than hiding columns.

Display preferences are stored locally in the browser and apply to the shared
shell, login page, calendar, visit note, panels, tables, and administrative
screens:

- **Dark mode** uses the `data-theme="dark"` attribute plus CSS semantic
  overrides for the existing Tailwind utility palette.
- **Text size** offers small, normal, and large settings through the
  `data-font-size` attribute. The large setting scales the rem-based interface
  without changing stored clinical values.
- **High contrast** uses `data-contrast="high"` to strengthen text, borders,
  focus rings, and input contrast. These settings are enhancements and do not
  replace browser or operating-system accessibility settings.

The behavior is implemented with the small vanilla script at
`app/static/js/app.js` and shared styling at `app/static/css/app.css`. Confirm
the manual mobile checklist in `TESTING.md` on physical iOS Safari and Android
Chrome before treating touch behavior as production-verified.

## Development documentation

- [CONTRIBUTING.md](CONTRIBUTING.md) — coding conventions, module organization,
  naming rules, and the checklist for every new feature
- [TESTING.md](TESTING.md) — manual test notes to append as features are built
- [TEST_RESULTS.md](TEST_RESULTS.md) — append-only history of automated test runs