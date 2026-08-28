#
# Copyright 2026 Tabsdata Inc.
#

"""The one exception a command raises for an expected, user-facing failure.

``cli.run()`` turns it into an ``error`` event and exit 1 without a traceback;
anything else that escapes is a bug and keeps its traceback in the log. Command
families subclass it (``TdxError`` in common.systems) so their own code can
catch narrowly while the runner still catches everything.
"""

from __future__ import annotations


class ToolError(Exception):
    pass
