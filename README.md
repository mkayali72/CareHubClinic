# OB/GYN Clinic Management App

This repository contains the portable foundation for a web application that
will support OB/GYN clinic operations. It includes foundational tenancy,
authentication, auditing, and soft-delete infrastructure, but intentionally
stops before clinical data models such as patients and visits.

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
  models/               Foundational Clinic, User, AuditLog, and mixins
  routes/               Health, authentication, and server-rendered page routers
  schemas/              Reserved for future request/response schemas
  services/             Authentication and audit/soft-delete business logic
  static/               CSS and future static assets
  templates/            Login, welcome, and shared sidebar shell
alembic/
  env.py                Migration environment wired to DATABASE_URL
  versions/             Foundational schema migration
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

The first migration creates only foundational, non-clinical tables:

- **Clinic** represents one tenant/customer and stores its name, branding
  reference, creation timestamp, extensible JSON settings, and the explicit
  `billing_module_enabled` opt-in flag, which defaults to `False`.
- **User** represents a staff account with a clinic, email, Argon2 password
  hash, full name, active status, creation timestamp, and exactly one of:
  `physician`, `nurse_ma`, `front_desk`, `billing_clerk`, or `clinic_admin`.
- **AuditLog** is a generic, immutable lifecycle log that records the actor,
  action, entity type, entity ID, timestamp, and JSON details/diff.
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

## Clinical schema sequencing

Clinical tables have not been created yet. This is deliberate: the clinical
domain requirements need to be agreed on before adding patients, visits, labs,
prescriptions, billing records, or other operational entities. Alembic is
configured and the foundational migration is already in place for the four
non-clinical building blocks above.

## Development documentation

- [CONTRIBUTING.md](CONTRIBUTING.md) — coding conventions, module organization,
  naming rules, and the checklist for every new feature
- [TESTING.md](TESTING.md) — manual test notes to append as features are built
- [TEST_RESULTS.md](TEST_RESULTS.md) — append-only history of automated test runs