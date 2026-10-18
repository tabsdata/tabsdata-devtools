#
# Copyright 2026 Tabsdata Inc.
#
"""Listen on 127.0.0.1 at the LOCAL port of argv[1], LOCAL:REMOTE, until
killed: the end of a port-forward a probe can reach."""

import socket
import sys
import time

LIFETIME_SECONDS = 300

local = int(sys.argv[1].split(":")[0])
server = socket.socket()
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(("127.0.0.1", local))
server.listen()
time.sleep(LIFETIME_SECONDS)
