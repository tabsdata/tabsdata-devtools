#
# Copyright 2026 Tabsdata Inc.
#
"""A lane child: print each event of the JSON list in argv[1], one per line,
and exit with argv[2]. Any further arguments -- the --suite-run a lane is
started with -- are ignored."""

import json
import pathlib
import sys

for event in json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")):
    print(json.dumps(event))
raise SystemExit(int(sys.argv[2]))
