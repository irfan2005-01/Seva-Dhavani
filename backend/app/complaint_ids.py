"""Generate the next human-readable complaint reference for a calendar year."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Complaint


def generate_complaint_id(db: Session, year: int | None = None) -> str:
    """Return an ID such as SD-2026-00001 based on IDs already in the database.

    The unique database constraint remains the final guard against concurrent
    registrations selecting the same sequence number.
    """
    selected_year = year or date.today().year
    prefix = f"SD-{selected_year}-"
    existing = db.scalars(
        select(Complaint.complaint_id).where(Complaint.complaint_id.like(f"{prefix}%"))
    ).all()
    highest = max((int(value.rsplit("-", 1)[1]) for value in existing), default=0)
    return f"{prefix}{highest + 1:05d}"
