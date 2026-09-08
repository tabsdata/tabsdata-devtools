#
# Copyright 2026 Tabsdata Inc.
#

"""The one exception a command raises for an expected, user-facing failure.

``cli.run()`` turns it into an ``error`` event and exit 1 without a traceback;
anything else that escapes is a bug and keeps its traceback in the log. Command
families subclass it (``TdxError`` in common.systems) so their own code can
catch narrowly while the runner still catches everything.

``details`` is what the *failing system* had to say, for the log under the error
line: a database's SQLSTATE and DETAIL/HINT, a container's last log lines. The
one-line message is a driver's summary -- "permission denied for schema public"
-- and the terminal is the right place for it, but the answer is usually in what
the summary left out. Raise sites fill it in where they can (see
``common.systems.diagnostics`` and ``core.docker.container_failure``).
"""

from __future__ import annotations


class ToolError(Exception):
    def __init__(self, message: str, details: str = "") -> None:
        super().__init__(message)
        self.details = details
