"""Complaint registration, tracking, and officer operations."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import require_role
from ..categorizer import classify_complaint
from ..complaint_ids import generate_complaint_id
from .. import config
from ..config import CATEGORY_CONFIG, COMPLAINT_STATUSES
from ..database import get_db
from ..models import ActionLog, Authority, Complaint, Hospital, Notification
from ..followups import complaint_metrics, run_followup_job
from ..services.notify import enqueue, localized_message
from ..schemas import (
    ActionLogItem, AssistedComplaintCreate, ComplaintCreate, ComplaintCreated, ComplaintHistory,
    ComplaintListItem, ComplaintPage, ComplaintUpdate, PublicComplaintStatus,
    NotificationItem, NotificationPage,
)

router = APIRouter(prefix="/api/complaints", tags=["complaints"])

ACKNOWLEDGEMENTS = {
    "en": "Your complaint has been registered and assigned.",
    "kn": "ನಿಮ್ಮ ದೂರು ನೋಂದಾಯಿಸಿ ಸಂಬಂಧಿತ ಅಧಿಕಾರಿಗೆ ನೀಡಲಾಗಿದೆ.",
    "hi": "आपकी शिकायत दर्ज करके संबंधित अधिकारी को भेज दी गई है।",
}
EMERGENCY_MESSAGES = {
    "en": "This may be an emergency. Immediately contact hospital staff or call 108. No routine complaint was registered.",
    "kn": "ಇದು ತುರ್ತು ಪರಿಸ್ಥಿತಿಯಾಗಿರಬಹುದು. ತಕ್ಷಣ ಆಸ್ಪತ್ರೆ ಸಿಬ್ಬಂದಿಯನ್ನು ಸಂಪರ್ಕಿಸಿ ಅಥವಾ 108ಕ್ಕೆ ಕರೆ ಮಾಡಿ. ಸಾಮಾನ್ಯ ದೂರು ದಾಖಲಿಸಲಾಗಿಲ್ಲ.",
    "hi": "यह आपात स्थिति हो सकती है। तुरंत अस्पताल के कर्मचारियों से संपर्क करें या 108 पर कॉल करें। सामान्य शिकायत दर्ज नहीं की गई।",
}


from ..messages import ACKNOWLEDGEMENTS, EMERGENCY_MESSAGES


@router.post("", response_model=ComplaintCreated, status_code=status.HTTP_201_CREATED)
async def create_complaint(payload: ComplaintCreate, db: Session = Depends(get_db)):
    hospital = db.get(Hospital, payload.hospital_id)
    if hospital is None:
        raise HTTPException(status_code=404, detail="Hospital not found")

    now = datetime.now(timezone.utc)
    classification = await classify_complaint(payload.description)
    if classification["is_emergency"]:
        # Persist only the emergency flag and redirect audit record; it is excluded
        # from the normal queue and never receives a routine complaint reference.
        flag = Complaint(
            complaint_id=f"EMG-{now.strftime('%y%m%d%H%M%S%f')[-16:]}",
            hospital_id=payload.hospital_id,
            category="Other",
            description=payload.description,
            language=payload.language,
            channel=payload.channel,
            complainant_phone=payload.complainant_phone,
            status="Emergency Redirected",
            priority="Emergency",
            is_emergency_flagged=True,
            transcript_original=payload.transcript_original,
            summary_english=str(classification["summary_english"]),
        )
        db.add(flag)
        db.flush()
        audit_note = "Emergency detected; caller directed to hospital staff or 108."
        if payload.registered_by:
            audit_note += f" Operator reference: {payload.registered_by.strip()}."
        db.add(ActionLog(complaint_id=flag.id, actor="system", action_type="emergency_flagged", note=audit_note))
        db.commit()
        return ComplaintCreated(emergency=True, message=EMERGENCY_MESSAGES[payload.language])

    category = str(classification["category"])
    role = CATEGORY_CONFIG[category].default_authority_role
    authority = db.scalar(
        select(Authority).where(
            Authority.hospital_id == payload.hospital_id,
            Authority.role == role,
        ).order_by(Authority.id)
    )
    if authority is None:
        raise HTTPException(status_code=409, detail=f"No authority configured for category {category}")

    complaint = Complaint(
        complaint_id=generate_complaint_id(db),
        hospital_id=payload.hospital_id,
        category=category,
        description=payload.description,
        language=payload.language,
        channel=payload.channel,
        complainant_phone=payload.complainant_phone,
        status="Assigned",
        priority=str(classification["priority"]),
        assigned_authority_id=authority.id,
        created_at=now,
        due_at=now + timedelta(hours=CATEGORY_CONFIG[category].sla_hours),
        transcript_original=payload.transcript_original,
        summary_english=str(classification["summary_english"]),
    )
    db.add(complaint)
    db.flush()
    db.add_all([
        ActionLog(complaint_id=complaint.id, actor="system", action_type="registered",
                  note="Complaint registered." + (f" Operator reference: {payload.registered_by.strip()}." if payload.registered_by else "")),
        ActionLog(complaint_id=complaint.id, actor="system", action_type="assigned", note=f"Assigned to {authority.role}."),
    ])
    if complaint.complainant_phone:
        enqueue(db, complaint, role="Complainant", phone=complaint.complainant_phone,
                message=f"{localized_message(complaint.language, 'acknowledged')} ID {complaint.complaint_id}.",
                dedupe_key=f"complaint:{complaint.id}:complainant:acknowledged", now=now)
    db.commit()
    return ComplaintCreated(
        complaint_id=complaint.complaint_id,
        category=category,
        assigned_role=authority.role,
        due_at=complaint.due_at,
        message=ACKNOWLEDGEMENTS[payload.language],
    )


@router.post("/assisted", response_model=ComplaintCreated, status_code=status.HTTP_201_CREATED)
async def create_assisted_complaint(payload: AssistedComplaintCreate, db: Session = Depends(get_db)):
    return await create_complaint(payload, db)


def _officer_item(db: Session, complaint: Complaint, now: datetime | None = None) -> ComplaintListItem:
    data = ComplaintListItem.model_validate(complaint).model_dump()
    hospital = db.get(Hospital, complaint.hospital_id)
    authority = db.get(Authority, complaint.assigned_authority_id) if complaint.assigned_authority_id else None
    data["hospital_name"] = hospital.name if hospital else ""
    data["assigned_role"] = authority.role if authority else None
    data.update(complaint_metrics(db, complaint, now or datetime.now(timezone.utc)))
    return ComplaintListItem.model_validate(data)


@router.get("/followups", tags=["follow-ups"])
def get_followups(db: Session = Depends(get_db), role: str = Depends(require_role)):
    del role
    now = datetime.now(timezone.utc)
    rows = db.scalars(select(Complaint).where(
        Complaint.is_emergency_flagged.is_(False), Complaint.status.not_in(("Resolved", "Closed"))
    ).order_by(Complaint.created_at)).all()
    groups = {"due_soon": [], "overdue": [], "escalated": [], "stale": []}
    for row in rows:
        metrics = complaint_metrics(db, row, now)
        item = _officer_item(db, row, now).model_dump(mode="json")
        due = row.due_at.replace(tzinfo=timezone.utc) if row.due_at and row.due_at.tzinfo is None else row.due_at
        if due and not metrics["is_overdue"] and (due - now).total_seconds() <= config.REMINDER_BEFORE_DUE_HOURS * 3600:
            groups["due_soon"].append(item)
        if metrics["is_overdue"]:
            groups["overdue"].append(item)
        if row.escalation_level > 0:
            groups["escalated"].append(item)
        if metrics["is_stale"]:
            groups["stale"].append(item)
    return groups


@router.get("/notifications", response_model=NotificationPage, tags=["follow-ups"])
def get_notifications(
    complaint_id: str | None = None,
    db: Session = Depends(get_db),
    role: str = Depends(require_role),
):
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


@router.post("/followups/run", tags=["follow-ups"])
def trigger_followup_job(db: Session = Depends(get_db), role: str = Depends(require_role)):
    del role
    return run_followup_job(db, datetime.now(timezone.utc))


@router.post("/demo/backdate/{complaint_id}", tags=["demo"])
def backdate_complaint(
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
    if complaint is None:
        raise HTTPException(status_code=404, detail="Complaint not found")
    shift = timedelta(hours=hours)
    complaint.created_at = complaint.created_at - shift
    if complaint.due_at:
        complaint.due_at = complaint.due_at - shift
    db.commit()
    return {"complaint_id": complaint.complaint_id, "shifted_back_hours": hours,
            "created_at": complaint.created_at, "due_at": complaint.due_at}


@router.get("/{complaint_id}", response_model=PublicComplaintStatus)
def get_public_status(complaint_id: str, db: Session = Depends(get_db)):
    complaint = db.scalar(select(Complaint).where(Complaint.complaint_id == complaint_id))
    if complaint is None or complaint.is_emergency_flagged:
        raise HTTPException(status_code=404, detail="Complaint not found")
    hospital = db.get(Hospital, complaint.hospital_id)
    latest = db.scalar(
        select(ActionLog).where(ActionLog.complaint_id == complaint.id)
        .order_by(ActionLog.created_at.desc(), ActionLog.id.desc())
    )
    return PublicComplaintStatus(
        complaint_id=complaint.complaint_id,
        status=complaint.status,
        category=complaint.category,
        hospital=hospital.name if hospital else "",
        latest_action_note=latest.note if latest else None,
        created_at=complaint.created_at,
        due_at=complaint.due_at,
        resolved_at=complaint.resolved_at,
    )


@router.get("", response_model=ComplaintPage)
def list_complaints(
    hospital_id: int | None = None,
    complaint_status: str | None = Query(default=None, alias="status"),
    category: str | None = None,
    search: str | None = Query(default=None, max_length=40),
    overdue: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    role: str = Depends(require_role),
):
    del role
    query = select(Complaint).where(Complaint.is_emergency_flagged.is_(False))
    if hospital_id is not None:
        query = query.where(Complaint.hospital_id == hospital_id)
    if complaint_status is not None:
        if complaint_status not in COMPLAINT_STATUSES:
            raise HTTPException(status_code=422, detail="Invalid status filter")
        query = query.where(Complaint.status == complaint_status)
    if category is not None:
        if category not in CATEGORY_CONFIG:
            raise HTTPException(status_code=422, detail="Invalid category filter")
        query = query.where(Complaint.category == category)
    if search and search.strip():
        query = query.where(Complaint.complaint_id.ilike(f"%{search.strip()}%"))
    if overdue:
        query = query.where(Complaint.due_at < datetime.now(timezone.utc), Complaint.status.not_in(("Resolved", "Closed")))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(Complaint.created_at.desc(), Complaint.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return ComplaintPage(items=[_officer_item(db, row) for row in rows], total=total, page=page, page_size=page_size)


@router.patch("/{complaint_id}", response_model=PublicComplaintStatus)
def update_complaint(
    complaint_id: str,
    payload: ComplaintUpdate,
    db: Session = Depends(get_db),
    role: str = Depends(require_role),
):
    complaint = db.scalar(select(Complaint).where(Complaint.complaint_id == complaint_id))
    if complaint is None or complaint.is_emergency_flagged:
        raise HTTPException(status_code=404, detail="Complaint not found")
    transitions = {"Assigned": "In Progress", "In Progress": "Resolved", "Resolved": "Closed"}
    if transitions.get(complaint.status) != payload.status:
        raise HTTPException(status_code=409, detail=f"Invalid status transition from {complaint.status} to {payload.status}")
    if payload.status == "Resolved" and not (payload.action_note and payload.action_note.strip()):
        raise HTTPException(status_code=422, detail="A non-empty action_note is required to resolve a complaint")
    if payload.status == "Closed" and role != "admin":
        raise HTTPException(status_code=403, detail="Only an admin can close complaints")
    complaint.status = payload.status
    if payload.status == "Resolved":
        complaint.resolved_at = datetime.now(timezone.utc)
    db.add(ActionLog(
        complaint_id=complaint.id,
        actor="officer",
        action_type="status_update",
        note=payload.action_note.strip() if payload.action_note and payload.action_note.strip() else f"Status changed to {payload.status}.",
    ))
    if complaint.complainant_phone:
        notice_key = {"In Progress": "in_progress", "Resolved": "resolved", "Closed": "closed"}[payload.status]
        enqueue(db, complaint, role="Complainant", phone=complaint.complainant_phone,
                message=f"{localized_message(complaint.language, notice_key)} ID {complaint.complaint_id}.",
                dedupe_key=f"complaint:{complaint.id}:complainant:{notice_key}",
                now=datetime.now(timezone.utc))
    db.commit()
    return get_public_status(complaint_id, db)


@router.get("/{complaint_id}/history", response_model=ComplaintHistory)
def get_complaint_history(
    complaint_id: str,
    db: Session = Depends(get_db),
    role: str = Depends(require_role),
):
    del role
    complaint = db.scalar(select(Complaint).where(Complaint.complaint_id == complaint_id, Complaint.is_emergency_flagged.is_(False)))
    if complaint is None:
        raise HTTPException(status_code=404, detail="Complaint not found")
    logs = db.scalars(select(ActionLog).where(ActionLog.complaint_id == complaint.id).order_by(ActionLog.created_at, ActionLog.id)).all()
    return ComplaintHistory(complaint_id=complaint_id, items=[ActionLogItem.model_validate(item) for item in logs])


@router.get("/{complaint_id}/officer-detail")
def get_officer_detail(
    complaint_id: str,
    db: Session = Depends(get_db),
    role: str = Depends(require_role),
):
    del role
    complaint = db.scalar(select(Complaint).where(
        Complaint.complaint_id == complaint_id, Complaint.is_emergency_flagged.is_(False)
    ))
    if complaint is None:
        raise HTTPException(status_code=404, detail="Complaint not found")
    phone = complaint.complainant_phone
    masked_phone = None
    if phone:
        digits = "".join(character for character in phone if character.isdigit())
        masked_phone = (digits[:2] + "X" * max(0, len(digits) - 4) + digits[-2:]) if len(digits) > 4 else "X" * len(digits)
    authority = db.get(Authority, complaint.assigned_authority_id) if complaint.assigned_authority_id else None
    logs = db.scalars(select(ActionLog).where(ActionLog.complaint_id == complaint.id)
                      .order_by(ActionLog.created_at, ActionLog.id)).all()
    return {
        "complaint_id": complaint.complaint_id,
        "description": complaint.description,
        "transcript_original": complaint.transcript_original,
        "summary_english": complaint.summary_english,
        "complainant_phone_masked": masked_phone,
        "assigned_role": authority.role if authority else None,
        "history": [ActionLogItem.model_validate(item).model_dump(mode="json") for item in logs],
    }
