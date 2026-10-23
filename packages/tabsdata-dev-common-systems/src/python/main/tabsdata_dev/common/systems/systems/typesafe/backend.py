#
# Copyright 2026 Tabsdata Inc.
#

"""TypeSafe — a credential-only service system (an API key and its name)."""

from __future__ import annotations

from tabsdata_dev.common.systems.systems._common.hosting.attached.remote import (
    RemoteHosting,
)
from tabsdata_dev.common.systems.systems._common.nature.credential.ai import (
    AiProvider,
)


class TypeSafe(RemoteHosting, AiProvider):
    slug = "typesafe"
    label = "TypeSafe"
    env_prefix = "TYPESAFE"
    cred_keys = ("API_KEY", "API_KEY_NAME")
    public_creds = frozenset({"API_KEY_NAME"})
