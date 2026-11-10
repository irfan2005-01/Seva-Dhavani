"""Backend IVR call-flow state machine used by the phone simulator and future adapters."""
from datetime import datetime, timedelta, timezone
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from ..categorizer import classify_complaint, detect_emergency
from ..complaint_ids import generate_complaint_id
from ..messages import EMERGENCY_MESSAGES
from ..models import ActionLog, Authority, Complaint, Hospital, IvrSession
from ..services.notify import enqueue, localized_message
from .channels import IvrProvider, SmsProvider

IVR_PROMPTS = {
    "kn": {
        "menu": "ದೂರು ದಾಖಲಿಸಲು 1 ಒತ್ತಿರಿ, ಸ್ಥಿತಿ ತಿಳಿಯಲು 2 ಒತ್ತಿರಿ, ತುರ್ತು ಸಹಾಯಕ್ಕೆ 9 ಒತ್ತಿರಿ.",
        "language": "ಭಾಷೆ ಆಯ್ಕೆಮಾಡಿ: ಕನ್ನಡಕ್ಕೆ 1, English ಗೆ 2, हिंदी के लिए 3 ಒತ್ತಿರಿ.",
        "hospital": "ಆಸ್ಪತ್ರೆ ಆಯ್ಕೆಮಾಡಲು ಅದರ ಸಂಖ್ಯೆಯನ್ನು ಒತ್ತಿರಿ. ",
        "voice": "ದಯವಿಟ್ಟು ನಿಮ್ಮ ಆಸ್ಪತ್ರೆ ಸೇವಾ ಸಮಸ್ಯೆಯನ್ನು ಹೇಳಿ.",
        "confirm": "ಈ ದೂರನ್ನು ಸಲ್ಲಿಸಬೇಕೆ? ಸಲ್ಲಿಸಲು 1, ಮತ್ತೆ ಹೇಳಲು 2 ಒತ್ತಿರಿ. ",
        "sms_offer": "ನಿಮ್ಮ ದೂರು ಸಂಖ್ಯೆ ",
        "phone": "ಈ ದೂರು ಸಂಖ್ಯೆಯನ್ನು SMS ಮೂಲಕ ಪಡೆಯಲು ನಿಮ್ಮ ಹತ್ತು ಅಂಕಿಯ ಮೊಬೈಲ್ ಸಂಖ್ಯೆಯನ್ನು ನಮೂದಿಸಿ.",
        "status_id": "ನಿಮ್ಮ ದೂರು ಸಂಖ್ಯೆಯ ಒಂಬತ್ತು ಅಂಕಿಗಳನ್ನು ನಮೂದಿಸಿ. ನಂತರ # ಒತ್ತಿರಿ.",
        "invalid": "ಈ ಆಯ್ಕೆ ಸರಿಯಲ್ಲ. ಮತ್ತೆ ಪ್ರಯತ್ನಿಸಿ. ",
        "ended": "ಕರೆ ಮುಗಿದಿದೆ.",
    },
    "en": {
        "menu": "Press 1 to register a complaint, 2 to check status, 9 for emergency help.",
        "language": "Choose language: press 1 for Kannada, 2 for English, 3 for Hindi.",
        "hospital": "Choose a hospital by pressing its number. ",
        "voice": "Please describe the non-emergency hospital service issue.",
        "confirm": "Submit this complaint? Press 1 to submit or 2 to record again. ",
        "sms_offer": "Your complaint ID is ",
        "phone": "Enter your ten-digit mobile number to receive this complaint ID by SMS.",
        "status_id": "Enter the nine digits in your complaint ID, then press #.",
        "invalid": "That key is not valid here. Please try again. ",
        "ended": "The call has ended.",
    },
    "hi": {
        "menu": "शिकायत दर्ज करने के लिए 1 दबाएँ, स्थिति जानने के लिए 2, आपात सहायता के लिए 9 दबाएँ।",
        "language": "भाषा चुनें: कन्नड़ के लिए 1, अंग्रेज़ी के लिए 2, हिंदी के लिए 3 दबाएँ।",
        "hospital": "अस्पताल चुनने के लिए उसका नंबर दबाएँ। ",
        "voice": "कृपया अस्पताल की गैर-आपातकालीन सेवा समस्या बताएं।",
        "confirm": "क्या यह शिकायत दर्ज करें? दर्ज करने के लिए 1, फिर से बोलने के लिए 2 दबाएँ। ",
        "sms_offer": "आपकी शिकायत आईडी है ",
        "phone": "SMS से शिकायत आईडी पाने के लिए अपना दस अंकों का मोबाइल नंबर दर्ज करें।",
        "status_id": "शिकायत आईडी के नौ अंक दर्ज करें, फिर # दबाएँ।",
        "invalid": "यह कुंजी यहाँ मान्य नहीं है। फिर प्रयास करें। ",
        "ended": "कॉल समाप्त हो गई है।",
    },
}
LANGUAGE_KEYS = {"1": "kn", "2": "en", "3": "hi"}
IVR_EMERGENCY = {
    "kn": "ತಕ್ಷಣ ಆಸ್ಪತ್ರೆ ಸಿಬ್ಬಂದಿಯನ್ನು ಸಂಪರ್ಕಿಸಿ ಅಥವಾ 108ಕ್ಕೆ ಕರೆ ಮಾಡಿ.",
    "en": "Contact hospital staff or call 108 immediately.",
    "hi": "तुरंत अस्पताल के कर्मचारियों से संपर्क करें या 108 पर कॉल करें।",
}
STATUS_NAMES = {
    "kn": {"Registered": "ದಾಖಲಾಗಿದೆ", "Assigned": "ನಿಯೋಜಿಸಲಾಗಿದೆ", "In Progress": "ಪ್ರಗತಿಯಲ್ಲಿದೆ", "Resolved": "ಪರಿಹರಿಸಲಾಗಿದೆ", "Closed": "ಮುಚ್ಚಲಾಗಿದೆ"},
    "en": {"Registered": "Registered", "Assigned": "Assigned", "In Progress": "In progress", "Resolved": "Resolved", "Closed": "Closed"},
    "hi": {"Registered": "दर्ज", "Assigned": "नियुक्त", "In Progress": "कार्य जारी", "Resolved": "हल", "Closed": "बंद"},
}


class OutboxSmsProvider:
    """Demo SMS adapter; replace this object with Twilio/Exotel delivery later."""
    def send(self, db: Session, complaint: Complaint, phone: str, message: str,
             dedupe_key: str, now: datetime) -> int:
        return enqueue(db, complaint, role="Complainant", phone=phone, message=message,
                       dedupe_key=dedupe_key, now=now)


sms_provider: SmsProvider = OutboxSmsProvider()


def _prompt(session: IvrSession, prompt_text: str, expects: str, **extra) -> dict:
    session.updated_at = datetime.now(timezone.utc)
    return {"session_id": session.id, "prompt_text": prompt_text, "language": session.language,
            "expects": expects, **extra}


def _hospital_prompt(db: Session, session: IvrSession) -> str:
    hospitals = db.scalars(select(Hospital).order_by(Hospital.district, Hospital.name)).all()
    session.digit_buffer = ""
    labels = " ".join(f"{i}. {hospital.name}, {hospital.district}." for i, hospital in enumerate(hospitals, 1))
    return IVR_PROMPTS[session.language]["hospital"] + labels


def _safe_id_speech(complaint_id: str) -> str:
    _prefix, year, sequence = complaint_id.split("-")
    return f"S D. {' '.join(year)}. {' '.join(sequence)}."


def _flag_emergency(db: Session, session: IvrSession) -> None:
    """Persist an emergency audit flag if a hospital has already been selected."""
    if not session.hospital_id:
        return
    now = datetime.now(timezone.utc)
    text = session.pending_description or "Emergency help selected in IVR."
    flagged = Complaint(
        complaint_id=f"EMG-{now.strftime('%y%m%d%H%M%S%f')[-16:]}", hospital_id=session.hospital_id,
        category="Other", description=text, language=session.language, channel="ivr",
        status="Emergency Redirected", priority="Emergency", is_emergency_flagged=True,
        created_at=now,
    )
    db.add(flagged)
    db.flush()
    db.add(ActionLog(complaint_id=flagged.id, actor="system", action_type="emergency_flagged",
                     note="Emergency detected in IVR; caller directed to hospital staff or 108."))
    session.pending_description = None


class SimulatedIVRProvider:
    """Database-backed menu flow; a real telephony adapter can submit the same key/text inputs."""

    async def start(self, db: Session) -> dict:
        session = IvrSession(id=str(uuid.uuid4()), state="menu", language="kn", digit_buffer="",
                            created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
        db.add(session)
        db.flush()
        result = _prompt(session, IVR_PROMPTS["kn"]["menu"], "digit")
        db.commit()
        return result

    async def input(self, db: Session, session_id: str, *, digit: str | None = None,
                    digits: str | None = None, speech: str | None = None) -> dict:
        session = db.get(IvrSession, session_id)
        if session is None:
            raise KeyError("IVR session not found")
        if session.state in ("end", "emergency"):
            return _prompt(session, IVR_PROMPTS[session.language]["ended"], "end", complaint_id=session.complaint_id)

        keyed = digits if digits is not None else digit
        if speech and detect_emergency(speech):
            session.pending_description = speech.strip()[:5000]
            _flag_emergency(db, session)
            session.state = "emergency"
            db.commit()
            return _prompt(session, IVR_EMERGENCY[session.language], "end", emergency=True)

        prompt = IVR_PROMPTS[session.language]
        if session.state == "menu":
            if digit == "9":
                session.state = "emergency"
                db.commit()
                return _prompt(session, IVR_EMERGENCY[session.language], "end", emergency=True)
            if digit == "1":
                session.state = "register_language"
                result = _prompt(session, prompt["language"], "digit")
            elif digit == "2":
                session.state = "status_language"
                result = _prompt(session, prompt["language"], "digit")
            else:
                result = _prompt(session, prompt["invalid"] + prompt["menu"], "digit")
        elif session.state in ("register_language", "status_language"):
            selected_language = LANGUAGE_KEYS.get(digit or "")
            if not selected_language:
                result = _prompt(session, prompt["invalid"] + prompt["language"], "digit")
            else:
                session.language = selected_language
                prompt = IVR_PROMPTS[session.language]
                if session.state == "register_language":
                    session.state = "hospital"
                    result = _prompt(session, _hospital_prompt(db, session), "digit")
                else:
                    session.state = "status_id"
                    session.digit_buffer = ""
                    result = _prompt(session, prompt["status_id"], "digit")
        elif session.state == "hospital":
            hospitals = db.scalars(select(Hospital).order_by(Hospital.district, Hospital.name)).all()
            if not digit or not digit.isdigit() or not 1 <= int(digit) <= len(hospitals):
                result = _prompt(session, prompt["invalid"] + _hospital_prompt(db, session), "digit")
            else:
                session.hospital_id = hospitals[int(digit) - 1].id
                session.state = "voice"
                result = _prompt(session, prompt["voice"], "voice")
        elif session.state == "voice":
            if not speech or not speech.strip():
                result = _prompt(session, prompt["voice"], "voice")
            else:
                session.pending_description = speech.strip()[:5000]
                session.state = "confirm"
                result = _prompt(session, prompt["confirm"] + session.pending_description, "digit")
        elif session.state == "confirm":
            if digit == "2":
                session.pending_description = None
                session.state = "voice"
                result = _prompt(session, prompt["voice"], "voice")
            elif digit == "1" and session.pending_description:
                classification = await classify_complaint(session.pending_description)
                if classification["is_emergency"]:
                    _flag_emergency(db, session)
                    session.state = "emergency"
                    db.commit()
                    return _prompt(session, IVR_EMERGENCY[session.language], "end", emergency=True)
                category = str(classification["category"])
                default_role = config.CATEGORY_CONFIG[category].default_authority_role
                authority = db.scalar(select(Authority).where(
                    Authority.hospital_id == session.hospital_id, Authority.role == default_role
                ).order_by(Authority.id))
                if authority is None:
                    result = _prompt(session, "No officer is configured for this category. Please contact the helpdesk.", "end")
                    session.state = "end"
                else:
                    now = datetime.now(timezone.utc)
                    complaint = Complaint(
                        complaint_id=generate_complaint_id(db), hospital_id=session.hospital_id,
                        category=category, description=session.pending_description, language=session.language,
                        channel="ivr", status="Assigned", priority=str(classification["priority"]),
                        assigned_authority_id=authority.id, created_at=now,
                        due_at=now + timedelta(hours=config.CATEGORY_CONFIG[category].sla_hours),
                        transcript_original=session.pending_description,
                        summary_english=str(classification["summary_english"]),
                    )
                    db.add(complaint)
                    db.flush()
                    db.add_all([
                        ActionLog(complaint_id=complaint.id, actor="system", action_type="registered", note="Complaint registered via IVR."),
                        ActionLog(complaint_id=complaint.id, actor="system", action_type="assigned", note=f"Assigned to {authority.role} via IVR."),
                    ])
                    session.complaint_id = complaint.complaint_id
                    session.pending_description = None
                    session.state = "sms_offer"
                    spaced_id = _safe_id_speech(complaint.complaint_id)
                    result = _prompt(session, IVR_PROMPTS[session.language]["sms_offer"] + spaced_id + " Press 1 for SMS or 2 to finish.", "digit", complaint_id=complaint.complaint_id)
            else:
                result = _prompt(session, prompt["invalid"] + prompt["confirm"] + (session.pending_description or ""), "digit")
        elif session.state == "sms_offer":
            if digit == "2":
                session.state = "end"
                result = _prompt(session, f"{prompt['ended']} {session.complaint_id}", "end", complaint_id=session.complaint_id)
            elif digit == "1":
                session.state = "phone"
                session.digit_buffer = ""
                result = _prompt(session, prompt["phone"], "digit", complaint_id=session.complaint_id)
            else:
                result = _prompt(session, prompt["invalid"] + "Press 1 for SMS or 2 to finish.", "digit", complaint_id=session.complaint_id)
        elif session.state == "phone":
            sequence = keyed or ""
            if sequence == "#":
                sequence = ""
            if not sequence or not sequence.isdigit() or len(session.digit_buffer + sequence) > 10:
                result = _prompt(session, prompt["invalid"] + prompt["phone"], "digit", complaint_id=session.complaint_id)
            else:
                session.digit_buffer += sequence
                if len(session.digit_buffer) < 10:
                    result = _prompt(session, f"{len(session.digit_buffer)} digits received. {prompt['phone']}", "digit", complaint_id=session.complaint_id)
                else:
                    complaint = db.scalar(select(Complaint).where(Complaint.complaint_id == session.complaint_id))
                    if complaint:
                        phone = session.digit_buffer
                        complaint.complainant_phone = phone
                        sms_message = f"Your hospital service complaint ID is {complaint.complaint_id}."
                        sms_provider.send(db, complaint, phone, sms_message,
                                          f"complaint:{complaint.id}:ivr:complaint_id", datetime.now(timezone.utc))
                    session.digit_buffer = ""
                    session.state = "end"
                    result = _prompt(session, "SMS queued. " + prompt["ended"] + f" {session.complaint_id}", "end", complaint_id=session.complaint_id, sms_queued=True)
        elif session.state == "status_id":
            if digit == "#":
                entered = session.digit_buffer
                session.digit_buffer = ""
                if len(entered) >= 9:
                    complaint_id = f"SD-{entered[:4]}-{entered[4:9]}"
                elif len(entered) == 5:
                    complaint_id = f"SD-{datetime.now(timezone.utc).year}-{entered}"
                else:
                    result = _prompt(session, prompt["invalid"] + prompt["status_id"], "digit")
                    db.commit()
                    return result
                complaint = db.scalar(select(Complaint).where(
                    Complaint.complaint_id == complaint_id, Complaint.is_emergency_flagged.is_(False)
                ))
                session.state = "end"
                if complaint:
                    hospital = db.get(Hospital, complaint.hospital_id)
                    status_name = STATUS_NAMES[session.language].get(complaint.status, complaint.status)
                    result = _prompt(session, f"{complaint_id}. {status_name}. {complaint.category}. {hospital.name if hospital else ''}. {prompt['ended']}", "end", complaint_id=complaint_id, status=complaint.status)
                else:
                    result = _prompt(session, "Complaint ID not found. " + prompt["ended"], "end", complaint_id=complaint_id)
            elif keyed and keyed.isdigit() and len(session.digit_buffer + keyed) <= 9:
                session.digit_buffer += keyed
                result = _prompt(session, f"{len(session.digit_buffer)}. {prompt['status_id']}", "digit")
            else:
                result = _prompt(session, prompt["invalid"] + prompt["status_id"], "digit")
        else:
            session.state = "end"
            result = _prompt(session, prompt["ended"], "end", complaint_id=session.complaint_id)
        db.commit()
        return result


ivr_provider: IvrProvider = SimulatedIVRProvider()
