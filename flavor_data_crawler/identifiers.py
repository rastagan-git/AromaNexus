"""Chemical identifier normalization and validation."""

from __future__ import annotations

import re

CAS_PATTERN = re.compile(r"^(\d{2,7})-(\d{2})-(\d)$")
INVALID_SENTINELS = {
    "",
    "\\",
    "n/a",
    "na",
    "nan",
    "none",
    "null",
    "not found",
    "ambiguous/list found",
}


def clean_text(value: object) -> str:
    """Normalize spreadsheet text without changing its semantic content."""

    if value is None:
        return ""
    text = str(value).replace("\u00a0", " ").strip()
    return "" if text.casefold() in INVALID_SENTINELS else text


def normalize_cas(value: object) -> str:
    """Return a hyphenated CAS number when the input shape is recognizable."""

    text = clean_text(value).replace(" ", "")
    if not text:
        return ""
    if text.isdigit() and 5 <= len(text) <= 10:
        return f"{text[:-3]}-{text[-3:-1]}-{text[-1]}"
    match = re.fullmatch(r"(\d{2,7})[-–—](\d{2})[-–—](\d)", text)
    return "-".join(match.groups()) if match else text


def is_valid_cas(value: object) -> bool:
    """Validate CAS syntax and checksum."""

    cas = normalize_cas(value)
    match = CAS_PATTERN.fullmatch(cas)
    if not match:
        return False
    body = "".join(match.groups()[:2])
    check_digit = int(match.group(3))
    checksum = sum(multiplier * int(digit) for multiplier, digit in enumerate(reversed(body), 1))
    return checksum % 10 == check_digit


def require_valid_cas(value: object) -> str:
    """Return a normalized CAS number or raise a descriptive ValueError."""

    cas = normalize_cas(value)
    if not cas:
        raise ValueError("CAS number is empty")
    if not is_valid_cas(cas):
        raise ValueError(f"Invalid CAS number or checksum: {cas}")
    return cas
