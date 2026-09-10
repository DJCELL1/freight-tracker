"""SQLite persistence for the freight tracker.

Three tables mirror the paperwork: a `shipments` row per manifest, a
`consignments` row per order on that manifest, and `docket_lines` for the item
detail. Re-uploading the same manifest refreshes what the PDF says and leaves
the delivery marks alone, so a second scan of a pack never loses the fact that
something has already landed.
"""

import sqlite3
from contextlib import contextmanager

import eta as eta_calc

DB_PATH = "freight_tracker.db"

DEFAULT_SETTINGS = {
    "transit_days": str(eta_calc.DEFAULT_TRANSIT_DAYS),
    "business_days": "0",
    "default_origin": "Epping VIC 3076",
}

# Fields that come off the PDF and are refreshed on every re-upload.
PDF_FIELDS = (
    "seq", "company", "address", "promised_time",
    "docket_no", "external_doc", "document_date",
)


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS shipments (
                manifest_no TEXT PRIMARY KEY,
                despatch_date TEXT NOT NULL,
                despatch_time TEXT,
                carrier_ref TEXT,
                origin TEXT,
                pickup INTEGER DEFAULT 0,
                source_file TEXT,
                ocr_used INTEGER DEFAULT 0,
                uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS consignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                manifest_no TEXT NOT NULL REFERENCES shipments(manifest_no) ON DELETE CASCADE,
                order_no TEXT NOT NULL,
                seq INTEGER,
                company TEXT,
                address TEXT,
                promised_time TEXT,
                docket_no TEXT,
                external_doc TEXT,
                document_date TEXT,
                delivered_on TEXT,
                notes TEXT,
                UNIQUE (manifest_no, order_no)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS docket_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                consignment_id INTEGER NOT NULL REFERENCES consignments(id) ON DELETE CASCADE,
                item_code TEXT,
                description TEXT,
                qty INTEGER,
                uom TEXT
            )
        """)
        conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        for key, value in DEFAULT_SETTINGS.items():
            conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))


def get_setting(key, default=None):
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is None:
        return DEFAULT_SETTINGS.get(key, default)
    return row["value"]


def set_setting(key, value):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )


def get_transit_rule():
    """The ETA rule as (transit_days, business_days)."""
    try:
        days = int(get_setting("transit_days"))
    except (TypeError, ValueError):
        days = eta_calc.DEFAULT_TRANSIT_DAYS
    return days, get_setting("business_days") == "1"


def save_shipment(shipment, source_file=None):
    """Insert or refresh one manifest and its consignments.

    Returns (manifest_no, action) where action is "added" or "updated".
    """
    manifest_no = shipment.get("manifest_no")
    if not manifest_no:
        raise ValueError("A shipment needs a manifest number before it can be saved.")

    with get_conn() as conn:
        existing = conn.execute(
            "SELECT 1 FROM shipments WHERE manifest_no = ?", (manifest_no,)
        ).fetchone()
        conn.execute(
            """
            INSERT INTO shipments (manifest_no, despatch_date, despatch_time, carrier_ref,
                                   origin, pickup, source_file, ocr_used)
            VALUES (:manifest_no, :despatch_date, :despatch_time, :carrier_ref,
                    :origin, :pickup, :source_file, :ocr_used)
            ON CONFLICT(manifest_no) DO UPDATE SET
                despatch_date = excluded.despatch_date,
                despatch_time = excluded.despatch_time,
                carrier_ref   = excluded.carrier_ref,
                origin        = excluded.origin,
                pickup        = excluded.pickup,
                source_file   = excluded.source_file,
                ocr_used      = excluded.ocr_used
            """,
            {
                "manifest_no": manifest_no,
                "despatch_date": shipment.get("despatch_date"),
                "despatch_time": shipment.get("despatch_time") or "",
                "carrier_ref": shipment.get("carrier_ref") or "",
                "origin": shipment.get("origin") or "",
                "pickup": 1 if shipment.get("pickup") else 0,
                "source_file": source_file or "",
                "ocr_used": 1 if shipment.get("ocr_used") else 0,
            },
        )

        for consignment in shipment.get("consignments", []):
            values = {k: consignment.get(k) for k in PDF_FIELDS}
            values.update(manifest_no=manifest_no, order_no=consignment["order_no"])
            conn.execute(
                """
                INSERT INTO consignments (manifest_no, order_no, seq, company, address,
                                          promised_time, docket_no, external_doc, document_date)
                VALUES (:manifest_no, :order_no, :seq, :company, :address,
                        :promised_time, :docket_no, :external_doc, :document_date)
                ON CONFLICT(manifest_no, order_no) DO UPDATE SET
                    seq           = excluded.seq,
                    company       = excluded.company,
                    address       = excluded.address,
                    promised_time = excluded.promised_time,
                    docket_no     = excluded.docket_no,
                    external_doc  = excluded.external_doc,
                    document_date = excluded.document_date
                """,
                values,
            )
            row = conn.execute(
                "SELECT id FROM consignments WHERE manifest_no = ? AND order_no = ?",
                (manifest_no, consignment["order_no"]),
            ).fetchone()
            # Item lines are wholly derived from the PDF, so replace them outright.
            conn.execute("DELETE FROM docket_lines WHERE consignment_id = ?", (row["id"],))
            conn.executemany(
                "INSERT INTO docket_lines (consignment_id, item_code, description, qty, uom) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    (row["id"], l.get("item_code"), l.get("description"), l.get("qty"), l.get("uom"))
                    for l in consignment.get("lines", [])
                ],
            )

    return manifest_no, ("updated" if existing else "added")


def get_consignments():
    """Every consignment with its shipment context, newest despatch first."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT c.*, s.despatch_date, s.despatch_time, s.carrier_ref, s.origin,
                   s.pickup, s.source_file, s.ocr_used,
                   (SELECT COUNT(*) FROM docket_lines dl WHERE dl.consignment_id = c.id) AS line_count,
                   (SELECT COALESCE(SUM(dl.qty), 0) FROM docket_lines dl WHERE dl.consignment_id = c.id) AS total_qty
            FROM consignments c
            JOIN shipments s ON s.manifest_no = c.manifest_no
            ORDER BY s.despatch_date DESC, c.seq ASC
        """).fetchall()
    return [dict(r) for r in rows]


def get_lines(consignment_id):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT item_code, description, qty, uom FROM docket_lines "
            "WHERE consignment_id = ? ORDER BY id",
            (consignment_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def mark_delivered(consignment_id, delivered_on):
    with get_conn() as conn:
        conn.execute(
            "UPDATE consignments SET delivered_on = ? WHERE id = ?",
            (delivered_on, consignment_id),
        )


def set_notes(consignment_id, notes):
    with get_conn() as conn:
        conn.execute("UPDATE consignments SET notes = ? WHERE id = ?", (notes, consignment_id))


def delete_shipment(manifest_no):
    with get_conn() as conn:
        conn.execute("DELETE FROM shipments WHERE manifest_no = ?", (manifest_no,))
