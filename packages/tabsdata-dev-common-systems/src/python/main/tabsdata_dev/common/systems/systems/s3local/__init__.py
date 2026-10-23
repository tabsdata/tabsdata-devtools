#
# Copyright 2026 Tabsdata Inc.
#

# s3local system. Only the backend + create command are system-specific; every other
# verb runs the shared command in _common/commands.

from tabsdata_dev.common.systems.systems.s3local.backend import S3Local

__all__ = ["S3Local"]
