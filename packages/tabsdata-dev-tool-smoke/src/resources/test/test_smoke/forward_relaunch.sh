#
# Copyright 2026 Tabsdata Inc.
#
# The forward's supervisor under two losses: kubectl dies (the supervisor
# relaunches it), then the supervisor and its kubectl die (ensure starts the
# forward afresh). Exits 0, or 10-17 naming the step that failed.
#
#   forward_relaunch.sh ENGINE LOG PORT
#
# The fake kubectl writes its pid to $PIDFILE.

# `tdd _smoke` is the toolset's own `_smoke` program, $SMOKE_ENGINE: the
# engine runs the forward through it.
tdd() {
    [ "$1" = _smoke ] || return 127
    shift
    "$SMOKE_ENGINE" "$@"
}

engine=$1
log=$2
port=$3
set --
. "$engine"

answers() {
    (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null
}

wait_down() {
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        answers || break
        sleep 0.5
    done
}

common_init "$log" 0
common_stage forward-2 "the forward"
common_kubeportforward_start /tmp/cfg sm-x net-apiserver "$port" 2457 || exit 10

# the tunnel drops: kubectl dies; the supervisor must bring it back
kill "$(cat "$PIDFILE")"
wait_down
answers && exit 11 # it must have gone down first
common_stage xp-1 "a suite"
common_kubeportforward_ensure || exit 12
[ "$(cat "$PIDFILE")" != "" ] || exit 13

# the supervisor itself is gone, and so is its kubectl: ensure starts afresh
kill -9 "$PORTFORWARD_PID"
kill "$(cat "$PIDFILE")" 2>/dev/null
wait_down
common_stage xp-2 "another suite"
common_kubeportforward_ensure || exit 14
answers || exit 15

common_kubeportforward_stop
answers && exit 16                                  # nothing left listening
kill -0 "$(cat "$PIDFILE")" 2>/dev/null && exit 17 # nor a kubectl
exit 0
