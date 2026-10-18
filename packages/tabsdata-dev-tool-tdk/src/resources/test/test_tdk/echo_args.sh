#!/bin/sh
#
# Copyright 2026 Tabsdata Inc.
#
# Stands in for tdk: says what it was given, and fails on `fail`.

echo "tdk got: $*"
[ "$1" != fail ]
