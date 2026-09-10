"""When freight that left Vic is expected to land.

The rule is deliberately simple, because it is the one the yard actually uses:
a consignment lands `transit_days` after the manifest's despatch date, five days
by default. Everything else here is presentation of that one number.
"""

from datetime import date, datetime, timedelta

DEFAULT_TRANSIT_DAYS = 5

DELIVERED = "Delivered"
OVERDUE = "Overdue"
DUE_TODAY = "Due today"
IN_TRANSIT = "In transit"


def to_date(value):
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError:
        return None


def eta_date(despatch, transit_days=DEFAULT_TRANSIT_DAYS, business_days=False, holidays=()):
    """Despatch date plus the transit allowance.

    Calendar days by default — a truck crossing the Nullarbor does not stop for
    the weekend. Set `business_days` when the transit time should count working
    days instead, in which case weekends and any date in `holidays` are skipped.
    """
    start = to_date(despatch)
    if start is None:
        return None
    if transit_days is None:
        transit_days = DEFAULT_TRANSIT_DAYS
    if not business_days:
        return start + timedelta(days=transit_days)

    holiday_dates = {to_date(h) for h in holidays}
    current = start
    remaining = transit_days
    while remaining > 0:
        current += timedelta(days=1)
        if current.weekday() < 5 and current not in holiday_dates:
            remaining -= 1
    return current


def days_out(eta, today=None):
    """Days until the ETA — negative once it is in the past."""
    eta = to_date(eta)
    if eta is None:
        return None
    return (eta - (today or date.today())).days


def status(eta, today=None, delivered_on=None):
    if to_date(delivered_on) is not None:
        return DELIVERED
    remaining = days_out(eta, today)
    if remaining is None:
        return IN_TRANSIT
    if remaining < 0:
        return OVERDUE
    if remaining == 0:
        return DUE_TODAY
    return IN_TRANSIT


def describe(eta, today=None, delivered_on=None):
    """A short human phrase for the countdown column."""
    state = status(eta, today, delivered_on)
    if state == DELIVERED:
        landed = to_date(delivered_on)
        return f"Delivered {landed:%a %d %b}" if landed else DELIVERED
    remaining = days_out(eta, today)
    if remaining is None:
        return "No despatch date"
    if remaining < 0:
        return f"{abs(remaining)} day{'s' if abs(remaining) != 1 else ''} overdue"
    if remaining == 0:
        return "Arrives today"
    if remaining == 1:
        return "Arrives tomorrow"
    return f"{remaining} days away"
