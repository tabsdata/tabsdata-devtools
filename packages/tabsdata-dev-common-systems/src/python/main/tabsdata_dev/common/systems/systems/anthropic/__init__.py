#
# Copyright 2026 Tabsdata Inc.
#

# anthropic system. Only the backend + create command are system-specific; every other
# verb runs the shared command in _common/commands.

from tabsdata_dev.common.systems.systems.anthropic.backend import Anthropic

__all__ = ["Anthropic"]
