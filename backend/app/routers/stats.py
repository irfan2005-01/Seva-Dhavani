"""Officer-only dashboard metrics."""
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from ..auth import require_role
from ..database import get_db
from ..followups import as_utc
from ..models import Complaint, Hospital

router = APIRouter(tags=["dashboard"])


@router.get("/api/stats")
def get_stats(
    hospital_id: int | None = Query(default=None, gt=0),
    start_date: date | None = None,
    end_date: date | None = None,
    db: Session = Depends(get_db),
    role: str = Depends(require_role),
):
    del role
    now = datetime.now(timezone.utc)
    query = select(Complaint).where(Complaint.is_emergency_flagged.is_(False))
    if hospital_id is not None:
        query = query.where(Complaint.hospital_id == hospital_id)
    if start_date is not None:
        query = query.where(Complaint.created_at >= datetime.combine(start_date, time.min, timezone.utc))
    if end_date is not None:
        query = query.where(Complaint.created_at < datetime.combine(end_date + timedelta(days=1), time.min, timezone.utc))
    rows = db.scalars(query).all()
    status_counts = Counter(row.status for row in rows)
    category_counts = Counter(row.category for row in rows)
    hospital_ids = {row.hospital_id for row in rows}
    hospitals = db.scalars(select(Hospital).where(Hospital.id.in_(hospital_ids))).all() if hospital_ids else []
    hospital_names = {hospital.id: hospital.name for hospital in hospitals}
    hospital_counts = Counter(row.hospital_id for row in rows)

    resolved = [row for row in rows if row.status in ("Resolved", "Closed") and row.resolved_at]
    resolution_hours = [max(0.0, (as_utc(row.resolved_at) - as_utc(row.created_at)).total_seconds() / 3600) for row in resolved]
    within_sla = [row for row in resolved if row.due_at and as_utc(row.resolved_at) <= as_utc(row.due_at)]
    overdue_count = sum(
        1 for row in rows
        if row.status not in ("Resolved", "Closed") and row.due_at and as_utc(row.due_at) < now
    )
    escalated_count = sum(1 for row in rows if row.escalation_level > 0)

    today = now.date()
    trend_start = today - timedelta(days=13)
    trend_counts = Counter(
        as_utc(row.created_at).date().isoformat() for row in rows
        if trend_start <= as_utc(row.created_at).date() <= today
    )
    complaints_per_day = [
        {"date": (trend_start + timedelta(days=offset)).isoformat(), "count": trend_counts[(trend_start + timedelta(days=offset)).isoformat()]}
        for offset in range(14)
    ]

    # Recurrence is always evaluated over a rolling seven-day window; a selected
    # hospital narrows the result, while date range filters the other metrics.
    recurrence_query = select(Complaint).where(
        Complaint.is_emergency_flagged.is_(False),
        Complaint.created_at >= now - timedelta(days=7),
    )
    if hospital_id is not None:
        recurrence_query = recurrence_query.where(Complaint.hospital_id == hospital_id)
    recent = db.scalars(recurrence_query).all()
    recurring_counts = Counter((row.hospital_id, row.category) for row in recent)
    recent_hospital_ids = {hid for hid, _category in recurring_counts}
    recent_hospitals = db.scalars(select(Hospital).where(Hospital.id.in_(recent_hospital_ids))).all() if recent_hospital_ids else []
    recent_hospital_names = {hospital.id: hospital.name for hospital in recent_hospitals}
    recurring_issues = [
        {"hospital_id": hid, "hospital": recent_hospital_names.get(hid, ""),
         "category": category, "count": count}
        for (hid, category), count in sorted(recurring_counts.items()) if count >= 3
    ]

    return {
        "total": len(rows),
        "totals_by_status": {key: status_counts.get(key, 0) for key in config.COMPLAINT_STATUSES},
        "totals_by_category": [{"category": key, "count": category_counts.get(key, 0)} for key in config.CATEGORIES],
        "totals_by_hospital": [
            {"hospital_id": hid, "hospital": hospital_names.get(hid, ""), "count": count}
            for hid, count in sorted(hospital_counts.items())
        ],
        "overdue_count": overdue_count,
        "escalated_count": escalated_count,
        "average_resolution_hours": round(sum(resolution_hours) / len(resolution_hours), 2) if resolution_hours else None,
        "resolved_within_sla_percent": round(100 * len(within_sla) / len(resolved), 2) if resolved else None,
        "complaints_per_day": complaints_per_day,
        "recurring_issues": recurring_issues,
        "demo_mode": config.DEMO_MODE,
    }
