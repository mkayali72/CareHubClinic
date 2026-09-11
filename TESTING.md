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