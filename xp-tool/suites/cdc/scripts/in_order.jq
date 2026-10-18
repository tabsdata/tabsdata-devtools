#
# Copyright 2026 Tabsdata Inc.
#
# The snapshot first, then the changes in commit order and by position within
# a transaction. The commit order is `seg`, a non-negative integer padded to 40
# digits and sorted as a string -- never through tonumber, which rounds past 2^53
# and db2's commit sequence goes well beyond. A stream without `seg` falls back
# to its source transaction: a number (postgres' xid), a GTID, `<server
# uuid>:<n>` (mysql), ordered by its n -- every change comes from the one server
# -- or db2's 32 hex digits, which order as they read: fixed width, so as a
# string. A postgres xid is the order transactions BEGAN, which is not the order
# they commit once several are open at once (modify-data --trx-mode).

def pad: ("0000000000000000000000000000000000000000"[0:(40 - length)]) + .;
def txkey: if test("^[0-9a-fA-F]{32}$") then ascii_downcase
           elif test("^[0-9]+$") then tonumber
           elif test(":[0-9]+$") then (split(":") | last | tonumber)
           else . end;
sort_by([.tx != "initial-load",
         (if .tx != "initial-load" and (.seg | test("^[0-9]+$")) then (.seg | pad) else "" end),
         (if .tx == "initial-load" then 0 else (.tx | txkey) end),
         .sq]) | .[]
