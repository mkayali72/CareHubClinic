# Development Conventions

These conventions apply to every change in the OB/GYN clinic management app.
They are written so another coding assistant can extend the project without
having to infer local patterns from individual modules.

## Documentation and type hints

### Google-style docstrings

Use Google-style docstrings for every Python module, class, and function.
Docstrings should explain purpose, parameters, return values, side effects, and
important assumptions. Use the following shape when a section is applicable:

```python
def find_visit(visit_id: int, include_notes: bool = False) -> Visit | None:
    """Find one visit by identifier.

    Args:
        visit_id: Primary key of the visit to find.
        include_notes: Whether the response should include clinical notes.

    Returns:
        The matching Visit, or None when no visit exists.

    Raises:
        DatabaseError: If the database query cannot be completed.

    Side effects:
        Reads from the configured PostgreSQL database.
    """
```

Every function and method must have type hints for all parameters and its
return value. Avoid untyped `dict`, `list`, and `tuple`; use precise generic
types such as `dict[str, str]`, `list[Visit]`, or a named schema instead.
Classes should have typed attributes. Constants should have explicit types when
their type is not obvious.

## Application organization

The application is organized by responsibility:

```text
app/
  routes/       HTTP endpoints; one router module per feature or endpoint group
  services/     Business rules and orchestration; no HTTP response formatting
  models/       SQLAlchemy persistence models; one module per core entity/group
  schemas/      Pydantic request and response contracts
  templates/    Jinja2 templates, grouped by feature when the app grows
  static/       CSS, JavaScript, and other browser assets
```

Use one router file per domain module. Planned examples include:

```text
app/routes/scheduling.py
app/routes/patients.py
app/routes/visits.py
app/routes/labs.py
app/routes/prescriptions.py
app/routes/billing.py
app/routes/reporting.py
```

Name the matching service and schema modules after the same domain:

```text
app/services/scheduling.py
app/models/patient.py
app/schemas/visits.py
```

Keep route handlers thin. They should validate input, call a service, and
return an HTML response or API response. Business rules belong in services.
Database access belongs in services or dedicated database helpers, not in
templates.

### Database model documentation

Every SQLAlchemy model module must begin with a module-level docstring that
explains:

1. Which real-world entity or relationship the module represents.
2. How the entity relates to other models.
3. Any important lifecycle, privacy, or ownership assumptions.

Each model class must also have a Google-style class docstring. Do not create a
model for a concept until its relationship to the clinical domain is understood
and documented.

## Routes and templates

### API and page routes

- Use lowercase, plural nouns for collection resources: `/patients`,
  `/appointments`, `/labs`.
- Use path parameters for one resource: `/patients/{patient_id}`.
- Use nested paths only when the relationship is meaningful:
  `/patients/{patient_id}/visits`.
- Use HTTP methods consistently: `GET` reads, `POST` creates, `PATCH` updates
  part of a resource, and `DELETE` removes a resource.
- Keep health and operational probes at root-level paths such as `/health`.
- Name router functions after the action and resource, such as
  `list_patients`, `create_visit`, or `show_dashboard`.

### Jinja templates

- Use lowercase snake_case filenames: `dashboard.html`,
  `patient_detail.html`, `visit_form.html`.
- Group feature templates in folders once a feature has more than one template:
  `app/templates/patients/detail.html`.
- Use `base.html` for shared document structure and feature templates for
  content blocks.
- Keep clinical terminology and display formatting in templates or a dedicated
  presentation helper, not in database models.

## New feature checklist

Every new feature module must ship together with:

1. The feature code, including its router, service, schema, model, and
   templates where applicable.
2. Google-style docstrings and complete type hints following this document.
3. A short README section describing what the module does, its routes, and any
   important setup or domain assumptions.
4. Relevant manual test steps appended to `TESTING.md`.
5. Automated test results appended to `TEST_RESULTS.md` when an automated test
   batch is run.

Do not overwrite older testing history. Append new dated sections to
`TEST_RESULTS.md`.

## Scope guard for the initial scaffold

The initial scaffold intentionally has no patient, user, appointment, or
clinical data models and no Alembic revisions. Preserve that boundary until a
separate schema-design decision is approved.