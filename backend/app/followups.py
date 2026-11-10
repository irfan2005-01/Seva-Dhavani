"""Idempotent reminder and escalation processor with an injectable clock."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .models import ActionLog, Authority, Complaint
from .services.notify import enqueue, localized_message

OPEN_STATUSES = ("Registered", "Assigned", "In Progress")


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def officer_last_action(db: Session, complaint: Complaint) -> datetime:
    value = db.scalar(
        select(ActionLog.created_at).where(
            ActionLog.complaint_id == complaint.id, ActionLog.actor.in_(("officer", "admin"))
        ).order_by(ActionLog.created_at.desc(), ActionLog.id.desc()).limit(1)
    )
    return as_utc(value or complaint.created_at)


def complaint_metrics(db: Session, complaint: Complaint, now: datetime) -> dict:
    now = as_utc(now)
    created = as_utc(complaint.created_at)
    due = as_utc(complaint.due_at) if complaint.due_at else None
    is_open = complaint.status not in ("Resolved", "Closed")
    hours_overdue = max(0.0, (now - due).total_seconds() / 3600) if due and is_open and now > due else 0.0
    return {
        "is_overdue": bool(hours_overdue),
        "hours_overdue": round(hours_overdue, 2),
        "age_hours": round(max(0.0, (now - created).total_seconds() / 3600), 2),
        "is_stale": is_open and (now - officer_last_action(db, complaint)).total_seconds() > config.STALE_AFTER_HOURS * 3600,
    }


def _send_level(db: Session, complaint: Complaint, authority: Authority, key: str, message_key: str, now: datetime) -> bool:
    message = localized_message(complaint.language, message_key)
    count = enqueue(db, complaint, role=authority.role, phone=authority.phone, message=message,
                    dedupe_key=f"complaint:{complaint.id}:{key}", now=now)
    if count:
        db.add(ActionLog(complaint_id=complaint.id, actor="system", action_type="reminder_sent",
                         note=f"{message_key} reminder sent to {authority.role}." if key.startswith("reminder") else f"Escalation reminder sent to {authority.role}."))
    # The job summary measures complaints receiving a reminder. `enqueue` may
    # create multiple delivery rows (in-app and SMS) for that single reminder.
    return count > 0


def run_followup_job(db: Session, now: datetime | None = None) -> dict[str, int]:
    """Process all eligible complaints once. Pass `now` from tests for deterministic behavior."""
    now = as_utc(now or datetime.now(timezone.utc))
    summary = {"due_soon": 0, "overdue": 0, "escalated": 0}
    complaints = db.scalars(select(Complaint).where(
        Complaint.is_emergency_flagged.is_(False), Complaint.status.in_(OPEN_STATUSES)
    )).all()
    for complaint in complaints:
        if not complaint.due_at:
            continue
        due = as_utc(complaint.due_at)
        overdue_hours = (now - due).total_seconds() / 3600
        authority = db.get(Authority, complaint.assigned_authority_id) if complaint.assigned_authority_id else None
        if not authority:
            continue
        if 0 <= -overdue_hours <= config.REMINDER_BEFORE_DUE_HOURS:
            summary["due_soon"] += int(_send_level(db, complaint, authority, "reminder:due_soon", "due_soon", now))
        if overdue_hours > 0:
            summary["overdue"] += int(_send_level(db, complaint, authority, "reminder:overdue", "overdue", now))
        if overdue_hours > config.ESCALATE_AFTER_OVERDUE_HOURS:
            escalation_due = config.ESCALATE_AFTER_OVERDUE_HOURS + complaint.escalation_level * config.ESCALATION_REPEAT_HOURS
            if overdue_hours > escalation_due:
                target = db.get(Authority, authority.escalation_to) if authority.escalation_to else None
                if target:
                    prior_role = authority.role
                    complaint.assigned_authority_id = target.id
                    complaint.escalation_level += 1
                    msg = localized_message(complaint.language, "escalated")
                    enqueue(db, complaint, role=target.role, phone=target.phone, message=msg,
                            dedupe_key=f"complaint:{complaint.id}:escalation:{complaint.escalation_level}:to:{target.id}", now=now)
                    db.add(ActionLog(complaint_id=complaint.id, actor="system", action_type="escalated",
                                     note=f"Escalated from {prior_role} to {target.role} (level {complaint.escalation_level})."))
                    summary["escalated"] += 1
    db.commit()
    return summary
