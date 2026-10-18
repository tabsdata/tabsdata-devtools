#!/bin/sh
#
# Copyright 2026 Tabsdata Inc.
#
# Installed as `gh`: runs fake_gh.py, beside it, on $FAKE_GH_PYTHON.

exec "$FAKE_GH_PYTHON" "$(dirname "$0")/fake_gh.py" "$@"
