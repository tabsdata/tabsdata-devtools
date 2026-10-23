#
# Copyright 2026 Tabsdata Inc.
#

"""``Application`` -- the nature of business applications reached with an
account's credentials (salesforce)."""

from __future__ import annotations

from tabsdata_dev.common.systems.systems._common.nature.credential._base import (
    CredentialAccount,
)


class Application(CredentialAccount):
    nature: str = "application"
