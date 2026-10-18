#
# Copyright 2026 Tabsdata Inc.
#
"""A lane child whose summary message is the groups it was handed in
_TDD_XP_SEQ, or `unset`."""

import json
import os

summary = {
    "command": "xp",
    "event": "ok",
    "xp": "summary",
    "message": os.environ.get("_TDD_XP_SEQ", "unset"),
}
print(json.dumps(summary))
