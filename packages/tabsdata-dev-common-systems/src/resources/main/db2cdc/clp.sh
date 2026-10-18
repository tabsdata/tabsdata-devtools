{#-
  Copyright 2026 Tabsdata Inc.

  One statement over its own connection; the call exits with its status.
  Values: db, sql.
-#}
db2w connect to {{ db }} >/dev/null
db2w -v "{{ sql }}"
rc=$?
db2 terminate >/dev/null 2>&1
exit $rc
