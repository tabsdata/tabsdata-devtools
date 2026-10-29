#
# Copyright 2026 Tabsdata Inc.
#

"""``ContainerHosting`` -- what every local-Docker system shares: the ``tdd_``
names, the host port slot and hostname, the readiness timeout, and getting its
images onto this machine.
"""

from __future__ import annotations

from tabsdata_dev.common.systems import constants
from tabsdata_dev.common.systems.shell import docker_pull
from tabsdata_dev.common.systems.systems._common.hosting.container.hostname import (
    HostMixin,
)
from tabsdata_dev.common.systems.systems._common.hosting.container.ports import (
    PortRangeMixin,
)


class ContainerHosting(PortRangeMixin, HostMixin):
    hosting: str = "container"
    is_container: bool = True
    supports_restart: bool = True
    fetches_binaries: bool = True
    advertises_host: bool = True

    slug: str = ""
    label: str = ""
    weight: int = 1
    exclusive: bool = False

    # Starting and probing a container is docker-only (readiness runs as an
    # in-container CLI), so the lifecycle needs no driver.
    sys_toolset: str = constants.TOOLSET_SYSTEMS

    ready_timeout: int = 300

    def fetch_bin(self, done: set[str]) -> None:
        """`fetch-bin`: a container system's binaries are its images."""
        self.fetch_images(done)

    def fetch_images(self, done: set[str]) -> None:
        """Get this system's images onto this machine, skipping those in `done`
        and adding what it fetched. Default: pull each from its registry; a
        system whose image is built here, not published, builds it instead."""
        for image, platform in self.docker_images():
            if image in done:
                continue
            print(f">>> pulling docker image {image} …", flush=True)
            docker_pull(image, platform)
            done.add(image)
