{#-
  Copyright 2026 Tabsdata Inc.

  In front of every script run in the container. The Db2 CLP returns non-zero
  for warnings too (e.g. SQL1363W); `db2w` treats only rc >= 4 (real errors) as
  failure, so a `set -e`/`&&` chain is not aborted by a perfectly successful step.
-#}
db2w() { db2 "$@"; local r=$?; [ "$r" -ge 4 ] && return "$r"; return 0; }
