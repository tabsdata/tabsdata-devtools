#
# Copyright 2026 Tabsdata Inc.
#
# Kill a kubectl that had been up long enough to count as steady, wait for the
# supervisor's relaunch, and stop.
#
#   forward_steady.sh ENGINE LOG PORT
#
# The fake kubectl writes its pid to $PIDFILE.

engine=$1
log=$2
port=$3
set --
. "$engine"

common_init "$log" 0
common_stage forward-2 "the forward"
common_kubeportforward_start /tmp/cfg sm-x net-apiserver "$port" 2457 || exit 10
first="$(cat "$PIDFILE")"
kill "$first"
for _ in 1 2 3 4 5 6 7 8 9 10; do
    [ "$(cat "$PIDFILE")" != "$first" ] && break
    sleep 0.2
done
common_kubeportforward_stop
exit 0
