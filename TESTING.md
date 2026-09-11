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

- [ ] Sign in as `physician`, `nurse_ma`, `front_desk`, and `clinic_admin`;
      confirm `/patients` is visible and the patient table shows name, date of
      birth, contact, insurance, allergies, medications, and contraception.
- [ ] Sign in as `billing_clerk`; confirm `/patients` is visible but allergies,
      current medications, contraception, and emergency contact details are not
      present in the page or `/api/patients` and `/api/patients/{id}` responses.
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