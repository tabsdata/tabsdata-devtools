#
# Copyright 2026 Tabsdata Inc.
#

"""``LocalHosting`` -- the host machine itself (a local directory, or
nothing at all)."""

from __future__ import annotations

from tabsdata_dev.common.systems.systems._common.hosting.attached._base import (
    AttachedHosting,
)


class LocalHosting(AttachedHosting):
    hosting = "local"
