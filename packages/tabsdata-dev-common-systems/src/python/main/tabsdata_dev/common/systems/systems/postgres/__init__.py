#
# Copyright 2026 Tabsdata Inc.
#

# PostgreSQL system: docker-run container + per-domain database. Only the dialect
# backend is system-specific; every verb runs the shared command in
# systems/_common/commands.

from tabsdata_dev.common.systems.systems.postgres.backend import Postgres

__all__ = ["Postgres"]
