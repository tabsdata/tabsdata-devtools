#
# Copyright 2026 Tabsdata Inc.
#

"""Amazon S3 backend (boto3) — object-store domains as bucket prefixes.

Config from the ``S3__`` environment: ``S3__BUCKET``, ``S3__REGION``,
``S3__ACCESS_KEY``, ``S3__SECRET_KEY`` (blank keys fall back to boto3's default
credential chain), ``S3__SYS_PATH`` (staging-root prefix). Only that config lives here; the
storage ops are :class:`S3Store`'s, shared with the local S3 emulator.
"""

from __future__ import annotations

from tabsdata_dev.common.systems import options
from tabsdata_dev.common.systems.systems._common.hosting.attached.remote import (
    RemoteHosting,
)
from tabsdata_dev.common.systems.systems._common.nature.file.object.s3 import S3Store


class S3(RemoteHosting, S3Store):
    slug = "s3"
    label = "S3"
    env_prefix = "S3"

    def options(self) -> tuple[options.Option, ...]:
        return (
            options.Option("BUCKET", "bucket", options.ENV, "env $S3__BUCKET"),
            options.Option(
                "REGION", "region", options.ENV, "env $S3__REGION", required=False
            ),
            options.Option(
                "ACCESS_KEY",
                "access-key",
                options.ENV,
                "env $S3__ACCESS_KEY (else boto3 default chain)",
                secret=True,
                required=False,
            ),
            options.Option(
                "SECRET_KEY",
                "secret-key",
                options.ENV,
                "env $S3__SECRET_KEY (else boto3 default chain)",
                secret=True,
                required=False,
            ),
            options.Option("SYS_PATH", "sys-path", options.ENV, "env $S3__SYS_PATH"),
        )
