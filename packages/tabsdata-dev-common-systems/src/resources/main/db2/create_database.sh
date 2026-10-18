{#-
  Copyright 2026 Tabsdata Inc.

  The shared database every Db2 domain is a schema of, created once, as the
  instance owner. Values: db.
-#}
set -e
db2 -v create database {{ db }}
db2 -v terminate
