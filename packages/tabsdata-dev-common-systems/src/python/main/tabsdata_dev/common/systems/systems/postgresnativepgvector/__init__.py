#
# Copyright 2026 Tabsdata Inc.
#

# postgresnativepgvector system: postgresnative with pgvector installed in its
# tree. Its DDL is the plain system's (ddl_from_slug); domain create adds
# --pgvector (domain/create.py), every other verb runs the shared command.

from tabsdata_dev.common.systems.systems.postgresnativepgvector.backend import (
    PostgresNativePgvector,
)

__all__ = ["PostgresNativePgvector"]
