"""Identifier formats. All IDs are clearly synthetic (no real carrier prefixes)."""

from __future__ import annotations

import random
import string

# ISO 6346 letter values skip multiples of 11.
_LETTER_VALUES: dict[str, int] = {}
_v = 10
for _ch in string.ascii_uppercase:
    if _v % 11 == 0:
        _v += 1
    _LETTER_VALUES[_ch] = _v
    _v += 1

SYNTHETIC_OWNER_CODE = "SYN"  # owner code + equipment category "U" -> "SYNU"


def iso6346_check_digit(first10: str) -> int:
    """Check digit for the first 10 characters of a container number (ISO 6346)."""
    total = 0
    for i, ch in enumerate(first10):
        value = _LETTER_VALUES[ch] if ch.isalpha() else int(ch)
        total += value * (2**i)
    return (total % 11) % 10


def is_valid_container(ref: str) -> bool:
    if len(ref) != 11 or not ref[:4].isalpha() or not ref[4:].isdigit():
        return False
    return iso6346_check_digit(ref[:10]) == int(ref[10])


def container_ref(serial: int) -> str:
    body = f"{SYNTHETIC_OWNER_CODE}U{serial:06d}"
    return body + str(iso6346_check_digit(body))


def customer_id(n: int) -> str:
    return f"CUS-{n:05d}"


def booking_ref(n: int) -> str:
    return f"BKG{n:09d}"


def bl_ref(n: int) -> str:
    return f"SBL{n:09d}"


def enquiry_id(n: int) -> str:
    return f"ENQ-{n:06d}"


def event_id(n: int) -> str:
    return f"EVT-{n:07d}"


def typo(ref: str, rng: random.Random) -> str:
    """Change one digit of a reference (simulates a mistyped reference)."""
    positions = [i for i, c in enumerate(ref) if c.isdigit()]
    if not positions:
        return ref + "X"
    i = rng.choice(positions)
    new = rng.choice([d for d in string.digits if d != ref[i]])
    return ref[:i] + new + ref[i + 1 :]
