# OB/GYN Clinic Management App

Portable FastAPI foundation for an OB/GYN clinic management app. The current
release includes foundational tenancy, staff authentication, auditing,
soft-delete infrastructure, Patient Demographics, Scheduling, Visit
Documentation, Lab Orders, and Prescriptions.

## Run & Operate

- `pnpm --filter @workspace/api-server run dev` — run the API server (port 5000)
- `pnpm run typecheck` — full typecheck across all packages
- `pnpm run build` — typecheck + build all packages
- `pnpm --filter @workspace/api-spec run codegen` — regenerate API hooks and Zod schemas from the OpenAPI spec
- `pnpm --filter @workspace/db run push` — push DB schema changes (dev only)
- `python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}` — run the FastAPI preview
- `python -m pytest -q` — run the isolated automated test suite
- Required env: `DATABASE_URL` — standard PostgreSQL connection string

## Stack

- Python 3.13
- Web: FastAPI + Jinja2
- Interactivity: htmx from CDN
- Styling: Tailwind CSS from CDN
- DB: PostgreSQL + SQLAlchemy + psycopg
- Migrations: Alembic
- Runtime: exactly two Docker Compose services, `app` and `db`

## Where things live

- `app/` — FastAPI application, server-rendered routes, templates, static CSS, and domain services
- `alembic/` — migration configuration and ordered schema revisions
- `docker-compose.yml` — portable `app` and `db` services for Docker Desktop
- `README.md` — setup, portability, and schema sequencing documentation

## Architecture decisions

- The app uses a standard `DATABASE_URL` and normalizes generic PostgreSQL URLs to the installed psycopg 3 driver.
- Foundational models cover Clinic, User, AuditLog, and reusable soft deletion;
  Patient, AppointmentType, and Appointment extend that foundation.
- Sessions use signed cookies and Argon2 hashes; role checks and destructive-action authorization are enforced in Python services/dependencies.
- The preview and Docker Compose both run the same FastAPI entry point.

## Product

The current product surface includes a signed-session login flow, a protected
welcome page, clinic-scoped patient demographics, a calendar and today's queue,
    the clinic-scoped Visit Documentation workspace, HTMX Lab Orders and
    Prescriptions workflows, PostgreSQL-backed `/health`, and foundational
    audit/soft-delete infrastructure.

## User preferences

The user requires exactly two services (`app` and `db`), no frontend build
system, and no Replit-specific dependencies.

## Gotchas

- Keep `DATABASE_URL` portable and standard; do not replace it with a platform-specific database API.
- Clinical models must reuse SoftDeleteMixin and destructive actions must be
  authorized in the service layer by clinic_admin.
- Scheduling status values and transitions are ordered in AppointmentStatus;
  queue actions advance one step and are audited.
- Clinical documentation is limited to physicians, nurse/MAs, and clinic
  administrators. Visit fields lock after the named 48-hour window or an
  explicit lock, with amendments as the only post-lock note update.
- Lab result files must remain outside the public static mount; validate size,
  extension, declared type, and magic bytes server-side, generate storage names,
  and authorize every download against the user's clinic and clinical role.
- Prescription pregnancy and allergy checks are server-side soft warnings:
  physicians must explicitly acknowledge each warning before confirmation, but
  the app does not hard-block clinically justified exceptions.

## Pointers

- See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details
