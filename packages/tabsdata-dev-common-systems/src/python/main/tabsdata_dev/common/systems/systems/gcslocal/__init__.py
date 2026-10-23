#
# Copyright 2026 Tabsdata Inc.
#

# gcslocal system. Only the backend + create command are system-specific; every other
# verb runs the shared command in _common/commands.

from tabsdata_dev.common.systems.systems.gcslocal.backend import GcsLocal

__all__ = ["GcsLocal"]
