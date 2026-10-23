#
# Copyright 2026 Tabsdata Inc.
#

"""Google Cloud Storage backend (google-cloud-storage) — bucket-prefix domains.

Config from the ``GCS__`` environment: ``GCS__BUCKET`` and
``GCS__SERVICE_ACCOUNT_KEY`` (inline JSON — starts with ``{`` — or a file path),
plus ``GCS__SYS_PATH`` (staging-root prefix). The S3-interop HMAC keys
(``GCS__HMAC_ACCESS_KEY`` / ``GCS__HMAC_SECRET_KEY``) are carried in the descriptor
for consumers that reach GCS over the S3 protocol (ClickHouse / StarRocks
staging); the storage ops use the service-account key. Only that config lives
here; the storage ops are :class:`GcsStore`'s, shared with the local GCS emulator.
"""

from __future__ import annotations

from tabsdata_dev.common.systems import options
from tabsdata_dev.common.systems.systems._common.hosting.attached.remote import (
    RemoteHosting,
)
from tabsdata_dev.common.systems.systems._common.nature.file.object.gcs import GcsStore


class GCS(RemoteHosting, GcsStore):
    slug = "gcs"
    label = "GCS"
    env_prefix = "GCS"

    def options(self) -> tuple[options.Option, ...]:
        return (
            options.Option("BUCKET", "bucket", options.ENV, "env $GCS__BUCKET"),
            options.Option(
                "SERVICE_ACCOUNT_KEY",
                "service-account-key",
                options.ENV,
                "env $GCS__SERVICE_ACCOUNT_KEY (inline JSON or a file path)",
                secret=True,
            ),
            # S3-interop (HMAC) credentials, baked into the descriptor for consumers
            # that reach GCS over the S3 protocol (ClickHouse / StarRocks staging).
            # Optional: a GCS system without S3-interop keys still creates.
            options.Option(
                "HMAC_ACCESS_KEY",
                "hmac-access-key",
                options.ENV,
                "env $GCS__HMAC_ACCESS_KEY (S3-interop access key)",
                # Half of a credential pair, like S3's own ACCESS_KEY: never a
                # value a manifest may re-emit in clear.
                secret=True,
                required=False,
            ),
            options.Option(
                "HMAC_SECRET_KEY",
                "hmac-secret-key",
                options.ENV,
                "env $GCS__HMAC_SECRET_KEY (S3-interop secret key)",
                secret=True,
                required=False,
            ),
            options.Option("SYS_PATH", "sys-path", options.ENV, "env $GCS__SYS_PATH"),
        )
