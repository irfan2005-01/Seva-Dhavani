"""Idempotently seed the three demo hospitals and their authority chains."""

import argparse
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .config import CATEGORY_CONFIG, CATEGORIES
from .complaint_ids import generate_complaint_id
from .database import Base, SessionLocal, engine
from .models import ActionLog, Authority, CallbackRequest, Complaint, Hospital, Notification
from .services.notify import enqueue


HOSPITALS = (
    ("District Hospital Kalaburagi", "Kalaburagi", "Kalaburagi"),
    ("District Hospital Bidar", "Bidar", "Bidar"),
    ("Taluk Hospital Sedam", "Kalaburagi", "Sedam"),
)


def seed_database(db: Session) -> None:
    for name, district, taluk in HOSPITALS:
        hospital = db.scalar(select(Hospital).where(Hospital.name == name))
        if hospital is None:
            hospital = Hospital(name=name, district=district, taluk=taluk)
            db.add(hospital)
            db.flush()

        authorities = db.scalars(select(Authority).where(Authority.hospital_id == hospital.id)).all()
        if authorities:
            continue

        # One hospital-level role for each category, reporting to its superintendent.
        superintendent = Authority(
            hospital_id=hospital.id,
            role="Medical Superintendent",
            name=f"{hospital.name} Medical Superintendent",
            category_handled="Doctor/Staff Unavailable",
        )
        district_officer = Authority(
            hospital_id=hospital.id,
            role="District Health Officer",
            name=f"{district} District Health Officer",
            category_handled="Escalation",
        )
        db.add_all([superintendent, district_officer])
        db.flush()
        superintendent.escalation_to = district_officer.id

        for role in sorted({item.default_authority_role for item in CATEGORY_CONFIG.values()}):
            if role == "Medical Superintendent":
                continue
            db.add(
                Authority(
                    hospital_id=hospital.id,
                    role=role,
                    name=f"{hospital.name} {role}",
                    category_handled=next(category for category, cfg in CATEGORY_CONFIG.items() if cfg.default_authority_role == role),
                    escalation_to=superintendent.id,
                )
            )
    db.commit()


DEMO_TEXT = {
    "Doctor/Staff Unavailable": "[DEMO] Service counter was unattended during the posted hours.",
    "Medicine Unavailable": "[DEMO] The listed item was not available at the pharmacy counter.",
    "Cleanliness & Hygiene": "[DEMO] The waiting area needs routine cleaning.",
    "Drinking Water & Sanitation": "[DEMO] The public drinking water point needs attention.",
    "Beds & Facilities": "[DEMO] A ward facility needs inspection and repair.",
    "Infrastructure Maintenance": "[DEMO] A corridor light or fixture needs maintenance.",
    "Other": "[DEMO] A hospital service request needs follow-up.",
}


def seed_demo_authority_phones(db: Session) -> None:
    """Use reserved fictional 555-01xx numbers only in the curated demo reset."""
    demo_phones = {
        "Medical Superintendent": "+1-202-555-0110",
        "District Health Officer": "+1-202-555-0111",
        "Pharmacy Officer": "+1-202-555-0112",
        "Water & Sanitation Engineer": "+1-202-555-0113",
    }
    authorities = db.scalars(select(Authority).order_by(Authority.hospital_id, Authority.id)).all()
    for authority in authorities:
        if authority.role in demo_phones:
            authority.phone = demo_phones[authority.role]
    db.flush()


def seed_demo_data(db: Session, target_count: int = 25) -> int:
    """Add a curated 25-record dataset with a four-item recent water recurrence cluster."""
    hospitals = db.scalars(select(Hospital).order_by(Hospital.id)).all()
    if not hospitals:
        seed_database(db)
        hospitals = db.scalars(select(Hospital).order_by(Hospital.id)).all()
    existing = db.scalars(select(Complaint).where(Complaint.description.like("[DEMO]%")).order_by(Complaint.id)).all()
    if len(existing) >= target_count:
        return 0
    now = datetime.now(timezone.utc)
    statuses = (
        "Assigned", "In Progress", "Assigned", "Resolved", "In Progress",
        "Assigned", "Closed", "Assigned", "Assigned", "In Progress",
        "Assigned", "Closed", "Registered", "Resolved", "In Progress",
        "Assigned", "Closed", "Registered", "Resolved", "Assigned",
        "In Progress", "Closed", "Assigned", "Registered", "Assigned",
    )
    categories = list(CATEGORIES)
    fake_complainant_phones = {
        1: "+1-202-555-0101", 6: "+1-202-555-0102", 13: "+1-202-555-0103",
    }
    added = 0
    for i in range(len(existing), target_count):
        # Four drinking-water issues at the same hospital in six days trigger recurrence.
        if i < 4:
            hospital = next((item for item in hospitals if item.id == 1), hospitals[0])
            category = "Drinking Water & Sanitation"
            age_days = (6, 5, 4, 3)[i]
        else:
            hospital = hospitals[i % len(hospitals)]
            category = categories[(i - 4) % len(categories)]
            age_days = (i % 13) + 1
        # Two escalated records show both hops of the seeded chain.
        if i in (4, 8):
            category = "Medicine Unavailable"
        cfg = CATEGORY_CONFIG[category]
        authority = db.scalar(select(Authority).where(
            Authority.hospital_id == hospital.id, Authority.role == cfg.default_authority_role
        ).order_by(Authority.id))
        if authority is None:
            continue
        # Keep one fresh, open record ready for a live backdate demonstration.
        created = now - timedelta(hours=1) if i == 5 else now - timedelta(days=age_days, hours=i % 5)
        due = created + timedelta(hours=cfg.sla_hours)
        status_value = statuses[i % len(statuses)]
        resolved_at = None
        if status_value in ("Resolved", "Closed"):
            resolution_hours = max(1, cfg.sla_hours - 2) if i % 2 == 0 else cfg.sla_hours + 4
            resolved_at = created + timedelta(hours=resolution_hours)
        escalation_level = 0
        original_authority = authority
        if i == 4:
            escalation_level = 1
            authority = db.get(Authority, authority.escalation_to) or authority
        elif i == 8:
            escalation_level = 2
            supervisor = db.get(Authority, authority.escalation_to)
            if supervisor:
                authority = db.get(Authority, supervisor.escalation_to) or supervisor
        complaint = Complaint(
            complaint_id=generate_complaint_id(db), hospital_id=hospital.id, category=category,
            description=DEMO_TEXT[category], language="en", channel="assisted",
            complainant_phone=fake_complainant_phones.get(i),
            status=status_value, priority="high" if i % 7 == 0 else ("medium" if i % 3 == 0 else "low"),
            assigned_authority_id=authority.id, created_at=created, due_at=due, resolved_at=resolved_at,
            escalation_level=escalation_level, is_emergency_flagged=False,
        )
        db.add(complaint)
        db.flush()
        db.add_all([
            ActionLog(complaint_id=complaint.id, actor="system", action_type="registered",
                      note="Synthetic dashboard demonstration record.", created_at=created),
            ActionLog(complaint_id=complaint.id, actor="system", action_type="assigned",
                      note=f"Assigned to {authority.role}.", created_at=created + timedelta(minutes=1)),
        ])
        if status_value != "Assigned" and status_value != "Registered":
            db.add(ActionLog(complaint_id=complaint.id, actor="officer", action_type="status_update",
                             note=f"Demo action recorded; status is {status_value}.",
                             created_at=resolved_at or min(now, created + timedelta(hours=4))))
        if escalation_level:
            if escalation_level == 1:
                hops = [authority]
            else:
                supervisor = db.get(Authority, original_authority.escalation_to) if original_authority.escalation_to else None
                hops = [item for item in (supervisor, authority) if item]
            previous = original_authority
            for level, target in enumerate(hops, 1):
                db.add(ActionLog(complaint_id=complaint.id, actor="system", action_type="escalated",
                                 note=f"Demo escalation from {previous.role} to {target.role} (level {level}).",
                                 created_at=created + timedelta(hours=level)))
                previous = target
        if complaint.complainant_phone:
            enqueue(db, complaint, role="Complainant", phone=complaint.complainant_phone,
                    message=f"Demo: complaint ID {complaint.complaint_id} has been registered.",
                    dedupe_key=f"demo:complaint:{complaint.id}:ack", now=created)
        if i in (0, 4, 8):
            enqueue(db, complaint, role=authority.role, phone=authority.phone,
                    message="Demo reminder: a hospital service complaint needs attention.",
                    dedupe_key=f"demo:complaint:{complaint.id}:reminder", now=now)
            db.add(ActionLog(complaint_id=complaint.id, actor="system", action_type="reminder_sent",
                             note=f"Demo reminder queued for {authority.role}.", created_at=now))
        added += 1
    db.commit()
    return added


def reset_demo_data(db: Session) -> int:
    """Clear demo activity and load fresh curated records, preserving hospitals/authorities."""
    db.execute(delete(Notification))
    db.execute(delete(ActionLog))
    db.execute(delete(CallbackRequest))
    db.execute(delete(Complaint))
    db.flush()
    seed_demo_authority_phones(db)
    count = seed_demo_data(db, target_count=25)
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Seva Dhwani hospitals and optional dashboard demo records.")
    parser.add_argument("--demo-data", action="store_true", help="Add curated synthetic complaints for dashboard demos")
    parser.add_argument("--reset-demo", action="store_true", help="Clear complaint activity and reload 25 curated fake complaints")
    parser.add_argument("--yes", action="store_true", help="Skip the typed confirmation required by --reset-demo")
    args = parser.parse_args()
    Base.metadata.create_all(bind=engine)
    if args.reset_demo and not args.yes:
        confirmation = input("This clears all complaints, notifications, action logs, and callback requests. Type yes to continue: ")
        if confirmation.strip().lower() != "yes":
            print("Demo reset cancelled.")
            return
    with SessionLocal() as db:
        seed_database(db)
        if args.reset_demo:
            demo_count = reset_demo_data(db)
        elif args.demo_data:
            seed_demo_authority_phones(db)
            demo_count = seed_demo_data(db)
        else:
            demo_count = 0
    print(f"Seeded Seva Dhwani demo hospitals. Added {demo_count} synthetic complaints.")


if __name__ == "__main__":
    main()
