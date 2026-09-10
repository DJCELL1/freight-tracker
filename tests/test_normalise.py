import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import normalise


def test_finds_clean_reference():
    assert normalise.find_ref("Order No. SO-182268 Colour", "SO") == "SO-182268"


def test_repairs_ocr_damaged_prefix():
    # The scanner renders "SO-" as "S$0-" and "So-" often enough to matter.
    assert normalise.find_ref("S$0-182268", "SO") == "SO-182268"
    assert normalise.find_ref("So-182268", "SO") == "SO-182268"
    assert normalise.find_ref("S0-182268", "SO") == "SO-182268"


def test_ignores_references_of_other_kinds():
    assert normalise.find_ref("PO-047605", "SO") is None
    assert normalise.find_ref("CRI WA - CRI952 - MP236666", "SO") is None


def test_keeps_first_seen_order_and_drops_duplicates():
    text = "SO-182281 then SO-182268 then SO-182281 again"
    assert normalise.find_refs(text, "SO") == ["SO-182281", "SO-182268"]


def test_reconcile_snaps_onto_a_single_near_match():
    trusted = ["SO-182268", "SO-182281"]
    assert normalise.reconcile("SO-182287", trusted) == "SO-182281"
    assert normalise.reconcile("SO-152268", trusted) == "SO-182268"


def test_reconcile_leaves_ambiguous_and_distant_references_alone():
    # Equidistant from both: guessing would be worse than flagging for a human.
    assert normalise.reconcile("SO-182280", ["SO-182281", "SO-182288"]) == "SO-182280"
    assert normalise.reconcile("SO-999999", ["SO-182268"]) == "SO-999999"


def test_parses_day_first_dates():
    assert normalise.parse_date("10/09/26") == "2026-09-10"
    assert normalise.parse_date("10/09/2026") == "2026-09-10"
    assert normalise.parse_date("not a date") is None
    assert normalise.parse_date(None) is None


def test_reads_digit_lookalikes():
    assert normalise.to_digits("S") == "5"
    assert normalise.to_digits("1O") == "10"
