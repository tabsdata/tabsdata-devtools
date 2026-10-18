#!/bin/sh
#
# Copyright 2026 Tabsdata Inc.
#
# Stands in for tdd-exe: echoes its arguments, and fails on `boom`.

if [ "$1" = boom ]; then
    echo "it broke" >&2
    exit 3
fi
echo "args: $*"
