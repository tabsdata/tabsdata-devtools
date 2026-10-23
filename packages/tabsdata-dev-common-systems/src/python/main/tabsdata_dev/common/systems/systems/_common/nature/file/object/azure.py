#
# Copyright 2026 Tabsdata Inc.
#

"""``AzureStore`` -- the Azure Blob Storage protocol of an :class:`ObjectStore`
(azure-storage-blob): the five storage primitives over a container.

An ``ENDPOINT`` in the config points the client at an Azure-compatible server
instead of Azure (the account in the path, as such servers expect), and
:meth:`storage_options` says the same to polars and obstore."""

from __future__ import annotations

from functools import cached_property

from tabsdata_dev.common.systems.systems._common.nature.file._base import (
    normalise_prefix,
    walk_files,
)
from tabsdata_dev.common.systems.systems._common.nature.file.object._base import (
    ObjectStore,
)


class AzureStore(ObjectStore):
    uri_scheme = "az"

    def _bucket(self) -> str:
        return self._cfg("CONTAINER")

    @cached_property
    def _container(self):
        from azure.storage.blob import BlobServiceClient

        account = self._cfg("ACCOUNT_NAME")
        endpoint = self._cfg("ENDPOINT", required=False)
        if endpoint:
            # The account rides in the path, not the host, so the client is told
            # its name rather than reading it off the URL.
            service = BlobServiceClient(
                account_url=endpoint,
                credential={
                    "account_name": account,
                    "account_key": self._cfg("ACCOUNT_KEY"),
                },
            )
        else:
            service = BlobServiceClient(
                account_url=f"https://{account}.blob.core.windows.net",
                credential=self._cfg("ACCOUNT_KEY"),
            )
        return service.get_container_client(self._cfg("CONTAINER"))

    def create_bucket(self) -> None:
        """Create the configured container; one that exists is already there."""
        from azure.core.exceptions import ResourceExistsError

        try:
            self._container.create_container()
        except ResourceExistsError:
            pass

    def storage_options(self, meta: dict[str, str]) -> dict[str, str]:
        options = {
            "azure_storage_account_name": meta.get("ACCOUNT_NAME", ""),
            "azure_storage_account_key": meta.get("ACCOUNT_KEY", ""),
        }
        endpoint = meta.get("ENDPOINT", "")
        if endpoint:
            options["azure_endpoint"] = endpoint
            options["allow_http"] = str(endpoint.startswith("http://")).lower()
        return {key: value for key, value in options.items() if value}

    def store_status(self, root: str) -> None:
        self._container.get_container_properties()

    def store_exists(self, dest: str) -> bool:
        p = normalise_prefix(dest)
        return (
            next(iter(self._container.list_blobs(name_starts_with=p)), None) is not None
        )

    def store_children(self, root: str) -> list[str]:
        p = normalise_prefix(root)
        names: list[str] = []
        for item in self._container.walk_blobs(name_starts_with=p, delimiter="/"):
            if item.name.endswith("/"):  # a BlobPrefix (child "folder")
                child = item.name[len(p) :].rstrip("/")
                if child:
                    names.append(child)
        return sorted(names)

    def store_clear(self, dest: str) -> None:
        p = normalise_prefix(dest)
        names = [b.name for b in self._container.list_blobs(name_starts_with=p)]
        for i in range(0, len(names), 256):
            self._container.delete_blobs(*names[i : i + 256])

    def store_upload(self, dest: str, local_dir: str) -> int:
        p = normalise_prefix(dest)
        n = 0
        for src, rel in walk_files(local_dir):
            with open(src, "rb") as f:
                self._container.upload_blob(name=p + rel, data=f, overwrite=True)
            n += 1
        return n
