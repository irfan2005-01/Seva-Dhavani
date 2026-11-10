"""Database schema for non-emergency hospital service complaints."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Hospital(Base):
    __tablename__ = "hospitals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    district: Mapped[str] = mapped_column(String(100), nullable=False)
    taluk: Mapped[str] = mapped_column(String(100), nullable=False)

    authorities: Mapped[list["Authority"]] = relationship(back_populates="hospital", cascade="all, delete-orphan")
    complaints: Mapped[list["Complaint"]] = relationship(back_populates="hospital")


class Authority(Base):
    __tablename__ = "authorities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hospital_id: Mapped[int] = mapped_column(ForeignKey("hospitals.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    category_handled: Mapped[str] = mapped_column(String(120), nullable=False)
    escalation_to: Mapped[int | None] = mapped_column(ForeignKey("authorities.id"), nullable=True)

    hospital: Mapped["Hospital"] = relationship(back_populates="authorities")
    escalation_authority: Mapped["Authority | None"] = relationship(remote_side="Authority.id", back_populates="escalated_from")
    escalated_from: Mapped[list["Authority"]] = relationship(back_populates="escalation_authority")


class Complaint(Base):
    __tablename__ = "complaints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    complaint_id: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    hospital_id: Mapped[int] = mapped_column(ForeignKey("hospitals.id"), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(2), nullable=False, default="kn")
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default="assisted")
    complainant_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="Registered")
    priority: Mapped[str] = mapped_column(String(30), nullable=False, default="Normal")
    assigned_authority_id: Mapped[int | None] = mapped_column(ForeignKey("authorities.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_emergency_flagged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    transcript_original: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_english: Mapped[str | None] = mapped_column(Text, nullable=True)
    escalation_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    hospital: Mapped["Hospital"] = relationship(back_populates="complaints")
    assigned_authority: Mapped["Authority | None"] = relationship(foreign_keys=[assigned_authority_id])
    action_logs: Mapped[list["ActionLog"]] = relationship(back_populates="complaint", cascade="all, delete-orphan")


class ActionLog(Base):
    __tablename__ = "action_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    complaint_id: Mapped[int] = mapped_column(ForeignKey("complaints.id"), nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String(30), nullable=False)
    action_type: Mapped[str] = mapped_column(String(30), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    complaint: Mapped["Complaint"] = relationship(back_populates="action_logs")


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    complaint_id: Mapped[int] = mapped_column(ForeignKey("complaints.id"), nullable=False, index=True)
    recipient_role: Mapped[str] = mapped_column(String(120), nullable=False)
    recipient_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    channel: Mapped[str] = mapped_column(String(10), nullable=False, default="inapp")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    dedupe_key: Mapped[str] = mapped_column(String(180), nullable=False, unique=True)


class CallbackRequest(Base):
    __tablename__ = "callback_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    phone_masked: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="Requested")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class IvrSession(Base):
    __tablename__ = "ivr_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    state: Mapped[str] = mapped_column(String(40), nullable=False, default="menu")
    language: Mapped[str] = mapped_column(String(2), nullable=False, default="kn")
    hospital_id: Mapped[int | None] = mapped_column(ForeignKey("hospitals.id"), nullable=True)
    complaint_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    pending_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    digit_buffer: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
