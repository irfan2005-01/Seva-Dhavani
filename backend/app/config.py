"""Application settings, complaint categories, and service-level targets."""

from dataclasses import dataclass
import os
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class CategoryConfig:
    default_authority_role: str
    sla_hours: int


# Values are easy to adjust for the hackathon pilot.
CATEGORY_CONFIG: dict[str, CategoryConfig] = {
    "Doctor/Staff Unavailable": CategoryConfig("Medical Superintendent", 24),
    "Medicine Unavailable": CategoryConfig("Pharmacy Officer", 24),
    "Cleanliness & Hygiene": CategoryConfig("Housekeeping Supervisor", 24),
    "Drinking Water & Sanitation": CategoryConfig("Water & Sanitation Engineer", 24),
    "Beds & Facilities": CategoryConfig("Ward In-charge", 48),
    "Infrastructure Maintenance": CategoryConfig("Maintenance Engineer", 48),
    "Other": CategoryConfig("Medical Superintendent", 48),
}

CATEGORIES = tuple(CATEGORY_CONFIG)
LANGUAGES = ("kn", "en", "hi")
CHANNELS = ("voice", "assisted", "web", "ivr")
COMPLAINT_STATUSES = ("Registered", "Assigned", "In Progress", "Resolved", "Closed")

# Follow-up engine controls. Tests can inject time directly into the service.
REMINDER_BEFORE_DUE_HOURS = float(os.getenv("REMINDER_BEFORE_DUE_HOURS", "4"))
ESCALATE_AFTER_OVERDUE_HOURS = float(os.getenv("ESCALATE_AFTER_OVERDUE_HOURS", "2"))
ESCALATION_REPEAT_HOURS = float(os.getenv("ESCALATION_REPEAT_HOURS", "24"))
STALE_AFTER_HOURS = float(os.getenv("STALE_AFTER_HOURS", "12"))
FOLLOWUP_INTERVAL_SECONDS = max(1, int(os.getenv("FOLLOWUP_INTERVAL_SECONDS", "60")))
DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() in ("1", "true", "yes", "on")
