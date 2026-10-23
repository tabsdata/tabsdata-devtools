#
# Copyright 2026 Tabsdata Inc.
#

"""``Server`` -- the base of every nature served by a process at HOST:PORT.

The server is administered as the login its hosting records (``HOST``, ``PORT``,
``USER``, ``PASSWORD``; a dialect may read other keys). A domain owns its
credentials (a generated password) and is reachable when its server answers on
the domain's host and port.
"""

from __future__ import annotations

from tabsdata_dev.common.systems import constants
from tabsdata_dev.common.systems.shell import gen_password
from tabsdata_dev.common.systems.systems._common.hosting.endpoint import (
    DEFAULT_HOSTNAME,
    Admin,
)


class Server:
    supports_purge: bool = True
    supports_table_capture: bool = False

    dom_toolset: str = constants.TOOLSET_SYSTEMS

    # The server's administrator, as its hosting records it under USER.
    root_user: str = ""

    # The domain-meta key holding the address a domain is reached at.
    domain_host_key: str = "HOST"

    def _admin(self, sys_meta: dict[str, str]) -> Admin:
        return Admin(
            host=sys_meta.get("HOST", DEFAULT_HOSTNAME),
            port=sys_meta.get("PORT", ""),
            user=sys_meta.get("USER", self.root_user),
            password=sys_meta.get("PASSWORD", ""),
        )

    def new_domain_password(self) -> str:
        return gen_password()

    def domain_status(self, domain_meta: dict[str, str]) -> tuple[bool, str]:
        from tabsdata_dev.common.systems.shell import port_open

        host = domain_meta.get(self.domain_host_key, DEFAULT_HOSTNAME)
        port = domain_meta.get("PORT", "")
        ok = port.isdigit() and port_open(host, int(port))
        return (
            ok,
            f"{self.label} at {host}:{port} {'reachable' if ok else 'unreachable'}",
        )
