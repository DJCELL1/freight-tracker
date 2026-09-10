import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import eta


def test_default_rule_is_five_calendar_days():
    assert eta.eta_date("2026-09-10") == date(2026, 9, 15)


def test_calendar_days_run_through_the_weekend():
    # Thursday 10 Sep + 5 calendar days lands on Tuesday.
    assert eta.eta_date(date(2026, 9, 10), 5) == date(2026, 9, 15)


def test_business_days_skip_weekends():
    assert eta.eta_date(date(2026, 9, 10), 5, business_days=True) == date(2026, 9, 17)


def test_business_days_skip_holidays():
    holidays = {date(2026, 9, 14)}
    assert eta.eta_date(date(2026, 9, 10), 5, business_days=True, holidays=holidays) == date(2026, 9, 18)


def test_missing_despatch_date_has_no_eta():
    assert eta.eta_date(None) is None
    assert eta.eta_date("") is None


def test_status_tracks_the_calendar():
    due = date(2026, 9, 15)
    assert eta.status(due, today=date(2026, 9, 12)) == eta.IN_TRANSIT
    assert eta.status(due, today=date(2026, 9, 15)) == eta.DUE_TODAY
    assert eta.status(due, today=date(2026, 9, 16)) == eta.OVERDUE


def test_delivered_beats_every_other_status():
    due = date(2026, 9, 15)
    assert eta.status(due, today=date(2026, 9, 30), delivered_on="2026-09-14") == eta.DELIVERED


def test_countdown_phrasing():
    due = date(2026, 9, 15)
    assert eta.describe(due, today=date(2026, 9, 15)) == "Arrives today"
    assert eta.describe(due, today=date(2026, 9, 14)) == "Arrives tomorrow"
    assert eta.describe(due, today=date(2026, 9, 12)) == "3 days away"
    assert eta.describe(due, today=date(2026, 9, 16)) == "1 day overdue"
