#!/bin/sh
#
# Copyright 2026 Tabsdata Inc.
#
# Stands in for tdd-exe: echoes its arguments, fails on `boom`, and on `venv`
# says the VIRTUAL_ENV it was started with.

if [ "$1" = venv ]; then
    echo "venv: ${VIRTUAL_ENV-unset}"
    exit 0
fi
if [ "$1" = boom ]; then
    echo "it broke" >&2
    exit 3
fi
echo "args: $*"
