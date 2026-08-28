#
# Copyright 2026 Tabsdata Inc.
#

# dev system. Only the backend + create command are system-specific; every other
# verb runs the shared command in _common/commands.

from tabsdata_dev.common.systems.systems.dev.backend import Dev

__all__ = ["Dev"]
