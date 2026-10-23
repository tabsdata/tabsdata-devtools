#
# Copyright 2026 Tabsdata Inc.
#

"""``Synthetic`` -- the nature of systems whose data is generated when it is
ingested rather than kept anywhere (dev, which backs the tabsdata dev
connectors). There is no external resource and no credential, so the system and
its domains are always there.
"""

from __future__ import annotations

from tabsdata_dev.common.systems.systems._common.nature.credential._base import (
    CredentialAccount,
)


class Synthetic(CredentialAccount):
    nature: str = "synthetic"
    domain_word: str = "domain"

    def probe_system(self, meta: dict[str, str]) -> tuple[bool, str]:
        return True, f"{self.slug} system (no external resource)"

    def domain_status(self, domain_meta: dict[str, str]) -> tuple[bool, str]:
        return True, f"{self.slug} domain (no external resource)"
