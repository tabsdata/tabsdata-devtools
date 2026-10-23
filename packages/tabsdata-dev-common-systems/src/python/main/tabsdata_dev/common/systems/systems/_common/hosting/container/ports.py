#
# Copyright 2026 Tabsdata Inc.
#

"""The host ports a system draws from when it needs any: its own range.

Every system type owns a fixed slot of ``PORTS_PER_SYSTEM`` ports from
``PORT_BASE`` on, by its position in the registry (``_SLUGS`` declaration order,
append-only; the table is docs/ports.md), so two creates -- in
one batch or in separate runs -- never look at the same ports, and a system's
ports are stable across recreates (the first free ones of its slot). A backend
takes them through :meth:`PortRangeMixin.next_free_port`, which walks the slot
from its start, skipping what is busy and what it already handed out in this
create (the previous port is not bound yet when the next is asked for).
``--ports`` still lets a caller pin the ports explicitly (:meth:`use_ports`).
Backends that need no ports simply never call it.
"""

from __future__ import annotations

from collections.abc import Iterable

from tabsdata_dev.common.core.ports import find_free_port
from tabsdata_dev.common.systems import constants
from tabsdata_dev.common.systems.errors import TdxError


def system_port_range(slug: str) -> tuple[int, int]:
    """The (first, last) host port of system type `slug`'s slot."""
    from tabsdata_dev.common.systems.systems import (
        slot_order,
    )  # the registry imports us

    slugs = slot_order()
    if slug not in slugs:
        raise TdxError(f"unknown system: {slug}")
    lo = constants.PORT_BASE + slugs.index(slug) * constants.PORTS_PER_SYSTEM
    hi = lo + constants.PORTS_PER_SYSTEM - 1
    if hi >= constants.PORTS_CEILING:
        raise TdxError(
            f"too many system types for the port slots: {slug} would reach {hi}, "
            f"the systems' ports end at {constants.PORTS_CEILING - 1}"
        )
    return lo, hi


class PortRangeMixin:
    slug: str
    _port_pool: tuple[int, ...] = ()
    _port_taken: int = 0
    _ports_given: frozenset[int] = frozenset()

    def use_ports(self, ports: Iterable[int]) -> None:
        """Pin the ports for this create (``--ports``); they are used in order
        before the system's own slot is consulted."""
        self._port_pool = tuple(int(p) for p in ports)
        self._port_taken = 0

    def next_free_port(self) -> int:
        """The next pinned port if any are left, else the first port of this
        system's slot that is free and not already handed out in this create."""
        if self._port_taken < len(self._port_pool):
            port = self._port_pool[self._port_taken]
            self._port_taken += 1
        else:
            port = find_free_port(
                system_port_range(self.slug), exclude=self._ports_given, from_start=True
            )
        self._ports_given = self._ports_given | {port}
        return port
