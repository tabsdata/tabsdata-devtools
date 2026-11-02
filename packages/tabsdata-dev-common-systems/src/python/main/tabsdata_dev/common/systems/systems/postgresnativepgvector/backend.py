#
# Copyright 2026 Tabsdata Inc.
#

"""PostgreSQL run natively with pgvector installed -- ``postgresnative`` with
pgvector in its tree, created in no database until a domain asks
(``postgres.pgvector``)."""

from __future__ import annotations

from typing import ClassVar

from tabsdata_dev.common.systems.systems.postgres.pgvector import PgvectorDomains
from tabsdata_dev.common.systems.systems.postgresnative.backend import PostgresNative


class PostgresNativePgvector(PgvectorDomains, PostgresNative):
    slug = "postgresnativepgvector"
    label = "PostgreSQL with pgvector (native)"

    pgvector: ClassVar[bool] = True
