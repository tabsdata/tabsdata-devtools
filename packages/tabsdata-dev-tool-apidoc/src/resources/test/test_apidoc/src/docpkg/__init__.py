#
# Copyright 2026 Tabsdata Inc.
#
"""The docpkg package."""

from docpkg._impl import Hidden, Widget

__all__ = ["Widget", "Hidden", "publish"]


def publish(count: int, name: "str" = "x") -> str:
    """Publish some rows.

    :categories: source

    Args:
        count: How many rows.
        name: What to call them.

    Returns:
        The name used.

    Examples:
        Plainly:

        .. code-block:: python

            publish(3)
    """
    return name
