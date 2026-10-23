#
# Copyright 2026 Tabsdata Inc.
#

"""``S3Store`` -- the S3 protocol of an :class:`ObjectStore` (boto3): the five
storage primitives over a bucket, for Amazon S3 and any S3-compatible store.

An ``ENDPOINT`` in the config points the client at an S3-compatible server
instead of AWS (path-style addressing, as such servers expect), and
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


class S3Store(ObjectStore):
    uri_scheme = "s3"

    def _bucket(self) -> str:
        return self._cfg("BUCKET")

    @cached_property
    def _client(self):
        import boto3
        from botocore.config import Config

        endpoint = self._cfg("ENDPOINT", required=False)
        return boto3.client(
            "s3",
            region_name=self._cfg("REGION", required=False) or None,
            aws_access_key_id=self._cfg("ACCESS_KEY", required=False) or None,
            aws_secret_access_key=self._cfg("SECRET_KEY", required=False) or None,
            endpoint_url=endpoint or None,
            config=Config(s3={"addressing_style": "path"}) if endpoint else None,
        )

    def create_bucket(self) -> None:
        """Create the configured bucket; one this account already owns is
        already there."""
        from botocore.exceptions import ClientError

        try:
            self._client.create_bucket(Bucket=self._bucket())
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                raise

    def storage_options(self, meta: dict[str, str]) -> dict[str, str]:
        options = {
            "aws_access_key_id": meta.get("ACCESS_KEY", ""),
            "aws_secret_access_key": meta.get("SECRET_KEY", ""),
            "aws_region": meta.get("REGION", ""),
        }
        endpoint = meta.get("ENDPOINT", "")
        if endpoint:
            options["aws_endpoint_url"] = endpoint
            options["aws_allow_http"] = str(endpoint.startswith("http://")).lower()
        return {key: value for key, value in options.items() if value}

    def store_status(self, root: str) -> None:
        self._client.head_bucket(Bucket=self._bucket())

    def store_exists(self, dest: str) -> bool:
        resp = self._client.list_objects_v2(
            Bucket=self._bucket(), Prefix=normalise_prefix(dest), MaxKeys=1
        )
        return resp.get("KeyCount", 0) > 0

    def store_children(self, root: str) -> list[str]:
        p = normalise_prefix(root)
        names: list[str] = []
        for page in self._client.get_paginator("list_objects_v2").paginate(
            Bucket=self._bucket(), Prefix=p, Delimiter="/"
        ):
            for cp in page.get("CommonPrefixes", []) or []:
                child = cp.get("Prefix", "")[len(p) :].rstrip("/")
                if child:
                    names.append(child)
        return sorted(names)

    def store_clear(self, dest: str) -> None:
        p = normalise_prefix(dest)
        bucket = self._bucket()
        for page in self._client.get_paginator("list_objects_v2").paginate(
            Bucket=bucket, Prefix=p
        ):
            objs = [{"Key": o["Key"]} for o in page.get("Contents", []) or []]
            for i in range(0, len(objs), 1000):
                self._client.delete_objects(
                    Bucket=bucket, Delete={"Objects": objs[i : i + 1000]}
                )

    def store_upload(self, dest: str, local_dir: str) -> int:
        p = normalise_prefix(dest)
        bucket = self._bucket()
        n = 0
        for src, rel in walk_files(local_dir):
            self._client.upload_file(str(src), bucket, p + rel)
            n += 1
        return n
