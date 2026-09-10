"""Repairing the reference numbers OCR mangles.

Scanned manifests come back with the document numbers slightly wrong in ways
that are obvious to a human and fatal to a regex: `SO-182268` reads as
`S$0-182268`, `So-1s2268` or `SO-182287`. Two things save us.

First, the *prefix* is drawn from a tiny known set (SO/PO/PSS/MAN), so a fuzzy
match against that set is safe.

Second — and this is the one that actually fixes wrong digits — every SO on the
manifest is also printed on its own delivery docket, in a large clean table
that OCRs reliably. So the dockets act as a spell-check dictionary for the
manifest: a manifest SO that is one or two characters off a docket SO is that
docket's SO.
"""

import difflib
import re
from datetime import datetime

KNOWN_PREFIXES = ("SO", "PO", "PSS", "MAN", "PRO")

# Characters OCR swaps in for digits inside a reference number.
_TO_DIGIT = str.maketrans({
    "O": "0", "o": "0", "D": "0", "Q": "0",
    "I": "1", "l": "1", "|": "1", "i": "1", "!": "1",
    "Z": "2", "z": "2",
    "A": "4",
    "S": "5", "s": "5", "$": "5",
    "G": "6", "b": "6",
    "T": "7",
    "B": "8",
    "g": "9", "q": "9",
})

# Characters OCR swaps in for letters inside a prefix.
_TO_LETTER = str.maketrans({"0": "O", "$": "S", "5": "S", "1": "I", "8": "B", "6": "G"})

# Deliberately loose: prefix and number may both carry lookalike characters, and
# the separator may come through as an en/em dash or vanish into a space.
_REF = re.compile(r"\b([A-Za-z$0-9]{2,4})\s*[-–—]\s*([A-Za-z0-9$|!]{4,12})\b")


def _clean_prefix(raw: str) -> str:
    letters = raw.translate(_TO_LETTER).upper()
    letters = re.sub(r"[^A-Z]", "", letters)
    if not letters:
        return ""
    if letters in KNOWN_PREFIXES:
        return letters
    match = difflib.get_close_matches(letters, KNOWN_PREFIXES, n=1, cutoff=0.6)
    return match[0] if match else letters


def to_digits(raw: str) -> str:
    """Read a run of characters as the digits OCR meant them to be."""
    return re.sub(r"[^0-9]", "", (raw or "").translate(_TO_DIGIT))


def _clean_number(raw: str) -> str:
    return to_digits(raw)


def find_refs(text: str, prefix: str) -> list:
    """Every `PREFIX-NNNN` in `text`, OCR damage repaired, in order of appearance.

    Duplicates are collapsed but the first-seen order is kept, because on a
    manifest the row order is the load order.
    """
    found = []
    for raw_prefix, raw_number in _REF.findall(text):
        if _clean_prefix(raw_prefix) != prefix:
            continue
        number = _clean_number(raw_number)
        if not number:
            continue
        ref = f"{prefix}-{number}"
        if ref not in found:
            found.append(ref)
    return found


def find_ref(text: str, prefix: str):
    """The first `PREFIX-NNNN` in `text`, or None."""
    refs = find_refs(text, prefix)
    return refs[0] if refs else None


def reconcile(ref, trusted, max_edits: int = 2):
    """Snap a shaky reference onto a trusted one when they are near-identical.

    Only a single unambiguous candidate is accepted — if a manifest number sits
    equally close to two docket numbers, guessing would be worse than leaving it
    alone for a human to look at.
    """
    if not ref or ref in trusted:
        return ref
    candidates = []
    for candidate in trusted:
        if len(candidate) != len(ref):
            continue
        edits = sum(1 for a, b in zip(ref, candidate) if a != b)
        if edits <= max_edits:
            candidates.append((edits, candidate))
    if not candidates:
        return ref
    best = min(c[0] for c in candidates)
    winners = {c[1] for c in candidates if c[0] == best}
    return winners.pop() if len(winners) == 1 else ref


DATE_FORMATS = ("%d/%m/%y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%y", "%d-%m-%Y")


def parse_date(raw):
    """Australian day-first dates off the docket, returned as ISO `YYYY-MM-DD`."""
    if not raw:
        return None
    cleaned = re.sub(r"[^0-9/\-]", "", str(raw).strip())
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def squash(text: str) -> str:
    """Collapse whitespace so patterns can span the line breaks OCR invents."""
    return re.sub(r"\s+", " ", text or "").strip()
