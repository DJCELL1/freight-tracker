"""Read a despatch manifest PDF into shipment / consignment / line records.

A manifest pack is one PDF holding two kinds of page:

  * one MANIFEST page — the load leaving the Victorian warehouse. It carries
    the manifest number, the carrier and its consignment note, the despatch
    date, and a row per order on the truck.
  * one DELIVERY DOCKET page per order — the SO and PO numbers, the document
    date, and the item lines that went into the carton.

The manifest is the source of truth for *when it left Vic*; the dockets are the
source of truth for *what is in it*, and (see normalise.reconcile) for the
order numbers themselves, since they print far more legibly there.

Everything here is written against scanned input, so it prefers to return a
field empty over returning it wrong — the upload screen shows the parse for
review before anything is saved.
"""

import re
from datetime import datetime

import normalise

DESPATCH_DATE_RE = re.compile(r"Despatch\s*Date[:\s]*([\d/\-]{6,10})", re.I)
DESPATCH_TIME_RE = re.compile(r"Despatch\s*Time[:\s]*(\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM)?)", re.I)
DOCUMENT_DATE_RE = re.compile(r"Document\s*Date.*?(\d{1,2}/\d{1,2}/\d{2,4})", re.I | re.S)
PROMISED_TIME_RE = re.compile(r"(\d{1,2}:\d{2}:\d{2}\s*(?:AM|PM))", re.I)
CARRIER_NOTE_RE = re.compile(r"Notes[:\s]*(.+?)(?:\s*Despatch|\s*$)", re.I | re.S)
MANIFEST_NO_RE = re.compile(r"MAN\s*[-–—]?\s*(\d{6,10})", re.I)
LOOSE_MANIFEST_NO_RE = re.compile(r"\b(\d{7,10})\b")
STATE_POSTCODE_RE = re.compile(r"\b(VIC|NSW|QLD|WA|SA|TAS|NT|ACT)\s+(\d{4})\b")
POSTCODE_RE = re.compile(r"\b(\d{4})\b")

# Walking back from the state to find the suburb has to stop somewhere, and the
# street type is the reliable fence: without it "23 Scanlon Drive EPPING VIC"
# reports the origin suburb as "Scanlon Drive Epping".
STREET_TYPES = {
    "DRIVE", "DR", "STREET", "ST", "ROAD", "RD", "CIRCUIT", "CCT", "AVENUE", "AVE",
    "COURT", "CT", "PLACE", "PL", "WAY", "LANE", "LN", "CLOSE", "CRESCENT", "CRES",
    "PARADE", "PDE", "HIGHWAY", "HWY", "BOULEVARD", "BLVD", "TERRACE", "TCE", "LOOP",
}
MAX_SUBURB_WORDS = 3

# The quantity column is the last thing on a docket line, so the pattern is
# anchored to the end: without that, "Angle 25 x 12 x 1.6 M" reads as a quantity
# of 6 metres. The lookbehind rejects a digit that is really the tail of a
# decimal, and the character class allows the lookalikes OCR substitutes for
# digits ("5 LTHS" scans as "S LTHS").
QTY_UOM_RE = re.compile(
    r"(?<![.,\d])\b([0-9OoIlSsBGZTAg|]{1,5})\s+(LTHS|EA|PK|BOX|SET|PCS|PC|KG|ROLL|PR|M)\s*$",
    re.I,
)

# The start of a street address inside a cramped manifest row.
ADDRESS_RE = re.compile(r"(\d+[A-Za-z]?\s+[A-Za-z].*)$")
COMPANY_SUFFIXES = {"LTD", "LID", "LD", "PTY", "PIY"}


class ManifestParseError(Exception):
    pass


def _is_manifest_page(text: str) -> bool:
    squashed = normalise.squash(text).upper()
    return "MANIFEST" in squashed or "DESPATCH DATE" in squashed


def _is_docket_page(text: str) -> bool:
    squashed = normalise.squash(text).upper()
    return "DELIVERY DOCKET" in squashed or "DELIVER TO" in squashed


def _first(pattern, text, group=1):
    match = pattern.search(text or "")
    return match.group(group).strip() if match else None


def _clean_time(raw):
    """Validate a promised time, repairing the one OCR slip we see often.

    A leading `1` scans as `4` or `7` ("41:59:00 PM"), which is unambiguous on a
    12-hour clock because no other reading is valid. Anything still unparseable
    is dropped rather than displayed as a broken time.
    """
    if not raw:
        return ""
    candidate = normalise.squash(raw).upper()
    attempts = [candidate]
    if candidate[:1] in "47":
        attempts.append("1" + candidate[1:])
    for attempt in attempts:
        for fmt in ("%I:%M:%S %p", "%I:%M %p", "%H:%M:%S", "%H:%M"):
            try:
                return datetime.strptime(attempt, fmt).strftime("%I:%M %p").lstrip("0")
            except ValueError:
                continue
    return ""


def _clean_carrier_ref(raw: str, manifest_no) -> str:
    """Keep the carrier and consignment codes, drop the scanner's confetti.

    The notes cell reads "CRI WA - CRI952 - MP236666", but OCR sprays in stray
    lowercase fragments and bleeds the big grey manifest number into the same
    line, so keep only the code-shaped tokens.
    """
    manifest_digits = manifest_no.split("-")[-1] if manifest_no else None
    kept = []
    for token in normalise.squash(raw).split():
        stripped = token.strip(",.;:")
        if not stripped:
            continue
        if stripped == "-":
            kept.append("-")
            continue
        if stripped == manifest_digits:
            continue
        if re.fullmatch(r"[A-Z0-9][A-Z0-9\-/]{1,}", stripped):
            kept.append(stripped)
    cleaned = " ".join(kept).strip(" -")
    return re.sub(r"\s*-\s*-\s*", " - ", cleaned)


def _suburb_before(text: str, end: int) -> str:
    """The suburb sitting immediately before a state code, at most a few words."""
    words = []
    for token in reversed(text[:end].split()):
        cleaned = token.strip(",.;:()")
        if not cleaned or not cleaned.isalpha():
            break
        if cleaned.upper() in STREET_TYPES or cleaned.upper() in COMPANY_SUFFIXES:
            break
        words.insert(0, cleaned)
        if len(words) == MAX_SUBURB_WORDS:
            break
    return " ".join(words)


def _parse_origin(pages: list, destination_postcodes: set):
    """Where the load left from, read off the sender's footer address.

    Only the tail of each page is searched — the sender block sits in the
    footer, while the top of the page is the *delivery* address, and reading
    that would report the freight as having left its own destination.

    Comes back empty when the footer is too degraded to read, which on a scan is
    often; the upload screen then falls back to the configured origin rather
    than inventing one.
    """
    for text in pages:
        lines = [l for l in (text or "").split("\n") if l.strip()]
        if not lines:
            continue
        footer = lines[max(0, int(len(lines) * 0.7)):]
        for line in footer:
            squashed = normalise.squash(line)
            match = STATE_POSTCODE_RE.search(squashed)
            if not match:
                continue
            state, postcode = match.groups()
            if postcode in destination_postcodes:
                continue
            suburb = _suburb_before(squashed, match.start())
            if not suburb:
                continue
            return f"{suburb.title()} {state} {postcode}"
    return ""


def _parse_manifest_header(text: str) -> dict:
    squashed = normalise.squash(text)

    manifest_no = None
    match = MANIFEST_NO_RE.search(squashed)
    if match:
        manifest_no = f"MAN-{match.group(1)}"
    elif re.search(r"MAN\s*[-–—]", squashed, re.I):
        # The number is set in large grey type and usually wraps away from its
        # "MANIFEST MAN-" label, so fall back to the first long bare number.
        loose = LOOSE_MANIFEST_NO_RE.search(squashed)
        if loose:
            manifest_no = f"MAN-{loose.group(1)}"

    return {
        "manifest_no": manifest_no,
        "despatch_date": normalise.parse_date(_first(DESPATCH_DATE_RE, squashed)),
        "despatch_time": _clean_time(_first(DESPATCH_TIME_RE, squashed)),
        "carrier_ref": _clean_carrier_ref(_first(CARRIER_NOTE_RE, squashed) or "", manifest_no),
        "pickup": "PICKUP" in squashed.upper(),
    }


def _split_manifest_rows(text: str) -> list:
    """Group the manifest table into one blob per order.

    Rows are found by their content, not by the leading row number: that number
    is a single character in grey type and scans as `{` or `|` about as often as
    it scans as a digit. A line carrying a promised time or an order number
    opens a row, and the wrapped remainder of the address follows it.
    """
    rows = []
    current = None
    for line in (text or "").split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        opens_row = bool(PROMISED_TIME_RE.search(stripped)) or bool(normalise.find_ref(stripped, "SO"))
        if opens_row:
            if current:
                rows.append(current)
            current = [stripped]
        elif current is not None:
            current.append(stripped)
    if current:
        rows.append(current)
    return rows


def _clean_wrapped_address(raw: str) -> str:
    """Tidy the second line of a wrapped address ("Lid VALE, 6155, WA es")."""
    tokens = normalise.squash(raw).split()
    while tokens and tokens[0].upper().strip(",.") in COMPANY_SUFFIXES:
        tokens.pop(0)
    while tokens and len(tokens[-1]) <= 2 and tokens[-1].islower():
        tokens.pop()
    return " ".join(tokens)


def _parse_manifest_rows(text: str) -> list:
    parsed = []
    for position, row_lines in enumerate(_split_manifest_rows(text), start=1):
        head_line = row_lines[0]
        blob = normalise.squash(" ".join(row_lines))
        order_no = normalise.find_ref(blob, "SO")
        if not order_no:
            continue

        seq_match = re.match(r"^[^\w]*(\d{1,2})\s+[A-Za-z]", head_line)
        # Everything ahead of the promised time on the opening line is
        # "Company + delivery address"; the wrap that follows finishes the address.
        head = PROMISED_TIME_RE.split(head_line)[0]
        head = re.sub(r"^[^A-Za-z]*", "", head).strip()
        wrapped = _clean_wrapped_address(" ".join(row_lines[1:]))

        address_match = ADDRESS_RE.search(head)
        if address_match:
            company = normalise.squash(head[: address_match.start(1)])
            address = normalise.squash(f"{address_match.group(1)} {wrapped}")
        else:
            company = normalise.squash(head)
            address = wrapped

        parsed.append({
            "seq": int(seq_match.group(1)) if seq_match else position,
            "order_no": order_no,
            "company": company,
            "address": address,
            "promised_time": _clean_time(_first(PROMISED_TIME_RE, blob)),
        })
    return parsed


def _parse_docket_lines(text: str) -> list:
    """Item lines, best effort.

    A scan can shear the quantity column off into its own block further down the
    page; when that happens no line matches and the docket is still valid — the
    shipment tracking does not depend on the item detail.
    """
    lines = []
    for raw in (text or "").split("\n"):
        stripped = raw.strip()
        if len(stripped) < 8:
            continue
        match = QTY_UOM_RE.search(stripped)
        if not match:
            continue
        qty = normalise.to_digits(match.group(1))
        if not qty or int(qty) == 0:
            continue
        parts = stripped[: match.start()].strip().split(None, 1)
        if len(parts) < 2:
            continue
        code, description = parts[0], parts[1].strip()
        if not description or description.lower().startswith(("quantity", "description")):
            continue
        lines.append({
            "item_code": code,
            "description": description,
            "qty": int(qty),
            "uom": match.group(2).upper(),
        })
    return lines


def _parse_docket(text: str) -> dict:
    squashed = normalise.squash(text)
    return {
        "docket_no": normalise.find_ref(squashed, "PSS"),
        "order_no": normalise.find_ref(squashed, "SO"),
        "external_doc": normalise.find_ref(squashed, "PO"),
        "document_date": normalise.parse_date(_first(DOCUMENT_DATE_RE, squashed)),
        "lines": _parse_docket_lines(text),
    }


def parse(pdf) -> dict:
    """Parse a manifest pack into one shipment dict with its consignments."""
    import ocr

    pages, ocr_used = ocr.extract_pages(pdf)
    if not pages:
        raise ManifestParseError("The PDF has no pages.")

    manifest_pages = [p for p in pages if _is_manifest_page(p)]
    docket_pages = [p for p in pages if _is_docket_page(p) and not _is_manifest_page(p)]

    if not manifest_pages:
        raise ManifestParseError(
            "No manifest page found — expected a page headed 'MANIFEST' with a "
            "despatch date. Is this a delivery docket on its own?"
        )

    manifest_text = manifest_pages[0]
    header = _parse_manifest_header(manifest_text)
    if not header["despatch_date"]:
        raise ManifestParseError(
            "Found the manifest but could not read its Despatch Date, which is "
            "what the ETA counts from."
        )

    dockets = [_parse_docket(p) for p in docket_pages]
    dockets = [d for d in dockets if d["order_no"] or d["docket_no"]]

    # The dockets print the order numbers most legibly, so let them correct the
    # manifest's — see the module docstring in normalise.py.
    trusted_orders = [d["order_no"] for d in dockets if d["order_no"]]
    by_order = {d["order_no"]: d for d in dockets if d["order_no"]}

    consignments = []
    for row in _parse_manifest_rows(manifest_text):
        order_no = normalise.reconcile(row["order_no"], trusted_orders)
        docket = by_order.get(order_no, {})
        consignments.append({**row, "order_no": order_no,
                             "docket_no": docket.get("docket_no"),
                             "external_doc": docket.get("external_doc"),
                             "document_date": docket.get("document_date"),
                             "lines": docket.get("lines", [])})

    # A docket with no matching manifest row still shipped — carry it through
    # rather than silently dropping freight off the truck.
    seen = {c["order_no"] for c in consignments}
    for docket in dockets:
        if docket["order_no"] and docket["order_no"] not in seen:
            consignments.append({
                "seq": len(consignments) + 1, "order_no": docket["order_no"],
                "company": "", "address": "", "promised_time": "",
                "docket_no": docket["docket_no"], "external_doc": docket["external_doc"],
                "document_date": docket["document_date"], "lines": docket["lines"],
            })

    if not consignments:
        raise ManifestParseError(
            "Read the manifest header but found no orders on it — no SO numbers "
            "could be picked out of the rows or the dockets."
        )

    consignments.sort(key=lambda c: c["seq"])
    for position, consignment in enumerate(consignments, start=1):
        consignment["seq"] = position

    destination_postcodes = set(
        POSTCODE_RE.findall(" ".join(c["address"] or "" for c in consignments))
    )

    return {
        **header,
        "origin": _parse_origin(pages, destination_postcodes),
        "ocr_used": ocr_used,
        "page_count": len(pages),
        "consignments": consignments,
    }
