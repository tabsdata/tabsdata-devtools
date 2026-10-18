#!/bin/sh
#
# Copyright 2026 Tabsdata Inc.
#
# Stands in for jq: says what it was given, and fails on `fail`.

echo "jq got: $*"
[ "$1" != fail ]
