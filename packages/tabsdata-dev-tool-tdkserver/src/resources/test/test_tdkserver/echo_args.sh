#!/bin/sh
#
# Copyright 2026 Tabsdata Inc.
#
# Stands in for tdkserver: says what it was given, and fails on `fail`.

echo "tdkserver got: $*"
[ "$1" != fail ]
