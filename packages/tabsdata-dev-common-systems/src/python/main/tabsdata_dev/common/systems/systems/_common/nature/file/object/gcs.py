#
# Copyright 2026 Tabsdata Inc.
#

"""``GcsStore`` -- the Google Cloud Storage protocol of an :class:`ObjectStore`
(google-cloud-storage): the five storage primitives over a bucket.

An ``ENDPOINT`` in the config points the client at a GCS-compatible server
instead of Google, unauthenticated (``PROJECT`` names the project it files
buckets under), and :meth:`storage_options` says the same to polars and
obstore."""

from __future__ import annotations

import json
from functools import cached_property

from tabsdata_dev.common.systems.systems._common.nature.file._base import (
    normalise_prefix,
    walk_files,
)
from tabsdata_dev.common.systems.systems._common.nature.file.object._base import (
    ObjectStore,
)


class GcsStore(ObjectStore):
    uri_scheme = "gs"

    def _bucket(self) -> str:
        return self._cfg("BUCKET")

    @cached_property
    def _client(self):
        from google.cloud import storage  # type: ignore[import-untyped]

        endpoint = self._cfg("ENDPOINT", required=False)
        if endpoint:
            from google.auth.credentials import AnonymousCredentials

            return storage.Client(
                project=self._cfg("PROJECT"),
                credentials=AnonymousCredentials(),
                client_options={"api_endpoint": endpoint},
            )
        sa = self._cfg("SERVICE_ACCOUNT_KEY")
        if sa.lstrip().startswith("{"):
            return storage.Client.from_service_account_info(json.loads(sa))
        return storage.Client.from_service_account_json(sa)

    def create_bucket(self) -> None:
        """Create the configured bucket; one already there is fine."""
        from google.api_core.exceptions import Conflict

        try:
            self._client.create_bucket(self._bucket())
        except Conflict:
            pass

    def storage_options(self, meta: dict[str, str]) -> dict[str, str]:
        endpoint = meta.get("ENDPOINT", "")
        if endpoint:
            # object_store reaches a GCS-compatible server through a service
            # account that names its base URL and turns OAuth off.
            account = {
                "gcs_base_url": endpoint,
                "disable_oauth": True,
                "client_email": "",
                "private_key": "",
                "private_key_id": "",
            }
            return {
                "google_service_account_key": json.dumps(account),
                "allow_http": str(endpoint.startswith("http://")).lower(),
            }
        sa = meta.get("SERVICE_ACCOUNT_KEY", "")
        if not sa:
            return {}
        if sa.lstrip().startswith("{"):
            return {"google_service_account_key": sa}
        return {"google_service_account": sa}

    def store_status(self, root: str) -> None:
        # Object-level probe (least-priv SAs may lack buckets.get).
        next(iter(self._client.list_blobs(self._bucket(), max_results=1)), None)

    def store_exists(self, dest: str) -> bool:
        p = normalise_prefix(dest)
        return any(self._client.list_blobs(self._bucket(), prefix=p, max_results=1))

    def store_children(self, root: str) -> list[str]:
        p = normalise_prefix(root)
        it = self._client.list_blobs(self._bucket(), prefix=p, delimiter="/")
        for _ in it:  # exhaust so `prefixes` is populated
            pass
        names = [cp[len(p) :].rstrip("/") for cp in it.prefixes]
        return sorted(n for n in names if n)

    def store_clear(self, dest: str) -> None:
        p = normalise_prefix(dest)
        for blob in list(self._client.list_blobs(self._bucket(), prefix=p)):
            blob.delete()

    def store_upload(self, dest: str, local_dir: str) -> int:
        bucket = self._client.bucket(self._bucket())
        p = normalise_prefix(dest)
        n = 0
        for src, rel in walk_files(local_dir):
            bucket.blob(p + rel).upload_from_filename(str(src))
            n += 1
        return n
