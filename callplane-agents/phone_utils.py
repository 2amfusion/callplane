"""Normalize US phone numbers for BiteBuddy DB lookup (exact match on +1XXXXXXXXXX)."""

from __future__ import annotations

import re


def normalize_e164_us(phone: str) -> str:
    """
    Normalize to E.164 for US numbers, e.g. +12182701915.

    LiveKit SIP often sends 10–11 digits without '+'; BiteBuddy stores +1...
    """
    if not phone or not str(phone).strip():
        return ""
    digits = re.sub(r"\D", "", str(phone).strip())
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if len(digits) > 11 and len(digits[-10:]) == 10:
        return f"+1{digits[-10:]}"
    if phone.strip().startswith("+") and digits:
        return f"+{digits}"
    return phone.strip()
