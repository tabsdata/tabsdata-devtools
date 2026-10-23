#
# Copyright 2026 Tabsdata Inc.
#

# azurebloblocal system. Only the backend + create command are system-specific; every
# other verb runs the shared command in _common/commands.

from tabsdata_dev.common.systems.systems.azurebloblocal.backend import AzureBlobLocal

__all__ = ["AzureBlobLocal"]
