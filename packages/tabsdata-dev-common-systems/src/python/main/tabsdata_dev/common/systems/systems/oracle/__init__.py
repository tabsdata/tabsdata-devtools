#
# Copyright 2026 Tabsdata Inc.
#

# oracle system: docker-run container. Only the dialect backend is system-specific;
# every verb runs the shared command in systems/_common/commands.

from tabsdata_dev.common.systems.systems.oracle.backend import Oracle

__all__ = ["Oracle"]
