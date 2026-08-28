#
# Copyright 2026 Tabsdata Inc.
#

# starrocks system: docker-run container. Only the dialect backend is system-specific;
# every verb runs the shared command in systems/_common/commands.

from tabsdata_dev.common.systems.systems.starrocks.backend import Starrocks

__all__ = ["Starrocks"]
