# OB/GYN Clinic Management App

Portable FastAPI foundation for an OB/GYN clinic management app. The current
release includes foundational tenancy, staff authentication, auditing, and
soft-delete infrastructure while intentionally stopping before clinical data.

## Run & Operate

- `pnpm --filter @workspace/api-server run dev` — run the API server (port 5000)
- `pnpm run typecheck` — full typecheck across all packages
- `pnpm run build` — typecheck + build all packages
- `pnpm --filter @workspace/api-spec run codegen` — regenerate API hooks and Zod schemas from the OpenAPI spec
- `pnpm --filter @workspace/db run push` — push DB schema changes (dev only)
- `python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}` — run the FastAPI preview
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

- `app/` — FastAPI application, server-rendered routes, templates, static CSS, and reserved domain folders
- `alembic/` — migration configuration and the foundational schema revision
- `docker-compose.yml` — portable `app` and `db` services for Docker Desktop
- `README.md` — setup, portability, and schema sequencing documentation

## Architecture decisions

- The app uses a standard `DATABASE_URL` and normalizes generic PostgreSQL URLs to the installed psycopg 3 driver.
- Foundational models cover Clinic, User, AuditLog, and reusable soft deletion; clinical entities remain a separate later step.
- Sessions use signed cookies and Argon2 hashes; role checks and destructive-action authorization are enforced in Python services/dependencies.
- The preview and Docker Compose both run the same FastAPI entry point.

## Product

The current product surface includes a signed-session login flow, a protected
welcome page, the clinic operations shell, PostgreSQL-backed `/health`, and
foundational audit/soft-delete infrastructure.

## User preferences

The user requires exactly two services (`app` and `db`), no frontend build
system, no Replit-specific dependencies, and no clinical data models until
those requirements are provided.

## Gotchas

- Keep `DATABASE_URL` portable and standard; do not replace it with a platform-specific database API.
- Clinical models must reuse SoftDeleteMixin and destructive actions must be
  authorized in the service layer by clinic_admin.

## Pointers

- See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details
