"""Request and response schemas for the complaint API."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .config import CATEGORIES


class ComplaintCreate(BaseModel):
    description: str = Field(min_length=1, max_length=5000)
    language: Literal["kn", "en", "hi"]
    hospital_id: int = Field(gt=0)
    channel: Literal["voice", "assisted", "web", "ivr"]
    complainant_phone: str | None = Field(default=None, max_length=30)
    transcript_original: str | None = Field(default=None, max_length=5000)
    registered_by: str | None = Field(default=None, min_length=1, max_length=120)


class AssistedComplaintCreate(ComplaintCreate):
    channel: Literal["assisted"] = "assisted"
    registered_by: str = Field(min_length=1, max_length=120)


class ComplaintCreated(BaseModel):
    emergency: bool = False
    complaint_id: str | None = None
    category: str | None = None
    assigned_role: str | None = None
    due_at: datetime | None = None
    message: str


class PublicComplaintStatus(BaseModel):
    complaint_id: str
    status: str
    category: str
    hospital: str
    latest_action_note: str | None
    created_at: datetime
    due_at: datetime | None
    resolved_at: datetime | None


class ComplaintListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    complaint_id: str
    hospital_id: int
    hospital_name: str = ""
    assigned_role: str | None = None
    category: str
    description: str
    status: str
    priority: str
    created_at: datetime
    due_at: datetime | None
    resolved_at: datetime | None
    assigned_authority_id: int | None
    is_emergency_flagged: bool
    summary_english: str | None = None
    is_overdue: bool = False
    hours_overdue: float = 0
    age_hours: float = 0
    is_stale: bool = False
    escalation_level: int = 0


class NotificationItem(BaseModel):
    id: int
    complaint_id: str
    recipient_role: str
    recipient_phone: str | None
    channel: str
    message: str
    status: str
    created_at: datetime


class NotificationPage(BaseModel):
    items: list[NotificationItem]


class ComplaintPage(BaseModel):
    items: list[ComplaintListItem]
    total: int
    page: int
    page_size: int


class ComplaintUpdate(BaseModel):
    status: Literal["In Progress", "Resolved", "Closed"]
    action_note: str | None = Field(default=None, max_length=3000)


class ActionLogItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    actor: str
    action_type: str
    note: str | None
    created_at: datetime


class ComplaintHistory(BaseModel):
    complaint_id: str
    items: list[ActionLogItem]


class HospitalOption(BaseModel):
    id: int
    name: str
    district: str
    taluk: str
