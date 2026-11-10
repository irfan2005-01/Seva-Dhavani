import pytest

from app.categorizer import categorize


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("ಆಸ್ಪತ್ರೆಯಲ್ಲಿ ಔಷಧ ಇಲ್ಲ", "Medicine Unavailable"),
        ("ಔಷಧಿ ಸಿಗುತ್ತಿಲ್ಲ", "Medicine Unavailable"),
        ("ಮಾತ್ರೆ ಇಲ್ಲ", "Medicine Unavailable"),
        ("ಡಾಕ್ಟರ್ ಇಲ್ಲ", "Doctor/Staff Unavailable"),
        ("ಆಸ್ಪತ್ರೆಯಲ್ಲಿ ನರ್ಸ್ ಇಲ್ಲ", "Doctor/Staff Unavailable"),
        ("ಸಿಬ್ಬಂದಿ ಲಭ್ಯವಿಲ್ಲ", "Doctor/Staff Unavailable"),
        ("ಶೌಚಾಲಯ ಗಲೀಜು", "Cleanliness & Hygiene"),
        ("ವಾರ್ಡ್‌ನಲ್ಲಿ ಕೊಳಕು ಇದೆ", "Cleanliness & Hygiene"),
        ("ಕುಡಿಯುವ ನೀರು ಸಿಗುತ್ತಿಲ್ಲ", "Drinking Water & Sanitation"),
        ("ಶೌಚಾಲಯಕ್ಕೆ ನೀರು ಬರುತ್ತಿಲ್ಲ", "Drinking Water & Sanitation"),
        ("ಹಾಸಿಗೆ ಸಿಗುತ್ತಿಲ್ಲ", "Beds & Facilities"),
        ("ವಾರ್ಡ್‌ನ ಬೆಡ್ ಮುರಿದಿದೆ", "Beds & Facilities"),
        ("ಮೇಲ್ಛಾವಣಿ ಸೋರುತ್ತಿದೆ", "Infrastructure Maintenance"),
        ("ಆಸ್ಪತ್ರೆಯಲ್ಲಿ ವಿದ್ಯುತ್ ಇಲ್ಲ", "Infrastructure Maintenance"),
        ("अस्पताल में दवा नहीं है", "Medicine Unavailable"),
        ("गोली उपलब्ध नहीं है", "Medicine Unavailable"),
        ("इंजेक्शन नहीं मिल रहा है", "Medicine Unavailable"),
        ("डॉक्टर मौजूद नहीं हैं", "Doctor/Staff Unavailable"),
        ("अस्पताल का शौचालय गंदा है", "Cleanliness & Hygiene"),
        ("पीने का पानी नहीं है", "Drinking Water & Sanitation"),
        ("बिस्तर उपलब्ध नहीं है", "Beds & Facilities"),
        ("पंखा खराब है", "Infrastructure Maintenance"),
        ("Doctor is not available today", "Doctor/Staff Unavailable"),
        ("The pharmacy has no medicine", "Medicine Unavailable"),
        ("The ward toilet is filthy", "Cleanliness & Hygiene"),
        ("There is no drinking water in the ward", "Drinking Water & Sanitation"),
        ("No bed is available in the ward", "Beds & Facilities"),
        ("The ceiling is leaking", "Infrastructure Maintenance"),
    ],
)
def test_keyword_categorizer_handles_common_language_stems(description: str, expected: str):
    assert categorize(description) == expected
