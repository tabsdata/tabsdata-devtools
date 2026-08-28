#
# Copyright 2026 Tabsdata Inc.
#

# postgrescdc system: a CDC variant of the plain SQL system; reuses that system's model
# DDL via ddl_from_slug. Every verb runs the shared command in _common/commands.

from tabsdata_dev.common.systems.systems.postgrescdc.backend import Postgrescdc

__all__ = ["Postgrescdc"]
