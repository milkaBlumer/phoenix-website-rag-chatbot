"""Deterministic boundaries for personal insurance data and professional advice."""

from __future__ import annotations

import re
from dataclasses import dataclass

from backend.services.generation_service import NO_ANSWER

PERSONAL_INFO_RESPONSE = (
    "אין לי גישה לפוליסה או לתביעה האישית שלך, ולכן איני יכול לקבוע כיסוי או זכאות. "
    "אפשר לבדוק זאת באזור האישי או מול מוקד התביעות של הפניקס. "
    "אני כן יכול להסביר מידע כללי שמופיע באתר."
)
MEDICAL_ADVICE_RESPONSE = (
    "איני יכול לאבחן או להמליץ על טיפול רפואי. יש לפנות לאיש מקצוע רפואי; "
    "במקרה דחוף, יש לפנות לשירותי החירום."
)
LEGAL_ADVICE_RESPONSE = (
    "איני יכול לתת ייעוץ משפטי או להמליץ אם להגיש תביעה. "
    "כדאי להתייעץ עם עורך דין או גורם מקצועי מתאים."
)

PERSONAL_INFO_PHRASES = (
    "הפוליסה האישית שלי",
    "פוליסת הדירה האישית שלי",
    "הכיסוי שלי",
    "הנזק שלי מכוסה",
    "המקרה שלי מכוסה",
    "האם אני מכוסה",
    "אני מכוסה",
    "מספר הפוליסה",
    "החשבון שלי",
    "כמה אקבל",
    "הפרמיה האישית שלי",
    "מגיע לי",
    "האם אני זכאי",
    "האם אני זכאית",
)
PERSONAL_COVERAGE_PATTERN = re.compile(
    r"(?:ה?פוליס(?:ה|ת)|ה?ביטוח)(?:\s+[א-תA-Za-z0-9-]+){0,3}"
    r"\s+(?:האישי(?:ת)?\s+)?שלי(?:\s+[א-תA-Za-z0-9-]+){0,5}"
    r"\s+(?:מכסה|תכסה|יכסה|מכוסה|מכסים|כולל|כוללת|מכיל|מכילה)"
)
PERSONAL_CLAIM_PATTERN = re.compile(
    r"(?:תביעה\s+שהגשתי|התביעה\s+שלי|תביעה\s+שלי)"
    r".{0,40}(?:אושרה|אושרה כבר|סטטוס|מצב|התקדמה)",
)
PERSONAL_FINANCIAL_PATTERN = re.compile(
    r"(?:כמה|מה)\s+(?:כסף|סכום|הפרמיה|פרמיה)"
    r".{0,45}(?:אקבל|אשלם|תהיה|האישית שלי|שלי)"
)
PERSONAL_TIMELINE_PATTERN = re.compile(
    r"(?:כמה זמן|מתי|תוך כמה זמן)"
    r".{0,60}(?:הדירה שלי|התביעה שלי|התיק שלי|השמאי שלי|הנזק שלי)"
)
MEDICAL_ADVICE_PHRASES = (
    "איזה טיפול רפואי",
    "איזה טיפול לעשות",
    "מה לעשות עם הכאבים",
    "מה לעשות עם הכאב",
    "יש לי כאבים",
    "יש לי כאב",
    "תאבחן",
    "מה האבחנה",
    "איזו תרופה לקחת",
)
LEGAL_ADVICE_PHRASES = (
    "ייעוץ משפטי",
    "כדאי לי לתבוע",
    "האם לתבוע",
    "לתבוע את השכן",
    "לתבוע בבית משפט",
)
INSTRUCTION_OVERRIDE_PHRASES = (
    "תתעלם מהאתר",
    "תתעלם מההוראות",
    "התעלם מההוראות",
    "תמציא לי",
    "תמציא תשובה",
    "תמציא מקור",
)


@dataclass(frozen=True)
class SafetyDecision:
    """A safe response that should bypass retrieval and model generation."""

    answer: str
    category: str


def assess_question(question: str) -> SafetyDecision | None:
    """Return a fixed safe response for known out-of-scope intents, if detected."""
    normalized = " ".join(question.casefold().split())
    if any(phrase in normalized for phrase in INSTRUCTION_OVERRIDE_PHRASES):
        return SafetyDecision(NO_ANSWER, "instruction_override")
    if any(phrase in normalized for phrase in MEDICAL_ADVICE_PHRASES):
        return SafetyDecision(MEDICAL_ADVICE_RESPONSE, "medical_advice")
    if any(phrase in normalized for phrase in LEGAL_ADVICE_PHRASES):
        return SafetyDecision(LEGAL_ADVICE_RESPONSE, "legal_advice")
    if (
        any(phrase in normalized for phrase in PERSONAL_INFO_PHRASES)
        or PERSONAL_COVERAGE_PATTERN.search(normalized)
        or PERSONAL_CLAIM_PATTERN.search(normalized)
        or PERSONAL_FINANCIAL_PATTERN.search(normalized)
        or PERSONAL_TIMELINE_PATTERN.search(normalized)
    ):
        return SafetyDecision(PERSONAL_INFO_RESPONSE, "personal_information")
    return None
