"""
utils/__init__.py
-----------------
Shared utility functions and helpers used across the application.
"""


def format_currency(value):
    """Format a number as currency string (e.g., 1234.5 → '₹1,234.50')."""
    if value is None:
        return '₹0.00'
    return f'₹{value:,.2f}'


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

