"""Replaceable keyword categorizer for Kannada, English, and Hindi complaints."""

from .config import CATEGORIES
from .services.sarvam import classify_with_llm

CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Doctor/Staff Unavailable": (
        "doctor unavailable", "doctor absent", "staff unavailable", "nurse unavailable",
        "\u0cb5\u0cc8\u0ca6\u0ccd\u0caf\u0cb0\u0cbf\u0cb2\u0ccd\u0cb2", "\u0cb5\u0cc8\u0ca6\u0ccd\u0caf\u0cb0\u0cc1 \u0c87\u0cb2\u0ccd\u0cb2", "\u0cb8\u0cbf\u0cac\u0ccd\u0cac\u0c82\u0ca6\u0cbf \u0c87\u0cb2\u0ccd\u0cb2", "\u0921\u0949\u0915\u094d\u091f\u0930 \u0928\u0939\u0940\u0902", "\u0915\u0930\u094d\u092e\u091a\u093e\u0930\u0940 \u0928\u0939\u0940\u0902",
    ),
    "Medicine Unavailable": (
        "medicine unavailable", "medicine not available", "medicines unavailable", "pharmacy out",
        "\u0c94\u0cb7\u0ca7\u0cbf \u0c87\u0cb2\u0ccd\u0cb2", "\u0cae\u0ca6\u0ccd\u0ca6\u0cc1 \u0c87\u0cb2\u0ccd\u0cb2", "\u0926\u0935\u093e \u0928\u0939\u0940\u0902", "\u0926\u0935\u093e\u0908 \u0909\u092a\u0932\u092c\u094d\u0927 \u0928\u0939\u0940\u0902",
    ),
    "Cleanliness & Hygiene": (
        "unclean", "dirty", "cleanliness", "hygiene", "\u0cb8\u0ccd\u0cb5\u0c9a\u0ccd\u0c9b\u0ca4\u0cc6 \u0c87\u0cb2\u0ccd\u0cb2", "\u0c95\u0cca\u0cb3\u0c95\u0cc1", "\u0938\u092b\u093e\u0908 \u0928\u0939\u0940\u0902", "\u0917\u0902\u0926\u0917\u0940",
    ),
    "Drinking Water & Sanitation": (
        "drinking water", "no water", "water supply", "sanitation", "\u0c95\u0cc1\u0ca1\u0cbf\u0caf\u0cc1\u0cb5 \u0ca8\u0cc0\u0cb0\u0cc1", "\u0ca8\u0cc0\u0cb0\u0cc1 \u0c87\u0cb2\u0ccd\u0cb2", "\u092a\u0940\u0928\u0947 \u0915\u093e \u092a\u093e\u0928\u0940", "\u092a\u093e\u0928\u0940 \u0928\u0939\u0940\u0902",
    ),
    "Beds & Facilities": (
        "no bed", "bed unavailable", "beds unavailable", "facility", "\u0cb9\u0cbe\u0cb8\u0cbf\u0c97\u0cc6 \u0c87\u0cb2\u0ccd\u0cb2", "\u0cac\u0cc6\u0ca1\u0ccd \u0c87\u0cb2\u0ccd\u0cb2", "\u092c\u093f\u0938\u094d\u0924\u0930 \u0928\u0939\u0940\u0902",
    ),
    "Infrastructure Maintenance": (
        "broken", "repair", "maintenance", "electricity", "fan not", "\u0ca6\u0cc1\u0cb0\u0cb8\u0ccd\u0ca4\u0cbf", "\u0c95\u0cc6\u0c9f\u0ccd\u0c9f\u0cbf\u0cb9\u0ccb\u0c97\u0cbf\u0ca6\u0cc6", "\u092e\u0930\u092e\u094d\u092e\u0924", "\u0916\u0930\u093e\u092c",
    ),
}

# Short, category-specific stems catch common inflections and changed word
# order in typed or transcribed speech. Keep generic words out where they could
# pull an issue into a neighboring category (for example, "clean" vs water).
CATEGORY_STEMS: dict[str, tuple[str, ...]] = {
    "Doctor/Staff Unavailable": (
        "doctor", "physician", "nurse", "staff",
        "ವೈದ್ಯ", "ಡಾಕ್ಟರ್", "ನರ್ಸ್", "ಸಿಬ್ಬಂದಿ",
        "डॉक्टर", "चिकित्सक", "नर्स", "स्टाफ", "कर्मचारी",
    ),
    "Medicine Unavailable": (
        "medicine", "medication", "pharmacy", "tablet", "pill", "injection",
        "ಔಷಧ", "ಔಷಧಿ", "ಮಾತ್ರೆ", "ಇಂಜೆಕ್ಷನ್",
        "दवा", "दवाई", "गोली", "इंजेक्शन", "औषधि",
    ),
    "Cleanliness & Hygiene": (
        "unclean", "dirty", "filthy", "cleanliness", "hygiene", "garbage", "litter",
        "ಸ್ವಚ್ಛ", "ಗಲೀಜು", "ಕೊಳಕು", "ಕಸ",
        "सफाई", "गंदगी", "गंदा", "कूड़ा", "कचरा",
    ),
    "Drinking Water & Sanitation": (
        "drinking water", "water supply", "no water", "water", "sanitation", "toilet", "washroom", "tap water",
        "ನೀರು", "ಶೌಚಾಲಯ", "ಟಾಯ್ಲೆಟ್",
        "पेयजल", "पानी", "शौचालय", "टॉयलेट", "नल",
    ),
    "Beds & Facilities": (
        "bed", "mattress", "bedding",
        "ಹಾಸಿಗೆ", "ಬೆಡ್",
        "बिस्तर", "बेड", "पलंग",
    ),
    "Infrastructure Maintenance": (
        "repair", "broken", "maintenance", "electricity", "leak", "leaking", "damaged",
        "ದುರಸ್ತಿ", "ಕೆಟ್ಟು", "ಸೋರು", "ವಿದ್ಯುತ್",
        "मरम्मत", "खराब", "टूट", "रिसाव", "बिजली",
    ),
}

EMERGENCY_KEYWORDS = (
    "emergency", "accident", "ambulance", "heart attack", "bleeding", "unconscious",
    "\u0ca4\u0cc1\u0cb0\u0ccd\u0ca4\u0cc1", "\u0c85\u0caa\u0c98\u0cbe\u0ca4", "\u0c86\u0c82\u0cac\u0ccd\u0caf\u0cc1\u0cb2\u0cc6\u0ca8\u0ccd\u0cb8\u0ccd", "\u0cb0\u0c95\u0ccd\u0ca4\u0cb8\u0ccd\u0cb0\u0cbe\u0cb5", "\u0cb9\u0cc3\u0ca6\u0caf\u0cbe\u0c98\u0cbe\u0ca4",
    "\u0906\u092a\u093e\u0924\u0915\u093e\u0932", "\u0926\u0941\u0930\u094d\u0918\u091f\u0928\u093e", "\u090f\u092e\u094d\u092c\u0941\u0932\u0947\u0902\u0938", "\u0926\u093f\u0932 \u0915\u093e \u0926\u094c\u0930\u093e", "\u0916\u0942\u0928 \u092c\u0939",
)


def detect_emergency(description: str) -> bool:
    lowered = description.casefold()
    return any(keyword.casefold() in lowered for keyword in EMERGENCY_KEYWORDS)


def categorize(description: str) -> str:
    lowered = description.casefold()
    for category in CATEGORIES:
        if category == "Other":
            continue
        keywords = CATEGORY_KEYWORDS.get(category, ()) + CATEGORY_STEMS.get(category, ())
        if any(keyword.casefold() in lowered for keyword in keywords):
            return category
    return "Other"


def _offline_priority(text: str) -> str:
    lowered = text.casefold()
    if any(term in lowered for term in ("urgent", "unsafe", "severe", "ತುರ್ತು", "गंभीर")):
        return "high"
    if any(term in lowered for term in ("broken", "unavailable", "not working", "ಇಲ್ಲ", "नहीं")):
        return "medium"
    return "low"


async def classify_complaint(text: str) -> dict[str, str | bool]:
    """Use Sarvam when configured and safely fall back to deterministic rules."""
    keyword_emergency = detect_emergency(text)
    category = categorize(text)
    priority = _offline_priority(text)
    summary = text.strip()[:240] if text.strip().isascii() else f"{category} service issue reported."

    if keyword_emergency:
        return {"category": category, "priority": "high", "is_emergency": True, "summary_english": summary}

    llm_result = await classify_with_llm(text)
    if llm_result:
        candidate = llm_result.get("category")
        if candidate in CATEGORIES:
            category = candidate
        candidate_priority = str(llm_result.get("priority", "")).lower()
        if candidate_priority in {"low", "medium", "high"}:
            priority = candidate_priority
        candidate_summary = llm_result.get("summary_english")
        if isinstance(candidate_summary, str) and candidate_summary.strip():
            summary = candidate_summary.strip()[:240]
        llm_emergency = llm_result.get("is_emergency") is True
    else:
        llm_emergency = False

    # Emergency detection is deliberately conservative: either signal redirects.
    return {
        "category": category,
        "priority": priority,
        "is_emergency": keyword_emergency or llm_emergency,
        "summary_english": summary,
    }

