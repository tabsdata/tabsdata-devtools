#
# Copyright 2026 Tabsdata Inc.
#

"""Create a domain (an entity-container + owner) in a system.

The shared create, with ``--pgvector on|off`` (default off): on, the extension
is created in the domain's database, which the server already has installed.
The choice is recorded in the domain's meta (``PGVECTOR``), so ``manifest``
replays it.
"""

from tabsdata_dev.common.systems.systems.postgres.pgvector import add_arguments, run

__all__ = ["add_arguments", "run"]
