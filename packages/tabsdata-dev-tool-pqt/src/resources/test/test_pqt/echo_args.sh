#!/bin/sh
#
# Copyright 2026 Tabsdata Inc.
#
# Stands in for pqt: says what it was given, and fails on `fail`.

echo "pqt got: $*"
[ "$1" != fail ]
