#
# Copyright 2026 Tabsdata Inc.
#

"""``Messaging`` -- the nature of message brokers (redpanda, redpandasasl).

A domain is a set of topics. A broker log only appends, so modify-data inserts
and nothing else, and a batch is produced whole, with no transactions to
schedule. The broker supplies its own admin client, topic lifecycle and
producer; dropping a model drops the domain's topics.
"""

from __future__ import annotations

from tabsdata_dev.common.systems.systems._common.nature.server._base import Server


class Messaging(Server):
    nature: str = "messaging"
    kind: str = "messaging"
    domain_word: str = "topic"
    supports_models: bool = True
    supports_data: bool = True
    supports_changes: bool = True
    supports_trx_modes: bool = False

    def uninstall_schema(self, meta: dict[str, str], model: str) -> None:
        with self.data_plane_uri(meta) as uri:
            self.drop_all_tables(uri)
        print(f">>> model '{model}' removed")
