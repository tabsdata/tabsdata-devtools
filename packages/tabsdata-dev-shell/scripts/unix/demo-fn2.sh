#
# Copyright 2026 Tabsdata Inc.
#

# A demo shell command. It prints its name, then something fetched through two
# external binaries -- which is the part it really demonstrates: the
# bin-reqs.txt beside this file declares them, `tdd --reqs` reports them, and
# tdd-fn refuses to run the command if one is missing from PATH. Registered
# --demo, so it stays out of `tdd help` unless asked for.

tdd_fn_register --demo demo-fn2 "demo shell command: prints its name, then the OS and the date"

tddfn_demo-fn2() {
    echo "demo-fn2: $(uname -s) $(date +%Y-%m-%d)"
}
