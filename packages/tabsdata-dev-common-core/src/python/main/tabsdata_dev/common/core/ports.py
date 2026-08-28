#
# Copyright 2026 Tabsdata Inc.
#

"""Free host ports and reachability probes."""

from __future__ import annotations

import socket


def find_free_port() -> int:
    s = socket.socket()
    try:
        s.bind(("", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def find_free_ports(count: int) -> list[int]:
    """`count` *distinct* free ports, found by holding every candidate socket open
    at once so the OS hands out different ports, then releasing them. The ports
    are free (not reserved) when returned; a caller that fans a disjoint slice out
    to each of several parallel workers keeps those workers from racing one
    another for the same free port."""
    socks: list[socket.socket] = []
    try:
        for _ in range(max(0, count)):
            s = socket.socket()
            s.bind(("", 0))
            socks.append(s)
        return [s.getsockname()[1] for s in socks]
    finally:
        for s in socks:
            s.close()


def port_pools(n: int, per: int) -> list[list[int]]:
    """`n` disjoint pools of `per` free ports, found in one go so they never
    overlap -- one pool per parallel worker that may need ports."""
    if n <= 0:
        return []
    ports = find_free_ports(n * per)
    return [ports[i * per : (i + 1) * per] for i in range(n)]


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

    req = urllib.request.Request(url)  # noqa: S310
    if user is not None:
        token = base64.b64encode(f"{user}:{password or ''}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return 200 <= resp.status < 300
    except Exception:  # noqa: BLE001 - any failure means "not ready"
        return False
