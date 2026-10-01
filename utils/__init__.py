import zoneinfo
from datetime import datetime, timezone, timedelta

# Indian Standard Time (Asia/Kolkata: UTC+05:30)
try:
    IST = zoneinfo.ZoneInfo('Asia/Kolkata')
except Exception:
    IST = timezone(timedelta(hours=5, minutes=30))


def to_ist(dt):
    """Convert a naive UTC or aware datetime object to IST (Asia/Kolkata)."""
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(IST)
    return dt


def format_datetime(value, fmt='%d %b %Y, %I:%M %p IST'):
    """Format a datetime value into IST string (e.g., '25 Aug 2026, 08:30 PM IST')."""
    if not value:
        return ''
    dt = to_ist(value)
    return dt.strftime(fmt)



def format_currency(value):
    """Format a number as currency string (e.g., 1234.5 → '$1,234.50')."""
    if value is None:
        return '$0.00'
    return f'${value:,.2f}'


def format_quantity(value):
    """Format quantity with commas (e.g., 10000 → '10,000')."""
    if value is None:
        return '0'
    return f'{value:,}'


class Pagination:
    """
    Simple pagination helper compatible with Flask-SQLAlchemy's Pagination API.
    Supports iter_pages() for template rendering.
    """

    def __init__(self, page, per_page, total):
        self.page = page
        self.per_page = per_page
        self.total = total
        self.pages = max(1, (total + per_page - 1) // per_page)
        self.has_prev = page > 1
        self.has_next = page < self.pages
        self.prev_num = page - 1
        self.next_num = page + 1

    def iter_pages(self, left_edge=2, left_current=2, right_current=5, right_edge=2):
        """Yield page numbers for pagination rendering, using None as gap marker."""
        last = 0
        for num in range(1, self.pages + 1):
            if (
                num <= left_edge
                or (self.page - left_current - 1 < num < self.page + right_current)
                or num > self.pages - right_edge
            ):
                if last + 1 != num:
                    yield None
                yield num
                last = num

