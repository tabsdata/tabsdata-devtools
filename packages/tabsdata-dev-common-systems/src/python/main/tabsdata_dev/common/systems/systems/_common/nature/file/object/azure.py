#
# Copyright 2026 Tabsdata Inc.
#

"""``AzureStore`` -- the Azure Blob Storage protocol of an :class:`ObjectStore`
(azure-storage-blob): the five storage primitives over a container."""

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
        service = BlobServiceClient(
            account_url=f"https://{account}.blob.core.windows.net",
            credential=self._cfg("ACCOUNT_KEY"),
        )
        return service.get_container_client(self._cfg("CONTAINER"))

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
