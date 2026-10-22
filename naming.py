"""
naming.py
=========
Pattern-based PDF file names: pattern validation, ``period`` derivation,
file-name sanitising and collision-free allocation. Pure logic, no GUI or
PDF imports, so the CLI, the batch runner and the GUI can share it.
"""

from __future__ import annotations

import re
from datetime import date

from mapping import HEADER_SLOTS, SLOT_CATEGORIES

# ── Fields ────────────────────────────────────────────────────────

PERIOD_FIELD = "period"

# Header slots only: item slots repeat per line, so they cannot name a file.
NAME_FIELDS: list[str] = [
    slot
    for slots in SLOT_CATEGORIES.values()
    for slot in slots
    if slot in HEADER_SLOTS
] + [PERIOD_FIELD]

# Leaves room for a "_NN" suffix and ".pdf" under the common 255-byte limit
# even when every character is multi-byte.
MAX_STEM_LEN = 200

_TOKEN_RE = re.compile(r"\{([a-z0-9_]+)\}")


class PatternError(ValueError):
    """The name pattern uses an unknown field or has a stray brace."""


def validate_pattern(pattern: str) -> list[str]:
    """Return the field names used in *pattern*, in order.

    Raises PatternError naming the offending field or character. We tokenise
    by hand instead of using ``str.format`` so a stray ``{`` or ``{0.x}``
    can never reach attribute lookup.
    """
    fields = []
    for m in _TOKEN_RE.finditer(pattern):
        name = m.group(1)
        if name not in NAME_FIELDS:
            raise PatternError(f"unknown field {{{name}}}")
        fields.append(name)
    leftover = _TOKEN_RE.sub("", pattern)
    for ch in ("{", "}"):
        if ch in leftover:
            raise PatternError(f"unmatched {ch!r} in pattern")
    return fields


# ── Period ────────────────────────────────────────────────────────

_ISO_DATE_RE = re.compile(r"^\s*(\d{4})-(\d{2})-(\d{2})")
_DMY_DATE_RE = re.compile(r"^\s*(\d{2})[./](\d{2})[./](\d{4})")


def parse_period(date_text: str) -> str:
    """Return ``YYYY-MM`` for a date string, or ``""`` if unparseable."""
    m = _ISO_DATE_RE.match(date_text)
    if m:
        year, month, day = (int(g) for g in m.groups())
    else:
        m = _DMY_DATE_RE.match(date_text)
        if not m:
            return ""
        day, month, year = (int(g) for g in m.groups())
    try:
        date(year, month, day)
    except ValueError:
        return ""
    return f"{year:04d}-{month:02d}"


# ── Sanitising ────────────────────────────────────────────────────

# Forbidden on Windows (the strictest target); dropped everywhere so a batch
# produces the same names on every OS.
_FORBIDDEN_RE = re.compile(r'[<>:"/\\|?*]')
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_WHITESPACE_RE = re.compile(r"\s+")
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {
    f"{base}{n}" for base in ("COM", "LPT") for n in range(1, 10)
}


def sanitize(text: str) -> str:
    """Make *text* safe as part of a file name; non-ASCII letters are kept.

    Whitespace collapses first so tabs and newlines become a space rather than
    being dropped as controls and gluing words together.
    """
    text = _WHITESPACE_RE.sub(" ", text)
    text = _FORBIDDEN_RE.sub("", text)
    text = _CONTROL_RE.sub("", text)
    text = _WHITESPACE_RE.sub(" ", text)
    # Windows silently strips trailing dots and spaces, which would make the
    # name we report differ from the file on disk.
    return text.strip().rstrip(" .").strip()


def build_stem(pattern: str, values: dict[str, str]) -> tuple[str, list[str]]:
    """Expand *pattern* into a file-name stem; return ``(stem, warnings)``.

    A field that is absent or empty after sanitising becomes ``no-<field>``
    and adds a ``missing <field>`` warning.
    """
    validate_pattern(pattern)
    warnings: list[str] = []

    def expand(m: re.Match) -> str:
        name = m.group(1)
        if name == PERIOD_FIELD:
            raw = parse_period(values.get("issue_date", ""))
        else:
            raw = values.get(name, "")
        value = sanitize(raw or "")
        if not value:
            warnings.append(f"missing {name}")
            return f"no-{name}"
        return value

    stem = sanitize(_TOKEN_RE.sub(expand, pattern))

    # Windows refuses these names even with an extension (CON.pdf).
    head, dot, rest = stem.partition(".")
    if head.strip().upper() in _RESERVED:
        stem = head + "_" + dot + rest

    stem = stem[:MAX_STEM_LEN].rstrip(" .")
    return stem, warnings
