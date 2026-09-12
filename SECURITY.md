# Security controls and deployment boundary

This document describes the security controls currently implemented in the
portable OB/GYN clinic application and the controls that remain deployment or
future-product responsibilities. It is not a HIPAA certification or a
substitute for a formal risk analysis, business-associate agreement, or
organization-specific security policy.

## Implemented in the application

### Authentication, sessions, and login protection

- Passwords are hashed with Argon2 and are never written to logs or stored in
  plaintext.
- Login errors use the same generic message for unknown accounts, bad
  passwords, inactive users, and locked accounts.
- Five failed password attempts lock the account for the configured
  `LOGIN_LOCKOUT_SECONDS` period. `LOGIN_MAX_FAILED_ATTEMPTS` and
  `LOGIN_LOCKOUT_SECONDS` are environment settings.
- Session cookies are signed by Starlette's `SessionMiddleware`.
- Production cookies use `Secure` and `SameSite=Lax`.
- Sessions expire after inactivity using `SESSION_INACTIVITY_SECONDS`
  (default: 1,800 seconds) and also have a signed-cookie maximum lifetime from
  `SESSION_MAX_AGE_SECONDS` (default: 1,209,600 seconds).
- Logout increments the database session version and clears the browser
  session, invalidating the previous cookie.
- Sessions contain only identifiers, role/session metadata, timestamps, and a
  CSRF token. They do not contain patient data, passwords, or credentials.

### CSRF protection

- Every `POST`, `PUT`, `PATCH`, and `DELETE` route is covered by the global
  `enforce_csrf` dependency.
- Browser pages receive a cryptographically random token bound to the signed
  session. Shared JavaScript adds it to normal forms and HTMX requests.
- API-style callers may send the same value in `X-CSRF-Token`.
- Missing, stale, or mismatched tokens return HTTP 403. HTMX responses use
  `HX-Reswap: none` so a failed request does not replace a form.
- Login and logout are protected as well; the login page establishes the
  anonymous session token before submission.

### SQL injection and XSS

- Application data access uses SQLAlchemy ORM expressions with bound
  parameters. The only raw SQL is the constant database health probe
  `SELECT 1`; it contains no user input.
- There are no application `|safe` template filters. Jinja2 autoescaping is
  enabled for rendered HTML.
- Error and HTMX response bodies use fixed messages or escaped content.
- Client-side banner updates use `textContent`, not `innerHTML`, for
  user-controlled response text.
- Lab-result filenames are reduced to generated UUID names, and file retrieval
  rejects absolute paths and parent-directory traversal before resolving the
  private path.

### Error handling

- `APP_ENV=production` enables FastAPI production behavior and a generic
  application error response. Internal exception messages and stack traces are
  not returned to the client.
- Development responses may include the exception message to aid local
  debugging. Development mode must not be used for PHI or production traffic.
- Application error logs contain generic event messages only; exception
  messages and tracebacks are intentionally not logged because they may contain
  patient data or secrets.
- User-facing validation and authorization messages are intentionally limited
  to the action needed by the user.

### PHI, secrets, and URLs

- Patient and clinical records are clinic-scoped and role-filtered.
- Application logs do not write patient names, clinical details, passwords,
  tokens, or credentials. Audit rows use actor/entity identifiers and
  structured operational details rather than patient free text.
- Patient links use internal identifiers. Patient names, allergies, medication
  details, and clinical notes are not placed in URL paths or query strings.
  Report filters use dates and report selection only.
- Lab files are stored outside public static assets with restrictive file
  permissions and are served only after clinic and clinical-role checks.

## Explicitly not implemented yet

- **MFA:** Multi-factor authentication is not implemented. It is a recommended
  phase-2 addition in the application specification.
- **Distributed/IP login rate limiting:** The current protection is
  account-based failed-attempt lockout. A shared Redis or edge/API-gateway
  limiter is not part of this portable two-service application.
- **Remote license authority:** License check-in currently evaluates the local
  placeholder record. A remote licensing service remains a follow-up.
- **Database encryption at rest in application code:** SQLAlchemy/FastAPI
  cannot provide disk encryption. Encrypted volumes, managed database
  encryption, backup encryption, and key rotation must be configured by the
  eventual hosting infrastructure.
- **End-to-end operational HIPAA program:** Policies, workforce training,
  access reviews, incident response, retention, breach notification, and
  formal risk analysis remain organizational responsibilities.

## Requirements for a HIPAA BAA-covered deployment

The production hosting arrangement must be evaluated separately. At minimum,
the deployment owner must confirm:

- A Business Associate Agreement with the cloud/database/object-storage
  providers that handle ePHI.
- Encrypted disk/database volumes and encrypted backups, configured at the
  infrastructure or managed-service level.
- TLS at the edge and between services where applicable.
- Secret management and key rotation for `SESSION_SECRET`, database
  credentials, and any future integration credentials.
- Least-privilege database, deployment, and operator access with MFA on
  administrative infrastructure accounts.
- Centralized access monitoring, immutable audit retention, alerting, and
  incident-response procedures that do not expose PHI in routine logs.
- Network controls, firewall rules, private database access, backup retention,
  disaster recovery, and tested restore procedures.
- Production dependency patching, vulnerability scanning, change control, and
  documented risk analysis.

These controls cannot be guaranteed by application code alone and must be
validated against the selected hosting provider and organization policy.

## Verification

The automated security coverage is in `tests/test_security.py`. The full
dependency, SAST, and privacy/data-flow scans should be rerun before
deployment. Manual scenarios are listed in `TESTING.md` under
“Security hardening.”