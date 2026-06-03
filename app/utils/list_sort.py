"""Shared helpers for server-side list table sorting."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def parse_list_sort(
    args,
    allowed: frozenset[str],
    default_sort: str,
    *,
    default_dir: str = "desc",
    sort_key: str = "sort",
    dir_key: str = "dir",
) -> tuple[str, str]:
    sort = args.get(sort_key, default_sort)
    direction = args.get(dir_key, default_dir)
    if sort not in allowed:
        sort = default_sort
    if direction not in ("asc", "desc"):
        direction = default_dir
    return sort, direction


def make_toggle_sort_dir(sort: str, direction: str) -> Callable[[str], str]:
    def toggle(col: str) -> str:
        if sort == col and direction == "asc":
            return "desc"
        return "asc"

    return toggle


def sql_order(col: Any, direction: str, *, nullable: bool = False):
    order = col.asc() if direction == "asc" else col.desc()
    if nullable:
        order = order.nullsfirst() if direction == "asc" else order.nullslast()
    return order
