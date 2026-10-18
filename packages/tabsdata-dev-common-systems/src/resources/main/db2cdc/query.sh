{#-
  Copyright 2026 Tabsdata Inc.

  One query's rows (db2 -x), whatever it returns. Values: db, sql.
-#}
db2 connect to {{ db }} >/dev/null 2>&1
db2 -x "{{ sql }}"
db2 terminate >/dev/null 2>&1
