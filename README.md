# OB/GYN Clinic Management App

This repository contains the initial, portable scaffold for a web application
that will support OB/GYN clinic operations. It intentionally stops before any
patient, user, appointment, or clinical data model is introduced.

## Stack

- **Backend:** Python and FastAPI
- **Templates:** Server-rendered Jinja2 HTML
- **Interactivity:** htmx loaded from its CDN
- **Styling:** Tailwind CSS loaded from its CDN
- **Database:** PostgreSQL through SQLAlchemy and psycopg
- **Migrations:** Alembic, configured but with no revisions yet
- **Services:** Exactly two Docker Compose services: `app` and `db`

The stack is deliberately minimal. There is no separate frontend build system,
Redis instance, worker, reverse proxy, or Replit-only dependency. Future
background jobs can run as in-process scheduled tasks inside FastAPI.

## Project structure

```text
app/
  config.py             Environment-backed settings
  database.py           SQLAlchemy engine and SELECT 1 probe
  main.py               FastAPI application factory and entry point
  models/               Reserved for the later database schema
  routes/               Health and server-rendered page routers
  schemas/              Reserved for request/response schemas
  services/             Reserved for business logic
  static/               CSS and future static assets
  templates/            Base sidebar shell and dashboard page
alembic/
  env.py                Migration environment wired to DATABASE_URL
  versions/             Empty until schema design is approved
docker-compose.yml      Portable app + PostgreSQL development environment
Dockerfile              Container image for the FastAPI app
requirements.txt        Pinned Python dependencies
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

## Database schema sequencing

No database schema has been created yet. This is deliberate: the clinical
domain requirements need to be agreed on before tables, models, or migrations
are generated. Alembic is already configured and will use the same standard
`DATABASE_URL` environment variable when the schema design step begins.