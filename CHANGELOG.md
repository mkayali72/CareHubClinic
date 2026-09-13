# Changelog

## 2026-09-13 — Portable Docker Desktop export

- Added a standard Docker entrypoint that applies Alembic migrations before
  starting the FastAPI app.
- Wired the Compose `app` and `db` services to `.env`, the `db` service hostname,
  a persistent named PostgreSQL volume, and the configurable application port.
- Hardened the app image to run as a non-root user and persist private lab
  uploads under the configured application data directory.
- Added the complete Docker Desktop setup walkthrough and expanded local
  environment and runtime ignore rules.

## 2026-09-13

- Added route-level acceptance coverage for the complete New OB patient-day
  workflow, including registration, scheduling, check-in, intake, clinical
  documentation, lab ordering, prescription safety behavior, follow-up
  scheduling, billing checkout, and billing-clerk clinical-note isolation.
- Added route-level acceptance coverage for clinic-admin correction of a
  duplicate patient, including active-view hiding, retained-row recovery, and
  delete audit verification.
- Fixed the queue's clinical patient link so it opens the latest active visit
  documented for that queue date instead of starting a blank visit.
- Added a gestational-age-based prenatal follow-up recommendation to the
  scheduling workspace and preserved the patient selection when the booking
  handoff moves from clinical staff to front desk.