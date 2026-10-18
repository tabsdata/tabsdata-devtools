#
# Copyright 2026 Tabsdata Inc.
#
class Widget:
    """A widget.

    :categories: destination

    Args:
        label: What it shows.
    """

    def __init__(self, label: str):
        self.label = label

    def spin(self) -> None:
        """Spin it."""

    @property
    def size(self) -> int:
        """How big it is."""
        return 1


class Hidden:
    """Re-exported but not on the allow-list."""
