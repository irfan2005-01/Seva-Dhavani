"""Provider contracts for SMS and IVR edges; current adapters are offline simulations."""
from datetime import datetime
from typing import Protocol

from sqlalchemy.orm import Session

from ..models import Complaint


class SmsProvider(Protocol):
    def send(self, db: Session, complaint: Complaint, phone: str, message: str,
             dedupe_key: str, now: datetime) -> int: ...


class IvrProvider(Protocol):
    async def start(self, db: Session) -> dict: ...
    async def input(self, db: Session, session_id: str, *, digit: str | None = None,
                    digits: str | None = None, speech: str | None = None) -> dict: ...
