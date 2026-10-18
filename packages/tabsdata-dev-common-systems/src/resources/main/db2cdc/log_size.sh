{#-
  Copyright 2026 Tabsdata Inc.

  Raise the log file size. Values: db, pages.
-#}
db2w connect to {{ db }} >/dev/null
db2w update db cfg for {{ db }} using logfilsiz {{ pages }}
db2 connect reset >/dev/null 2>&1
