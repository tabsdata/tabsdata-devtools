#
# Copyright 2026 Tabsdata Inc.
#

"""``DocumentDatabase`` -- the nature of document databases (mongodb).

A domain is a database with its own owner. There is no tdd data plane yet: the
connector under test loads its own documents, so only create, destroy, status
and purge are exposed.
"""

from __future__ import annotations

from tabsdata_dev.common.systems.systems._common.nature.server._base import Server


class DocumentDatabase(Server):
    nature: str = "document_database"
    kind: str = "document"
    domain_word: str = "database"
    supports_models: bool = False
    supports_data: bool = False
    supports_changes: bool = False
    supports_trx_modes: bool = False
