#
# Copyright 2026 Tabsdata Inc.
#

# postgresnative system: PostgreSQL run natively from downloaded binaries. Its
# DDL is the plain system's (ddl_from_slug); every verb runs the shared command.

from tabsdata_dev.common.systems.systems.postgresnative.backend import PostgresNative

__all__ = ["PostgresNative"]
