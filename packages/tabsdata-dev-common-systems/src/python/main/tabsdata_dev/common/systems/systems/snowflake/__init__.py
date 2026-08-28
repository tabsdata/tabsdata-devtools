#
# Copyright 2026 Tabsdata Inc.
#

# Snowflake system: a remote warehouse; domains are schemas in the account
# database. Only the backend + create command are system-specific; every other
# verb runs the shared command in _common/commands.

from tabsdata_dev.common.systems.systems.snowflake.backend import Snowflake

__all__ = ["Snowflake"]
