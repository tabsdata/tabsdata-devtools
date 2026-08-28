#
# Copyright 2026 Tabsdata Inc.
#

"""Bounded parallelism helper, uniform across tools."""

from __future__ import annotations

import concurrent.futures
from collections.abc import Callable, Iterable
from typing import TypeVar

T = TypeVar("T")
R = TypeVar("R")


def map_bounded(fn: Callable[[T], R], items: Iterable[T], workers: int = 8) -> list[R]:
    """Apply fn across items, preserving input order."""
    items = list(items)
    if not items:
        return []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(fn, items))
