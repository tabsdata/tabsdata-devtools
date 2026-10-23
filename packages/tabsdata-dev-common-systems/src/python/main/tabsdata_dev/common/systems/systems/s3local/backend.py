#
# Copyright 2026 Tabsdata Inc.
#

"""S3 local backend -- the local twin of ``s3``: the S3 protocol
(:class:`S3Store`) in a docker-run container (:class:`SingleContainerHosting`),
served by RustFS.

The container serves S3 on one port, keeps its data on a named volume at
``/data`` and needs at least 2 GiB of memory (it is killed at 1 GiB under a
large parquet sink). Its access key is ``USER`` and its secret key the generated
``PASSWORD``; create makes the ``tdd`` bucket, and a domain is a prefix in it,
as on S3. Every descriptor carries the endpoint, the keys and the polars /
obstore ``STORAGE_OPTIONS`` (JSON), so a reader needs nothing else.
"""

from __future__ import annotations

from typing import ClassVar

from tabsdata_dev.common.systems.systems._common.hosting.container import images
from tabsdata_dev.common.systems.systems._common.hosting.container.single import (
    SingleContainerHosting,
)
from tabsdata_dev.common.systems.systems._common.nature.file.object.s3 import S3Store

BUCKET = "tdd"
REGION = "us-east-1"


class S3Local(SingleContainerHosting, S3Store):
    slug = "s3local"
    label = "S3 local (RustFS)"
    env_prefix = "S3LOCAL"
    weight = 2

    image = images.RUSTFS.ref
    image_platform = images.RUSTFS.platform
    internal_port = 9000
    root_user = "tdd"
    volume_path = "/data"
    extra_run_flags: ClassVar[list[str]] = ["--memory", "2g"]

    def env_vars(self, password: str) -> dict[str, str]:
        return {"RUSTFS_ACCESS_KEY": self.root_user, "RUSTFS_SECRET_KEY": password}

    def ready_exec_cmd(self, password: str) -> list[str]:
        return ["curl", "-fsS", "-o", "/dev/null", "http://127.0.0.1:9000/health"]

    def store_keys(self) -> tuple[str, ...]:
        return (
            "ENDPOINT",
            "BUCKET",
            "REGION",
            "ACCESS_KEY",
            "SECRET_KEY",
            "STORAGE_OPTIONS",
        )

    def plan_system(
        self, name: str, overrides: dict[str, str] | None = None
    ) -> dict[str, str]:
        meta = super().plan_system(name, overrides)
        meta.update(
            {
                "ENDPOINT": f"http://{meta['HOST']}:{meta['PORT']}",
                "BUCKET": BUCKET,
                "REGION": REGION,
                "ACCESS_KEY": meta["USER"],
                "SECRET_KEY": meta["PASSWORD"],
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
