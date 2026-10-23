#
# Copyright 2026 Tabsdata Inc.
#

"""Azure Blob Storage backend (azure-storage-blob) — container-prefix domains.

Config from the ``AZ__`` environment: ``AZ__ACCOUNT_NAME``, ``AZ__ACCOUNT_KEY``,
``AZ__CONTAINER``, plus ``AZ__SYS_PATH`` (staging-root prefix). Auth is the shared
account key over the HTTPS blob endpoint. Only that config lives here; the
storage ops are :class:`AzureStore`'s, shared with the local Azure emulator.
"""

from __future__ import annotations

from tabsdata_dev.common.systems import options
from tabsdata_dev.common.systems.systems._common.hosting.attached.remote import (
    RemoteHosting,
)
from tabsdata_dev.common.systems.systems._common.nature.file.object.azure import (
    AzureStore,
)


class Azureblob(RemoteHosting, AzureStore):
    slug = "azureblob"
    label = "Azure Blob"
    env_prefix = "AZ"

    def options(self) -> tuple[options.Option, ...]:
        return (
            options.Option("CONTAINER", "container", options.ENV, "env $AZ__CONTAINER"),
            options.Option(
                "ACCOUNT_NAME", "account-name", options.ENV, "env $AZ__ACCOUNT_NAME"
            ),
            options.Option(
                "ACCOUNT_KEY",
                "account-key",
                options.ENV,
                "env $AZ__ACCOUNT_KEY",
                secret=True,
            ),
            options.Option("SYS_PATH", "sys-path", options.ENV, "env $AZ__SYS_PATH"),
        )
