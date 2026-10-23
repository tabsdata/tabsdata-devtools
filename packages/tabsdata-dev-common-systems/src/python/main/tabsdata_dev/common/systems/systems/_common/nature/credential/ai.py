#
# Copyright 2026 Tabsdata Inc.
#

"""``AiProvider`` -- the nature of AI model providers reached with an API key
(anthropic, openai, typesafe)."""

from __future__ import annotations

from tabsdata_dev.common.systems.systems._common.nature.credential._base import (
    CredentialAccount,
)


class AiProvider(CredentialAccount):
    nature: str = "ai_provider"
