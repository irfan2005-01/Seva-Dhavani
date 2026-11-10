"""Notification outbox. The default provider queues and logs; SMS can be added later."""
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Complaint, Notification

logger = logging.getLogger("seva_dhwani.notifications")

MESSAGES = {
    "en": {
        "due_soon": "Reminder: a hospital service complaint needs attention soon.",
        "overdue": "Urgent reminder: a hospital service complaint is overdue.",
        "escalated": "A hospital service complaint has been escalated for attention.",
        "acknowledged": "Your hospital service complaint has been received.",
        "in_progress": "Action has started on your hospital service complaint.",
        "resolved": "Your hospital service complaint has been marked resolved.",
        "closed": "Your hospital service complaint has been closed.",
    },
    "kn": {
        "due_soon": "ಜ್ಞಾಪನೆ: ಆಸ್ಪತ್ರೆಯ ಸೇವಾ ದೂರಿಗೆ ಶೀಘ್ರ ಗಮನ ಅಗತ್ಯವಿದೆ.",
        "overdue": "ತುರ್ತು ಜ್ಞಾಪನೆ: ಆಸ್ಪತ್ರೆಯ ಸೇವಾ ದೂರು ಗಡುವು ಮೀರಿದೆ.",
        "escalated": "ಆಸ್ಪತ್ರೆಯ ಸೇವಾ ದೂರನ್ನು ಹೆಚ್ಚಿನ ಗಮನಕ್ಕಾಗಿ ಮೇಲಾಧಿಕಾರಿಗೆ ಕಳುಹಿಸಲಾಗಿದೆ.",
        "acknowledged": "ನಿಮ್ಮ ಆಸ್ಪತ್ರೆಯ ಸೇವಾ ದೂರನ್ನು ಸ್ವೀಕರಿಸಲಾಗಿದೆ.",
        "in_progress": "ನಿಮ್ಮ ಆಸ್ಪತ್ರೆಯ ಸೇವಾ ದೂರಿನ ಮೇಲೆ ಕ್ರಮ ಆರಂಭವಾಗಿದೆ.",
        "resolved": "ನಿಮ್ಮ ಆಸ್ಪತ್ರೆಯ ಸೇವಾ ದೂರನ್ನು ಪರಿಹರಿಸಲಾಗಿದೆ ಎಂದು ಗುರುತಿಸಲಾಗಿದೆ.",
        "closed": "ನಿಮ್ಮ ಆಸ್ಪತ್ರೆಯ ಸೇವಾ ದೂರನ್ನು ಮುಕ್ತಾಯಗೊಳಿಸಲಾಗಿದೆ.",
    },
    "hi": {
        "due_soon": "सूचना: अस्पताल सेवा शिकायत पर जल्द ध्यान देना है।",
        "overdue": "तत्काल सूचना: अस्पताल सेवा शिकायत की समय सीमा बीत गई है।",
        "escalated": "अस्पताल सेवा शिकायत को आगे ध्यान के लिए भेजा गया है।",
        "acknowledged": "आपकी अस्पताल सेवा शिकायत प्राप्त हुई है।",
        "in_progress": "आपकी अस्पताल सेवा शिकायत पर कार्रवाई शुरू हो गई है।",
        "resolved": "आपकी अस्पताल सेवा शिकायत को हल किया गया है।",
        "closed": "आपकी अस्पताल सेवा शिकायत बंद कर दी गई है।",
    },
}


class ConsoleLogProvider:
    def queue(self, notification: Notification) -> None:
        logger.info("Queued %s notification for role=%s", notification.channel, notification.recipient_role)


provider = ConsoleLogProvider()


def enqueue(db: Session, complaint: Complaint, *, role: str, phone: str | None, message: str,
            dedupe_key: str, now: datetime) -> int:
    """Create one in-app item and an SMS item when a phone is available; safe to retry."""
    count = 0
    destinations = [("inapp", None)]
    if phone:
        destinations.append(("sms", phone))
    for channel, target_phone in destinations:
        key = f"{dedupe_key}:{channel}"
        if db.scalar(select(Notification.id).where(Notification.dedupe_key == key)):
            continue
        row = Notification(
            complaint_id=complaint.id, recipient_role=role, recipient_phone=target_phone,
            channel=channel, message=message, status="queued", created_at=now, dedupe_key=key,
        )
        db.add(row)
        db.flush()
        provider.queue(row)
        count += 1
    return count


def localized_message(language: str, key: str) -> str:
    return MESSAGES.get(language, MESSAGES["en"]).get(key, MESSAGES["en"][key])
