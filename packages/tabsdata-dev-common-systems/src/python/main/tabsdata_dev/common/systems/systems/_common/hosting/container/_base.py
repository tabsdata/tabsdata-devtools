#
# Copyright 2026 Tabsdata Inc.
#

"""``ContainerHosting`` -- what every local-Docker system shares: the ``tdd_``
names, the host port slot and hostname, the readiness timeout.
"""

from __future__ import annotations

from tabsdata_dev.common.systems import constants
from tabsdata_dev.common.systems.systems._common.hosting.container.hostname import (
    HostMixin,
)
from tabsdata_dev.common.systems.systems._common.hosting.container.ports import (
    PortRangeMixin,
)


class ContainerHosting(PortRangeMixin, HostMixin):
    hosting: str = "container"
    is_container: bool = True

    slug: str = ""
    label: str = ""
    weight: int = 1
    exclusive: bool = False

    # Starting and probing a container is docker-only (readiness runs as an
    # in-container CLI), so the lifecycle needs no driver.
    sys_toolset: str = constants.TOOLSET_SYSTEMS

    ready_timeout: int = 300
