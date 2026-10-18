#!/bin/sh
#
# Copyright 2026 Tabsdata Inc.
#
# Stands in for tdd-exe: appends its arguments to $FAKE_TDD_EXE_CALLS and
# prints what `_1p fetch --pypi-twine` would.

printf '%s\n' "$*" >> "$FAKE_TDD_EXE_CALLS"
printf 'export TWINE_USERNAME=__token__\n'
printf "export TWINE_PASSWORD='p w'\n"
