"""Free host ports and reachability probes.

Ports never come from ``bind(("", 0))``: that hands out an *ephemeral* port
(macOS 49152-65535, Linux 32768-60999 by default), the very pool every outgoing
connection draws from, so in the seconds between finding one and `docker run`
binding it a docker pull or kubectl would routinely take it ("failed to bind
host port 0.0.0.0:59718/tcp: address already in use"). Everything here lives
below 32768: 20000-29999 belongs to the systems, a hundred ports each in a fixed
slot per system type (`common.systems.systems._common.hosting.container.ports`), so two creates
never look at the same ports; PORT_RANGE is for everything else (an ssh tunnel's
local end), walked from a random start so two tdd processes rarely meet. A
candidate is checked with a plain bind -- no SO_REUSEADDR: a port in TIME_WAIT
is not free for docker either.
"""

from __future__ import annotations

import random
import socket
from collections.abc import Iterable

from .errors import ToolError

PORT_RANGE = (30000, 32767)


def is_free(port: int) -> bool:
    """Whether nothing on this host has `port` bound right now."""
    s = socket.socket()
    try:
        s.bind(("", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def find_free_ports(
    count: int,
    port_range: tuple[int, int] = PORT_RANGE,
    *,
    exclude: Iterable[int] = (),
    from_start: bool = False,
) -> list[int]:
    """`count` *distinct* free ports in `port_range`, none in `exclude`, found by
    holding every candidate socket open at once, then releasing them. The ports
    are free (not reserved) when returned. The walk starts at random unless
    `from_start`, which gives a caller with a range of its own stable ports."""
    lo, hi = port_range
    span = hi - lo + 1
    start = 0 if from_start else random.randrange(span)
    skip = set(exclude)
    socks: list[socket.socket] = []
    try:
        for i in range(span):
            if len(socks) >= max(0, count):
                break
            port = lo + (start + i) % span
            if port in skip:
                continue
            s = socket.socket()
            try:
                s.bind(("", port))
            except OSError:
                s.close()
                continue
            socks.append(s)
        if len(socks) < count:
            raise ToolError(f"could not find {count} free port(s) in {lo}-{hi}")
        return [s.getsockname()[1] for s in socks]
    finally:
        for s in socks:
            s.close()


def find_free_port(
    port_range: tuple[int, int] = PORT_RANGE,
    *,
    exclude: Iterable[int] = (),
    from_start: bool = False,
) -> int:
    return find_free_ports(1, port_range, exclude=exclude, from_start=from_start)[0]


def port_open(host: str, port: int, timeout: float = 3.0) -> bool:
    """True if a TCP connection to host:port succeeds within `timeout` seconds."""
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def http_ok(
    url: str,
    timeout: float = 5.0,
    *,
    user: str | None = None,
    password: str | None = None,
) -> bool:
    """True if a GET to `url` returns a 2xx within `timeout`s (an HTTP readiness
    probe). With `user`, sends HTTP basic-auth."""
    import base64
    import urllib.request

    req = urllib.request.Request(url)
    if user is not None:
        token = base64.b64encode(f"{user}:{password or ''}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception:  # noqa: BLE001 - any failure means "not ready"
        return False
