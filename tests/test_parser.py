"""Parser tests run against text shaped like a real OCR'd manifest pack.

The damage in these fixtures is copied from actual scanner output: the row
number reads as `{`, "11:59" reads as "41:59", `SO-` reads as `S$0-`, a digit in
an order number comes through wrong, and a quantity of 5 reads as `S`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import parser
import pytest

MANIFEST_PAGE = """MANIFEST MAN- Carrier: Notes: FRT WA - FRT100 -
pane , MP111222
00099001 Despatch Date: 10/09/26 Depart: [|
| Blue Line = PICKUP Despatch Time: Arrive: | | |
| { Northside Joinery Pty 12 Example Circuit, CANNING 41:59:00 PM So-190001 [| = |
Lid VALE, 6155, WA es
2 Northside Joinery Pty 12 Example Circuit, CANNING 11:59:00 PM SO-190062 |
Lid VALE, 6155, WA
"""

DOCKET_ONE = """DELIVERY DOCKET PSS-200001
Deliver To Bil To
Customer No. Contact Name Document Date Order No. External Doc. No.
C-000001 A Person 10/09/26 S$0-190001 PO-055001
048728-0 XY-0487 Stop End M (2.8) 6 LTHS
515465-1 XY-5154 Clip on Pelmet N/A (6.5) - Suits XY-5153 Track 1 LTHS
"""

DOCKET_TWO = """DELIVERY DOCKET PSS-200002
Deliver To Bil To
Customer No. Contact Name Document Date Order No. External Doc. No.
C-000001 A Person 10/09/26 SO-190002 PO-055002
605065-1 XY-6050 Base Insert Carrier - N/A (6.5) S LTHS
ANG25121665-0 Angle 25 x 12 x 1.6 M (6.5) 10 LTHS
"""


@pytest.fixture
def pack(monkeypatch):
    """Feed the parser page text directly, standing in for the PDF/OCR layer."""
    def parse_pages(pages, ocr_used=True):
        import ocr as ocr_module
        monkeypatch.setattr(ocr_module, "extract_pages", lambda _pdf: (pages, ocr_used))
        return parser.parse(b"not-a-real-pdf")
    return parse_pages


def test_reads_the_manifest_header(pack):
    shipment = pack([MANIFEST_PAGE, DOCKET_ONE, DOCKET_TWO])
    assert shipment["manifest_no"] == "MAN-00099001"
    assert shipment["despatch_date"] == "2026-09-10"
    assert shipment["pickup"] is True


def test_strips_scanner_confetti_out_of_the_carrier_reference(pack):
    shipment = pack([MANIFEST_PAGE, DOCKET_ONE, DOCKET_TWO])
    assert shipment["carrier_ref"] == "FRT WA - FRT100 - MP111222"


def test_finds_every_row_even_when_the_row_number_is_unreadable(pack):
    # Row one opens with "{" where the scanner lost the "1".
    shipment = pack([MANIFEST_PAGE, DOCKET_ONE, DOCKET_TWO])
    assert [c["seq"] for c in shipment["consignments"]] == [1, 2]
    assert [c["order_no"] for c in shipment["consignments"]] == ["SO-190001", "SO-190002"]


def test_corrects_a_manifest_order_number_against_the_dockets(pack):
    # The manifest scans "SO-190062"; only the docket's "SO-190002" is real.
    shipment = pack([MANIFEST_PAGE, DOCKET_ONE, DOCKET_TWO])
    assert "SO-190062" not in [c["order_no"] for c in shipment["consignments"]]


def test_rejoins_an_address_split_across_the_line_wrap(pack):
    shipment = pack([MANIFEST_PAGE, DOCKET_ONE, DOCKET_TWO])
    first = shipment["consignments"][0]
    assert first["company"] == "Northside Joinery Pty"
    assert first["address"] == "12 Example Circuit, CANNING VALE, 6155, WA"


def test_repairs_an_impossible_promised_time(pack):
    shipment = pack([MANIFEST_PAGE, DOCKET_ONE, DOCKET_TWO])
    assert shipment["consignments"][0]["promised_time"] == "11:59 PM"


def test_attaches_docket_numbers_to_their_orders(pack):
    shipment = pack([MANIFEST_PAGE, DOCKET_ONE, DOCKET_TWO])
    first, second = shipment["consignments"]
    assert (first["docket_no"], first["external_doc"]) == ("PSS-200001", "PO-055001")
    assert (second["docket_no"], second["external_doc"]) == ("PSS-200002", "PO-055002")


def test_reads_item_lines_including_an_ocr_damaged_quantity(pack):
    shipment = pack([MANIFEST_PAGE, DOCKET_ONE, DOCKET_TWO])
    lines = shipment["consignments"][1]["lines"]
    assert [(l["qty"], l["uom"]) for l in lines] == [(5, "LTHS"), (10, "LTHS")]


def test_a_decimal_in_a_description_is_not_read_as_a_quantity(pack):
    # "Angle 25 x 12 x 1.6 M" must not become a quantity of 6 metres.
    shipment = pack([MANIFEST_PAGE, DOCKET_ONE, DOCKET_TWO])
    angle = shipment["consignments"][1]["lines"][1]
    assert (angle["qty"], angle["uom"]) == (10, "LTHS")


def test_a_docket_with_no_manifest_row_is_still_carried(pack):
    orphan = DOCKET_TWO.replace("SO-190002", "SO-190777")
    shipment = pack([MANIFEST_PAGE, DOCKET_ONE, orphan])
    assert "SO-190777" in [c["order_no"] for c in shipment["consignments"]]


def test_a_pack_with_no_manifest_page_is_rejected(pack):
    with pytest.raises(parser.ManifestParseError, match="No manifest page"):
        pack([DOCKET_ONE, DOCKET_TWO])


def test_a_manifest_with_no_despatch_date_is_rejected(pack):
    with pytest.raises(parser.ManifestParseError, match="Despatch Date"):
        pack([MANIFEST_PAGE.replace("Despatch Date: 10/09/26", "Despatch Date:"), DOCKET_ONE])


def test_origin_is_read_from_the_sender_footer_not_the_delivery_address(pack):
    docket = DOCKET_ONE + "\nExample Industries Pty Ltd 23 Sample Drive EPPING VIC 3076 Australia\n"
    shipment = pack([MANIFEST_PAGE, docket, DOCKET_TWO])
    assert shipment["origin"] == "Epping VIC 3076"


def test_origin_is_left_empty_when_the_footer_is_unreadable(pack):
    # The upload screen falls back to the configured default rather than guessing.
    shipment = pack([MANIFEST_PAGE, DOCKET_ONE, DOCKET_TWO])
    assert shipment["origin"] == ""
