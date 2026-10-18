#!/usr/bin/env bash
#
# Copyright 2026 Tabsdata Inc.
#
# Stands in for kubectl's port-forward: appends its arguments to $RECORD,
# writes its pid to $PIDFILE when one is named, and listens on the LOCAL end
# of its last argument, LOCAL:REMOTE, as the real forward would.
# $FAKE_PYTHON runs listen.py, which sits beside it.

printf '%s\n' "$*" >> "$RECORD"
if [ -n "${PIDFILE:-}" ]; then
    echo $$ > "$PIDFILE"
fi
exec "$FAKE_PYTHON" "$(dirname "$0")/listen.py" "${@: -1}"
