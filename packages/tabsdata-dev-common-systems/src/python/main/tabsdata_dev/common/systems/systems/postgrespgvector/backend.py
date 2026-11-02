#
# Copyright 2026 Tabsdata Inc.
#

"""PostgreSQL with pgvector installed -- the ``postgres`` container on
pgvector's build of its image, created in no database until a domain asks
(``postgres.pgvector``)."""

from __future__ import annotations

from tabsdata_dev.common.systems.systems._common.hosting.container import images
from tabsdata_dev.common.systems.systems.postgres.backend import Postgres
from tabsdata_dev.common.systems.systems.postgres.pgvector import PgvectorDomains


class Postgrespgvector(PgvectorDomains, Postgres):
    slug = "postgrespgvector"
    label = "PostgreSQL with pgvector"
    ddl_from_slug = "postgres"

    image = images.POSTGRESPGVECTOR.ref
    image_platform = images.POSTGRESPGVECTOR.platform
