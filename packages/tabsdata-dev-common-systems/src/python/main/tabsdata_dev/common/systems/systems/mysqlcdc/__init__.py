#
# Copyright 2026 Tabsdata Inc.
#

# mysqlcdc system: a CDC variant of the plain SQL system; reuses that system's model
# DDL via ddl_from_slug. Every verb runs the shared command in _common/commands.

from tabsdata_dev.common.systems.systems.mysqlcdc.backend import Mysqlcdc

__all__ = ["Mysqlcdc"]
