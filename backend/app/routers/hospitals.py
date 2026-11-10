"""Public hospital selector for the citizen frontend."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Hospital
from ..schemas import HospitalOption

router = APIRouter(prefix="/api/hospitals", tags=["hospitals"])


@router.get("", response_model=list[HospitalOption])
def list_hospitals(db: Session = Depends(get_db)):
    return db.scalars(select(Hospital).order_by(Hospital.district, Hospital.name)).all()
