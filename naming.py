"""
naming.py
=========
Pattern-based PDF file names: pattern validation, ``period`` derivation,
file-name sanitising and collision-free allocation. Pure logic, no GUI or
PDF imports, so the CLI, the batch runner and the GUI can share it.
"""

from __future__ import annotations

import os
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

# ext4 and APFS cap a file name at 255 UTF-8 *bytes*, not characters: a
# 200-character cap let 150 x "ł" (300 bytes) through preview and dry-run and
# then failed at write with "File name too long". 200 bytes leaves room for a
# "_NN" suffix and ".pdf".
MAX_STEM_BYTES = 200

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

    return finalize_stem(_TOKEN_RE.sub(expand, pattern)), warnings


def finalize_stem(stem: str) -> str:
    """Apply the whole-name rules: sanitise, reserved names, byte cap.

    Every stem that becomes a file name goes through here, including the
    XML-file-name fallback, so no path can skip a rule.
    """
    # A leading dot makes a hidden file on macOS and Linux, so the PDF would
    # seem never to have been written. Stripped before the reserved-name check
    # so ".con" still becomes "con_".
    stem = sanitize(stem).lstrip(" .")

    # Windows refuses these names even with an extension (CON.pdf).
    head, dot, rest = stem.partition(".")
    if head.strip().upper() in _RESERVED:
        stem = head + "_" + dot + rest

    # errors="ignore" drops a multi-byte character cut in half by the slice,
    # so the cap never produces invalid UTF-8.
    stem = stem.encode("utf-8")[:MAX_STEM_BYTES].decode("utf-8", errors="ignore")
    return stem.rstrip(" .")


# ── Allocation ────────────────────────────────────────────────────

class NameAllocator:
    """Hand out ``.pdf`` names that never overwrite anything.

    Comparison is case-insensitive because Windows and default macOS volumes
    treat ``A.pdf`` and ``a.pdf`` as one file. The folder is snapshotted once
    (cheap for large batches) but each candidate is also checked against the
    disk, so a file that appeared mid-run is not overwritten either.
    """

    def __init__(self, output_dir: str):
        self._dir = output_dir
        self._taken: set[str] = set()
        if os.path.isdir(output_dir):
            self._taken = {n.lower() for n in os.listdir(output_dir)}

    def allocate(self, stem: str) -> str:
        n = 1
        while True:
            name = f"{stem}.pdf" if n == 1 else f"{stem}_{n}.pdf"
            if (name.lower() not in self._taken
                    and not os.path.exists(os.path.join(self._dir, name))):
                self._taken.add(name.lower())
                return name
            n += 1
