#
# Copyright 2026 Tabsdata Inc.
#
# A stream row -> the trail's shape: `op` and `entity`, the source `tx`, its
# commit position `seg` (kept a string: db2's runs to 38 digits) and `sq`,
# `row` (the new values, the user's columns only) and `old` (the before-image).
# A delete carries the row it removed in the data columns and leaves the
# before-image empty: the row is its before-image. LOAD rows only mark where a
# table's load begins, and go.

select(.["@td.cdc.meta.op"] != "l")
| . as $r
| ($r | with_entries(select(.key | (startswith("@td.") or startswith("$td.")) | not))) as $new
| ($r | with_entries(select(.key | startswith("@td.cdc.data.col.old."))
                     | .key |= ltrimstr("@td.cdc.data.col.old."))) as $old
| {"i": "insert", "u": "update", "d": "delete"}[$r["@td.cdc.meta.op"]] as $op
| {op: $op, entity: $entity, tx: $r["@td.cdc.meta.tx"], seg: ($r["@td.cdc.meta.seg"] // ""),
   sq: ($r["@td.cdc.meta.sq"] | tonumber),
   row: $new,
   old: (if $op == "delete" and ($old | [.[]] | all(. == "")) then $new else $old end)}
