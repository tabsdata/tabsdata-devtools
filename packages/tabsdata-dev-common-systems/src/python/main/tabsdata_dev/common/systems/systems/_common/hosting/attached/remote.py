#
# Copyright 2026 Tabsdata Inc.
#

"""``RemoteHosting`` -- a service tdd only calls (object stores, warehouses,
AI providers, applications)."""

from __future__ import annotations

from tabsdata_dev.common.systems.systems._common.hosting.attached._base import (
    AttachedHosting,
)


class RemoteHosting(AttachedHosting):
    hosting = "remote"
