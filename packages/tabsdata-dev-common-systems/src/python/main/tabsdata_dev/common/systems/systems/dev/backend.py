#
# Copyright 2026 Tabsdata Inc.
#

"""Development — a fully no-op system (no external resource, no credentials).

Exists so a dev system + domain can be created / listed / destroyed through the
same tooling for CI consistency; it backs the tabsdata dev connectors.
"""

from __future__ import annotations

from tabsdata_dev.common.systems.systems._common.hosting.attached.local import (
    LocalHosting,
)
from tabsdata_dev.common.systems.systems._common.nature.credential.synthetic import (
    Synthetic,
)


class Dev(LocalHosting, Synthetic):
    slug = "dev"
    label = "Development"
    kind = "dev"
