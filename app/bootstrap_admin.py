"""Create the first clinic administrator for a local deployment.

This module intentionally provides a small, explicit bootstrap path instead of
adding an unauthenticated account-creation route to the application.
"""

from __future__ import annotations

import argparse
from getpass import getpass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Clinic, User, UserRole
from app.services.auth import create_user
from app.services.licensing import ensure_license


def _parser() -> argparse.ArgumentParser:
    """Build the command-line parser for the bootstrap command."""

    parser = argparse.ArgumentParser(
        description="Create the first clinic administrator account.",
    )
    parser.add_argument(
        "--email",
        required=True,
        help="Email address used to sign in.",
    )
    parser.add_argument(
        "--full-name",
        default="Clinic Administrator",
        help="Display name for the administrator.",
    )
    parser.add_argument(
        "--clinic-id",
        type=int,
        help="Existing clinic ID. Required when multiple clinics exist.",
    )
    parser.add_argument(
        "--clinic-name",
        default="OB/GYN Clinic",
        help="Name for a new clinic when no clinic exists.",
    )
    parser.add_argument(
        "--password",
        help=(
            "Password for non-interactive use. Omit this option to enter it "
            "securely at the prompt."
        ),
    )
    return parser


def _read_password(provided_password: str | None) -> str:
    """Read and confirm a password without echoing it to the terminal."""

    if provided_password is not None:
        return provided_password
    password = getpass("New administrator password: ")
    confirmation = getpass("Confirm administrator password: ")
    if password != confirmation:
        raise ValueError("The password entries do not match.")
    return password


def _select_clinic(
    db: Session,
    clinic_id: int | None,
    clinic_name: str,
) -> Clinic:
    """Select an explicit clinic or create the first clinic tenant."""

    if clinic_id is not None:
        clinic = db.get(Clinic, clinic_id)
        if clinic is None:
            raise ValueError(f"Clinic {clinic_id} does not exist.")
        return clinic

    clinics = db.scalars(select(Clinic).order_by(Clinic.id)).all()
    if len(clinics) > 1:
        raise ValueError(
            "Multiple clinics exist; rerun with --clinic-id to choose one."
        )
    if clinics:
        return clinics[0]

    clinic = Clinic(name=clinic_name)
    db.add(clinic)
    db.flush()
    ensure_license(db, clinic.id)
    return clinic


def bootstrap_admin(
    *,
    email: str,
    password: str,
    full_name: str = "Clinic Administrator",
    clinic_id: int | None = None,
    clinic_name: str = "OB/GYN Clinic",
) -> tuple[User, Clinic]:
    """Create one clinic-admin account and return it with its clinic.

    Raises:
        ValueError: If the email already exists, the clinic selection is
            ambiguous, or the password fails the application policy.
    """

    normalized_email = email.strip().lower()
    if not normalized_email:
        raise ValueError("Email is required.")

    with SessionLocal() as db:
        existing_user = db.scalar(
            select(User)
            .execution_options(include_deleted=True)
            .where(User.email == normalized_email)
        )
        if existing_user is not None:
            raise ValueError(
                f"An account already exists for {normalized_email}; "
                "this command never overwrites existing credentials."
            )

        clinic = _select_clinic(db, clinic_id, clinic_name)
        user = create_user(
            db=db,
            clinic_id=clinic.id,
            email=normalized_email,
            password=password,
            full_name=full_name.strip() or "Clinic Administrator",
            role=UserRole.CLINIC_ADMIN,
        )
        db.commit()
        db.refresh(user)
        db.refresh(clinic)
        return user, clinic


def main() -> int:
    """Run the command-line bootstrap flow."""

    args = _parser().parse_args()
    try:
        password = _read_password(args.password)
        user, clinic = bootstrap_admin(
            email=args.email,
            password=password,
            full_name=args.full_name,
            clinic_id=args.clinic_id,
            clinic_name=args.clinic_name,
        )
    except (ValueError, OSError) as exc:
        _parser().error(str(exc))
    print(
        f"Created clinic administrator {user.email} for clinic "
        f"{clinic.name!r} (clinic_id={clinic.id})."
    )
    print("Use the password entered during setup to sign in at /login.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())