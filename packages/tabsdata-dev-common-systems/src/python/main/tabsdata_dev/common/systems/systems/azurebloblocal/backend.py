#
# Copyright 2026 Tabsdata Inc.
#

"""Azure Blob local backend -- the local twin of ``azureblob``: the Azure Blob
protocol (:class:`AzureStore`) in a docker-run container
(:class:`SingleContainerHosting`), served by Azurite.

The container serves the blob API on one port and keeps its data on a named
volume at ``/data``. Its account is ``USER`` and the account key the generated
``PASSWORD`` (base64, as Azure keys are); the account rides in the endpoint's
path. Create makes the ``tdd`` container, and a domain is a prefix in it, as on
Azure. Every descriptor carries the endpoint, the account and the polars /
obstore ``STORAGE_OPTIONS`` (JSON), so a reader needs nothing else.
"""

from __future__ import annotations

import base64
import secrets
from typing import ClassVar

from tabsdata_dev.common.systems.systems._common.hosting.container import images
from tabsdata_dev.common.systems.systems._common.hosting.container.single import (
    SingleContainerHosting,
)
from tabsdata_dev.common.systems.systems._common.nature.file.object.azure import (
    AzureStore,
)

CONTAINER = "tdd"


class AzureBlobLocal(SingleContainerHosting, AzureStore):
    slug = "azurebloblocal"
    label = "Azure Blob local (Azurite)"
    env_prefix = "AZLOCAL"

    image = images.AZURITE.ref
    image_platform = images.AZURITE.platform
    internal_port = 10000
    root_user = "tdd"
    volume_path = "/data"
    cmd_args: ClassVar[list[str]] = [
        "azurite-blob",
        "--blobHost",
        "0.0.0.0",
        "--blobPort",
        "10000",
        "--location",
        "/data",
        # Accept any API version a client sends, the way object_store's own CI
        # runs it: the SDKs move faster than the emulator's version list.
        "--skipApiVersionCheck",
    ]

    def generate_password(self) -> str:
        return base64.b64encode(secrets.token_bytes(32)).decode()

    def env_vars(self, password: str) -> dict[str, str]:
        return {"AZURITE_ACCOUNTS": f"{self.root_user}:{password}"}

    def ready_exec_cmd(self, password: str) -> list[str]:
        # The blob SDK's first call can take 20 s of its own retries, so ask the
        # socket rather than the API.
        return ["nc", "-z", "127.0.0.1", "10000"]

    def store_keys(self) -> tuple[str, ...]:
        return (
            "ENDPOINT",
            "CONTAINER",
            "ACCOUNT_NAME",
            "ACCOUNT_KEY",
            "STORAGE_OPTIONS",
        )

    def plan_system(
        self, name: str, overrides: dict[str, str] | None = None
    ) -> dict[str, str]:
        meta = super().plan_system(name, overrides)
        meta.update(
            {
                "ENDPOINT": f"http://{meta['HOST']}:{meta['PORT']}/{meta['USER']}",
                "CONTAINER": CONTAINER,
                "ACCOUNT_NAME": meta["USER"],
                "ACCOUNT_KEY": meta["PASSWORD"],
            }
        )
        return self.plan_store(meta)

    def provision_system(
        self, meta: dict[str, str], *, force: bool = False
    ) -> dict[str, str]:
        extra = super().provision_system(meta, force=force)
        self.configure(meta)
        self.create_bucket()
        return extra
