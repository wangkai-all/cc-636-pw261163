"""Canonical scalar helpers shared by the reader, API and exporters."""

from __future__ import annotations

import math
import struct
from typing import Any, Optional

STATA_MISSING_BASE = 0x7FE0000000000000
STATA_MISSING_STEP = 1 << 40
EXT_LETTERS = "abcdefghijklmnopqrstuvwxyz"


def canonical_number(value: float) -> str:
    """A stable, human-readable representation of a stored numeric value."""

    if isinstance(value, bool):
        return "1" if value else "0"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(number):
        return str(number)
    if number.is_integer() and abs(number) < 1e16:
        return str(int(number))
    return format(number, ".15g")


def number_key(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, bool):
        return "1" if value else "0"
    try:
        return canonical_number(float(value))
    except (TypeError, ValueError):
        return None


def json_scalar(value: Any) -> Any:
    """Convert numpy scalars (and friends) into JSON-friendly Python values."""

    if value is None:
        return None
    try:
        import numpy as np

        if isinstance(value, np.generic):
            value = value.item()
    except Exception:  # pragma: no cover - numpy is a hard dependency
        pass
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def is_nan(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(math.isnan(float(value)))
    except (TypeError, ValueError):
        return False


def ext_index(code: str) -> int:
    """. -> 0, .a -> 1 ... .z -> 26."""

    text = code[1:] if code.startswith(".") else code
    if not text:
        return 0
    return EXT_LETTERS.index(text[0].lower()) + 1


def ext_code_from_letter(letter: str) -> str:
    text = letter[1:] if letter.startswith(".") else letter
    return "." + text.lower()


def ext_ieee_value(code: str) -> float:
    raw = STATA_MISSING_BASE + ext_index(code) * STATA_MISSING_STEP
    return struct.unpack("<d", struct.pack("<Q", raw))[0]


def ext_code_from_ieee(value: float) -> Optional[str]:
    raw = struct.unpack("<Q", struct.pack("<d", float(value)))[0]
    if raw < STATA_MISSING_BASE:
        return None
    index = (raw - STATA_MISSING_BASE) // STATA_MISSING_STEP
    if index < 0 or index > 26:
        return None
    if raw != STATA_MISSING_BASE + index * STATA_MISSING_STEP:
        return None
    return "." if index == 0 else "." + EXT_LETTERS[index - 1]


def analysis_string(value: Any) -> str:
    """Canonical text for a compiled analysis value (for text exports)."""

    value = json_scalar(value)
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return canonical_number(value)
    return str(value)


def raw_string(value: Any) -> str:
    value = json_scalar(value)
    if value is None:
        return ""
    if isinstance(value, float):
        return canonical_number(value)
    return str(value)
