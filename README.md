# OB/GYN Clinic Management App

This repository contains the portable foundation for a web application that
supports OB/GYN clinic operations. It includes foundational tenancy,
authentication, auditing, soft-delete infrastructure, the Patient Demographics
module, and the Scheduling module. Future clinical workflows such as visits,
labs, and prescriptions remain intentionally scoped for later modules.

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
Redis instance, worker, reverse proxy, or Replit-only dependency. Future
background jobs can run as in-process scheduled tasks inside FastAPI.

## Project structure

```text
app/
  config.py             Environment-backed settings
  database.py           SQLAlchemy engine, ORM sessions, and soft-delete filter
  main.py               FastAPI application factory and entry point
  models/               Clinic, Patient, User, scheduling entities, and mixins
  routes/               Health, authentication, patient, scheduling, and page routers
  schemas/              Reserved for future request/response schemas
  services/             Authentication, scheduling, patient, and audit logic
  static/               CSS and future static assets
  templates/            Login, patient, scheduling, welcome, and shared shell
alembic/
  env.py                Migration environment wired to DATABASE_URL
  versions/             Foundational, auth-security, patient, and scheduling migrations
docker-compose.yml      Portable app + PostgreSQL development environment
Dockerfile              Container image for the FastAPI app
requirements.txt        Pinned Python dependencies
requirements-dev.txt    Test dependencies for pytest and FastAPI TestClient
tests/                  Isolated automated foundation tests
```

## Run in Replit

The development preview runs the same FastAPI application used by Docker:

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

Set `DATABASE_URL` to a PostgreSQL connection string in the environment before
expecting `/health` to report a healthy database. The application does not
depend on Replit-specific authentication, storage, database APIs, or secret
mechanisms.

Open the root page to see the empty sidebar layout:

```text
/
```

The health endpoint runs `SELECT 1` against PostgreSQL:

```text
/health
```

It returns HTTP 200 with `{"status":"ok","database":"ok"}` when the database is
reachable and HTTP 503 with a safe degraded response when it is not.

## Run with Docker Desktop

Copy the example environment file and adjust values if needed:

```bash
cp .env.example .env
docker compose up --build
```

The app will be available at `http://localhost:8000` and PostgreSQL will be
available at `localhost:5432`. The Compose file passes the internal database
hostname `db` to the app, so the application container can connect without
any host-specific configuration.

The only required application setting is `DATABASE_URL`. In Docker Compose it
is assembled from the `POSTGRES_*` variables. For a local process outside
Docker, use a URL such as:

```text
postgresql+psycopg://clinic:clinic@localhost:5432/obgyn
```

## Data Model

The migrations create the following foundational and patient tables:

- **Clinic** represents one tenant/customer and stores its name, branding
  reference, creation timestamp, extensible JSON settings, and the explicit
  `billing_module_enabled` opt-in flag, which defaults to `False`.
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
- **SoftDeleteMixin** adds `deleted_at` and `deleted_by_user_id`. SQLAlchemy
  SELECT statements exclude soft-deleted rows by default; callers must
  explicitly opt in with `include_deleted=True` to inspect them.

The application never hard-deletes clinical or financial data. Only the
`clinic_admin` role may trigger soft deletion or restoration, and that rule is
enforced in the service layer rather than only in the UI. Future clinical
models such as Patient, Visit, Prescription, and LabOrder must use the mixin.

## Authentication

`/login` provides a Jinja2 and htmx login form. Successful login stores only
the user ID and role in a signed session cookie. Passwords are hashed with
Argon2 and are never stored in plaintext. `/welcome` is protected by the
authentication dependency and displays the signed-in user's name and role.
`/logout` clears the session. The reusable `require_roles(...)` dependency is
available for every future route that needs role-based access control.

## Patient Demographics

The `/patients` workspace is visible to `physician`, `nurse_ma`, `front_desk`,
`billing_clerk`, and `clinic_admin`. It is ordered most-recent-first and
supports htmx create/edit forms without full-page form submissions. Allergies
and current medications are stored as structured lists of objects rather than
free-text fields. Only `physician`, `nurse_ma`, and `clinic_admin` can view or
write emergency contact, allergy, medication, and contraception fields.

Patient detail pages include Summary, Visit History, Labs, and Prescriptions
tabs. A Billing tab is rendered only when the owning Clinic has
`billing_module_enabled=True`; the tab currently shows an empty placeholder.
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
currently point to a visit placeholder for the next clinical module.

Front desk and clinic administrators can book an existing patient through
`POST /schedule/appointments`. The type's default duration is used when no
override is entered. The same roles can use `POST /schedule/walk-ins` to create
a new Patient and a `checked_in` Appointment in one transaction. The physician
must be an active physician in the same clinic, and all patient, doctor, and
appointment-type references are clinic-scoped in the service layer.

Clinic administrators can manage appointment types directly in the Schedule
workspace. Billing clerks do not have scheduling or queue access.

## Clinical schema sequencing

Visit, lab, prescription, and billing tables have not been created yet. This
is deliberate: those workflows need their own domain requirements. Alembic is
configured through the Scheduling migration, and future clinical records should
continue using the soft-delete and audit conventions.

## Development documentation

- [CONTRIBUTING.md](CONTRIBUTING.md) — coding conventions, module organization,
  naming rules, and the checklist for every new feature
- [TESTING.md](TESTING.md) — manual test notes to append as features are built
- [TEST_RESULTS.md](TEST_RESULTS.md) — append-only history of automated test runs