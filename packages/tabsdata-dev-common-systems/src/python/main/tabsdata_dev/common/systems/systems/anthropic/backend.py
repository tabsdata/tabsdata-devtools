#
# Copyright 2026 Tabsdata Inc.
#

"""Anthropic — a credential-only service system (one API key)."""

from __future__ import annotations

from tabsdata_dev.common.systems.systems._common.hosting.attached.remote import (
    RemoteHosting,
)
from tabsdata_dev.common.systems.systems._common.nature.credential.ai import (
    AiProvider,
)


class Anthropic(RemoteHosting, AiProvider):
    slug = "anthropic"
    label = "Anthropic"
    env_prefix = "ANTHROPIC"
    cred_keys = ("API_KEY",)
