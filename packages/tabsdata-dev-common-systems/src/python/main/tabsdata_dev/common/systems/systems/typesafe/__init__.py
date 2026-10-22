#
# Copyright 2026 Tabsdata Inc.
#

# typesafe system. Only the backend + create command are system-specific; every other
# verb runs the shared command in _common/commands.

from tabsdata_dev.common.systems.systems.typesafe.backend import TypeSafe

__all__ = ["TypeSafe"]
