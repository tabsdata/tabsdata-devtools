#!/bin/sh
#
# Copyright 2026 Tabsdata Inc.
#
# A venv's python that reports, whatever it is asked, the sys.path in
# sys_path.json beside it.

cat "$(dirname "$0")/sys_path.json"
