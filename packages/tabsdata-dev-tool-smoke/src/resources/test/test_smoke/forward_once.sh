#
# Copyright 2026 Tabsdata Inc.
#
# Start the port-forward to net-apiserver:2457 on PORT, stop it, and exit
# with the start's status.
#
#   forward_once.sh ENGINE LOG PORT

engine=$1
log=$2
port=$3
set --
. "$engine"

common_init "$log" 0
common_stage forward-1 "the forward"
common_kubeportforward_start /tmp/cfg sm-x net-apiserver "$port" 2457
rc=$?
common_kubeportforward_stop
exit $rc
