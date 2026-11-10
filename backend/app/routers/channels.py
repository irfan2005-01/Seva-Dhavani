"""No-smartphone channel simulations and callback inbox endpoints."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from ..auth import require_role
from ..database import get_db
from ..models import CallbackRequest, Complaint, Hospital, Notification
from ..services.ivr import ivr_provider

router = APIRouter(tags=["no-smartphone channels"])


class IvrInput(BaseModel):
    digit: str | None = Field(default=None, max_length=1)
    digits: str | None = Field(default=None, max_length=10)
    speech: str | None = Field(default=None, max_length=5000)


class MissedCallInput(BaseModel):
    phone: str = Field(min_length=7, max_length=24)
    hospital_id: int | None = Field(default=None, gt=0)


class SmsInboxInput(BaseModel):
    phone: str = Field(min_length=7, max_length=24)


def _digits(phone: str) -> str:
    return "".join(ch for ch in phone if ch.isdigit())


def _mask_phone(phone: str) -> str:
    digits = _digits(phone)
    if len(digits) < 5:
        return "X" * len(digits)
    return digits[:2] + "X" * (len(digits) - 4) + digits[-2:]


@router.get("/api/demo/status")
def demo_status():
    return {"demo_mode": config.DEMO_MODE}


@router.post("/api/ivr/session")
async def start_ivr_session(db: Session = Depends(get_db)):
    return await ivr_provider.start(db)


@router.post("/api/ivr/session/{session_id}/input")
async def input_ivr_session(session_id: str, payload: IvrInput, db: Session = Depends(get_db)):
    try:
        return await ivr_provider.input(
            db, session_id, digit=payload.digit, digits=payload.digits, speech=payload.speech
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'")) from exc


@router.post("/api/ivr/missed-call", status_code=201)
def missed_call(payload: MissedCallInput, db: Session = Depends(get_db)):
    phone_digits = _digits(payload.phone)
    if not 7 <= len(phone_digits) <= 15:
        raise HTTPException(status_code=422, detail="Enter a valid phone number")
    if payload.hospital_id is not None and db.get(Hospital, payload.hospital_id) is None:
        raise HTTPException(status_code=404, detail="Hospital not found")
    request = CallbackRequest(phone_masked=_mask_phone(payload.phone), status="Requested",
                              created_at=datetime.now(timezone.utc))
    db.add(request)
    db.commit()
    db.refresh(request)
    return {"id": request.id, "phone_masked": request.phone_masked,
            "status": request.status, "created_at": request.created_at}


@router.post("/api/sms/inbox")
def sms_inbox(payload: SmsInboxInput, db: Session = Depends(get_db)):
    """Read-only phone inbox lookup; phone stays in the request body, not URL or logs."""
    if not config.DEMO_MODE:
        raise HTTPException(status_code=404, detail="Phone inbox simulation is available only in demo mode")
    phone_digits = _digits(payload.phone)
    if not 7 <= len(phone_digits) <= 15:
        raise HTTPException(status_code=422, detail="Enter a valid phone number")
    rows = db.execute(
        select(Notification, Complaint.complaint_id)
        .join(Complaint, Complaint.id == Notification.complaint_id)
        .where(Notification.channel == "sms")
        .order_by(Notification.created_at.desc(), Notification.id.desc())
    ).all()
    messages = [{
        "id": notification.id,
        "complaint_id": complaint_id,
        "message": notification.message,
        "created_at": notification.created_at,
    } for notification, complaint_id in rows if _digits(notification.recipient_phone or "") == phone_digits]
    return {"messages": messages}


@router.get("/api/callbacks")
def list_callbacks(db: Session = Depends(get_db), role: str = Depends(require_role)):
    del role
    rows = db.scalars(select(CallbackRequest).order_by(CallbackRequest.created_at.desc(), CallbackRequest.id.desc())).all()
    return [{"id": item.id, "phone_masked": item.phone_masked, "status": item.status,
             "created_at": item.created_at} for item in rows]


@router.patch("/api/callbacks/{callback_id}")
def mark_callback_called_back(
    callback_id: int,
    db: Session = Depends(get_db),
    role: str = Depends(require_role),
):
    del role
    request = db.get(CallbackRequest, callback_id)
    if request is None:
        raise HTTPException(status_code=404, detail="Callback request not found")
    request.status = "Called back"
    db.commit()
    return {"id": request.id, "phone_masked": request.phone_masked,
            "status": request.status, "created_at": request.created_at}
