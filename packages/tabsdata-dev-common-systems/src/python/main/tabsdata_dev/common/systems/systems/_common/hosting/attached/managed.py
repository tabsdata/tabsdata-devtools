#
# Copyright 2026 Tabsdata Inc.
#

"""``ManagedHosting`` -- a provider-run instance, a VM or container rented
rather than run here (managed PostgreSQL)."""

from __future__ import annotations

from tabsdata_dev.common.systems.systems._common.hosting.attached._base import (
    AttachedHosting,
)


class ManagedHosting(AttachedHosting):
    hosting = "managed"
