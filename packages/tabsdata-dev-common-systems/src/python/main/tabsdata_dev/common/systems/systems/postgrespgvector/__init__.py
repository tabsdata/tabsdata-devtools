#
# Copyright 2026 Tabsdata Inc.
#

# postgrespgvector system: the postgres container with pgvector installed. Its
# DDL is the plain system's (ddl_from_slug); domain create adds --pgvector
# (domain/create.py), every other verb runs the shared command.

from tabsdata_dev.common.systems.systems.postgrespgvector.backend import (
    Postgrespgvector,
)

__all__ = ["Postgrespgvector"]
