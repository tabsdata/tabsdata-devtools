#
# Copyright 2026 Tabsdata Inc.
#

"""SSH tunnels -- re-exported from ``common.core.ssh``; the descriptor meta keys a
connected system carries are defined there too."""

from __future__ import annotations

from tabsdata_dev.common.core.ssh import (  # noqa: F401 - re-exports
    SSH_HOST,
    SSH_PORT,
    SSH_TARGET_PORT,
    SSH_USER,
    TUNNEL_PID,
    SshEndpoint,
    close_tunnel,
    fetch_remote_file,
    is_tunnelled,
    open_tunnel,
    parse_remote_spec,
    tunnel_alive,
)
