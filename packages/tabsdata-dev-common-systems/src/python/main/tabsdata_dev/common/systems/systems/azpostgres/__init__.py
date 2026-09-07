#
# Copyright 2026 Tabsdata Inc.
#

# Azure Database for PostgreSQL Flexible Server: a managed remote instance;
# domains are databases with a dedicated owner role. Only the backend is
# system-specific; every verb runs the shared command in _common/commands.

from tabsdata_dev.common.systems.systems.azpostgres.backend import AzPostgres

__all__ = ["AzPostgres"]
