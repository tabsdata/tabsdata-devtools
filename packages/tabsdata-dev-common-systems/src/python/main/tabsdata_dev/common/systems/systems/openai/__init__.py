#
# Copyright 2026 Tabsdata Inc.
#

# openai system. Only the backend + create command are system-specific; every other
# verb runs the shared command in _common/commands.

from tabsdata_dev.common.systems.systems.openai.backend import Openai

__all__ = ["Openai"]
