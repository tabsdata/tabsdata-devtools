#
# Copyright 2026 Tabsdata Inc.
#

"""GCS local backend -- the local twin of ``gcs``: the Google Cloud Storage
protocol (:class:`GcsStore`) in a docker-run container
(:class:`SingleContainerHosting`), served by cloudburrow.

Upstream publishes no image, so this one is built here from ``image/``: the
pinned upstream commit plus our patch (listings past 1000 keys, copy). Its tag
names its inputs -- the commit and a hash of the Dockerfile and the patch -- so
a create builds only when that exact image is missing, and any change to them
builds a new one. Every create and status also compares the pin with upstream's
head and says so when they differ (best effort, never failing the command): a
newer upstream may already do what the patch does.

The server keeps its data on a named volume at ``/data`` and takes no
credentials; create makes the ``tdd`` bucket, and a domain is a prefix in it,
as on GCS. Every descriptor carries the endpoint and the polars / obstore
``STORAGE_OPTIONS`` (JSON), so a reader needs nothing else.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import ClassVar

from tabsdata_dev.common.systems import console
from tabsdata_dev.common.systems.shell import docker_build, image_exists
from tabsdata_dev.common.systems.systems._common.hosting.container.single import (
    SingleContainerHosting,
)
from tabsdata_dev.common.systems.systems._common.nature.file.object.gcs import (
    GcsStore,
)

REPOSITORY = "https://github.com/cloudburrow/cloudburrow.git"
COMMIT = "73443bd32ae89248c486e70b607f1f928e5122b6"
IMAGE_DIR = Path(__file__).resolve().parent / "image"
BUCKET = "tdd"
PROJECT = "tdd"
UPSTREAM_TIMEOUT = 5


def image_tag() -> str:
    """The image's tag: the pinned commit and a hash of everything it is built
    from, so a changed input is a different image."""
    digest = hashlib.sha256(f"{REPOSITORY}\n{COMMIT}\n".encode())
    for name in ("Dockerfile", "cloudburrow.patch"):
        digest.update((IMAGE_DIR / name).read_bytes())
    return f"tdd/gcslocal:{COMMIT[:12]}-{digest.hexdigest()[:12]}"


def upstream_head() -> str:
    """Upstream's current head commit, or "" when it cannot be had quickly."""
    try:
        cp = subprocess.run(
            ["git", "ls-remote", REPOSITORY, "HEAD"],
            check=False,
            capture_output=True,
            encoding="utf-8",
            timeout=UPSTREAM_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return cp.stdout.split()[0] if cp.returncode == 0 and cp.stdout.split() else ""


def watch_upstream() -> None:
    head = upstream_head()
    if head and head != COMMIT:
        console.warn(
            f"gcslocal pins cloudburrow {COMMIT[:12]}, upstream is at {head[:12]}: "
            f"check whether upstream now lists past 1000 keys and copies, and if "
            f"so drop the patch"
        )


class GcsLocal(SingleContainerHosting, GcsStore):
    slug = "gcslocal"
    label = "GCS local (cloudburrow)"
    env_prefix = "GCSLOCAL"
    weight = 2

    image = image_tag()
    internal_port = 4443
    volume_path = "/data"
    cmd_args: ClassVar[list[str]] = ["--data-dir", "/data"]

    def fetch_images(self, done: set[str]) -> None:
        watch_upstream()
        if self.image in done:
            return
        if image_exists(self.image):
            print(f">>> using local image {self.image}")
        else:
            print(f">>> building image {self.image} (cloudburrow {COMMIT[:12]}) …")
            docker_build(
                str(IMAGE_DIR),
                self.image,
                {"REPOSITORY": REPOSITORY, "COMMIT": COMMIT},
            )
        done.add(self.image)

    def env_vars(self, password: str) -> dict[str, str]:
        return {}

    def ready_exec_cmd(self, password: str) -> list[str]:
        return ["nc", "-z", "127.0.0.1", "4443"]

    def system_status(self, meta: dict[str, str]) -> tuple[bool, str]:
        watch_upstream()
        return super().system_status(meta)

    def store_keys(self) -> tuple[str, ...]:
        return ("ENDPOINT", "BUCKET", "PROJECT", "STORAGE_OPTIONS")

    def plan_system(
        self, name: str, overrides: dict[str, str] | None = None
    ) -> dict[str, str]:
        meta = super().plan_system(name, overrides)
        meta.update(
            {
                "ENDPOINT": f"http://{meta['HOST']}:{meta['PORT']}",
                "BUCKET": BUCKET,
                "PROJECT": PROJECT,
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
