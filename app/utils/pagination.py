"""Shared list pagination: 10 / 50 / 100 per page (default 50)."""

from __future__ import annotations

LIST_PER_PAGE_CHOICES = (10, 50, 100)
LIST_PER_PAGE_DEFAULT = 50


def list_per_page(value) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return LIST_PER_PAGE_DEFAULT
    return n if n in LIST_PER_PAGE_CHOICES else LIST_PER_PAGE_DEFAULT


def list_page(value, total_pages: int) -> int:
    try:
        p = int(value)
    except (TypeError, ValueError):
        p = 1
    if p < 1:
        return 1
    if total_pages and p > total_pages:
        return total_pages
    return p


def pagination_page_numbers(current: int, total: int) -> list[int | None]:
    """Page numbers with None marking an ellipsis gap."""
    if total <= 7:
        return list(range(1, total + 1))
    keep = {1, total}
    for p in range(current - 2, current + 3):
        if 1 <= p <= total:
            keep.add(p)
    out: list[int | None] = []
    prev = 0
    for p in sorted(keep):
        if prev and p - prev > 1:
            out.append(None)
        out.append(p)
        prev = p
    return out


def paginate_query(query, request_args) -> tuple:
    """Count, slice, and return pagination metadata for a SQLAlchemy query."""
    per_page = list_per_page(request_args.get("per_page"))
    total = query.order_by(None).count()
    total_pages = max(1, (total + per_page - 1) // per_page) if total else 1
    page = list_page(request_args.get("page"), total_pages)
    offset = (page - 1) * per_page
    items = query.offset(offset).limit(per_page).all()
    range_start = offset + 1 if total else 0
    range_end = offset + len(items) if total else 0
    return (
        items,
        page,
        per_page,
        total,
        total_pages,
        range_start,
        range_end,
        pagination_page_numbers(page, total_pages),
    )
