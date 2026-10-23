#
# Copyright 2026 Tabsdata Inc.
#

"""OpenAI — a credential-only service system (one API key)."""

from __future__ import annotations

from tabsdata_dev.common.systems.systems._common.hosting.attached.remote import (
    RemoteHosting,
)
from tabsdata_dev.common.systems.systems._common.nature.credential.ai import (
    AiProvider,
)


class Openai(RemoteHosting, AiProvider):
    slug = "openai"
    label = "OpenAI"
    env_prefix = "OPENAI"
    cred_keys = ("API_KEY",)
