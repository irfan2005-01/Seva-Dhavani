"""Officer endpoints for follow-up queues, notification outbox, and demo clock shifts."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from ..auth import require_role
from ..database import get_db
from ..followups import complaint_metrics, run_followup_job
from ..models import Complaint, Notification
from ..schemas import ComplaintListItem, NotificationItem, NotificationPage

router = APIRouter(tags=["follow-ups"])


def _item(db: Session, complaint: Complaint, now: datetime) -> dict:
    values = ComplaintListItem.model_validate(complaint).model_dump()
    values.update(complaint_metrics(db, complaint, now))
    return ComplaintListItem.model_validate(values).model_dump(mode="json")


@router.get("/api/followups")
def followups(db: Session = Depends(get_db), role: str = Depends(require_role)):
    del role
    now = datetime.now(timezone.utc)
    rows = db.scalars(select(Complaint).where(
        Complaint.is_emergency_flagged.is_(False), Complaint.status.not_in(("Resolved", "Closed"))
    ).order_by(Complaint.created_at)).all()
    result = {"due_soon": [], "overdue": [], "escalated": [], "stale": []}
    for complaint in rows:
        metrics = complaint_metrics(db, complaint, now)
        item = _item(db, complaint, now)
        due = complaint.due_at
        if due and due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
        if due and not metrics["is_overdue"] and (due - now).total_seconds() <= config.REMINDER_BEFORE_DUE_HOURS * 3600:
            result["due_soon"].append(item)
        if metrics["is_overdue"]:
            result["overdue"].append(item)
        if complaint.escalation_level:
            result["escalated"].append(item)
        if metrics["is_stale"]:
            result["stale"].append(item)
    return result


@router.get("/api/notifications", response_model=NotificationPage)
def notifications(complaint_id: str | None = None, db: Session = Depends(get_db), role: str = Depends(require_role)):
    del role
    query = select(Notification, Complaint.complaint_id).join(Complaint, Complaint.id == Notification.complaint_id)
    if complaint_id:
        query = query.where(Complaint.complaint_id == complaint_id)
    rows = db.execute(query.order_by(Notification.created_at.desc(), Notification.id.desc())).all()
    return NotificationPage(items=[NotificationItem(
        id=n.id, complaint_id=public_id, recipient_role=n.recipient_role,
        recipient_phone=n.recipient_phone, channel=n.channel, message=n.message,
        status=n.status, created_at=n.created_at,
    ) for n, public_id in rows])


@router.post("/api/followups/run")
def run_now(db: Session = Depends(get_db), role: str = Depends(require_role)):
    del role
    return run_followup_job(db, datetime.now(timezone.utc))


@router.post("/api/demo/backdate/{complaint_id}")
def backdate(
    complaint_id: str,
    hours: float = Query(gt=0, le=8760),
    db: Session = Depends(get_db),
    role: str = Depends(require_role),
):
    del role
    if not config.DEMO_MODE:
        raise HTTPException(status_code=404, detail="Demo backdating is disabled")
    complaint = db.scalar(select(Complaint).where(
        Complaint.complaint_id == complaint_id, Complaint.is_emergency_flagged.is_(False)
    ))
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")
    delta = timedelta(hours=hours)
    complaint.created_at -= delta
    if complaint.due_at:
        complaint.due_at -= delta
    db.commit()
    return {"complaint_id": complaint.complaint_id, "shifted_back_hours": hours,
            "created_at": complaint.created_at, "due_at": complaint.due_at}
