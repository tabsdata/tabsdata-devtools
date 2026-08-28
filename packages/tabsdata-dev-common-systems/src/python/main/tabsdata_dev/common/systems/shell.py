#
# Copyright 2026 Tabsdata Inc.
#

"""Docker, ports and passwords -- re-exported from ``common.core`` so the
backends keep importing them from here. Only ``validate_name`` is local."""

from __future__ import annotations

from tabsdata_dev.common.core.docker import (  # noqa: F401 - re-exports
    compose_container_ids,
    container_exists,
    container_id,
    container_state,
    docker_compose,
    docker_exec,
    docker_exec_check,
    docker_pull,
    docker_restart,
    docker_rm,
    docker_run,
    docker_start,
    docker_stop,
    require_docker,
)
from tabsdata_dev.common.core.passwords import gen_password  # noqa: F401
from tabsdata_dev.common.core.ports import (  # noqa: F401 - re-exports
    find_free_port,
    find_free_ports,
    http_ok,
    port_open,
)

from tabsdata_dev.common.systems.errors import TdxError


def validate_name(name: str, label: str = "name") -> None:
    if not name:
        raise TdxError(f"{label} is empty")
    for ch in name:
        if not (ch.isalnum() or ch == "_"):
            raise TdxError(f"{label} must be alphanumeric/underscore (got: {name})")
