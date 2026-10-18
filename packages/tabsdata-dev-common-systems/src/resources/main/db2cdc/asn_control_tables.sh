{#-
  Copyright 2026 Tabsdata Inc.

  The ASN capture control tables: asnclp writes their DDL to a script, which the
  CLP runs. Values: db, asn, script.
-#}
cd "$HOME"
rm -f {{ script }}
printf 'set output capture script {{ script }}\nset server capture to db {{ db }}\nset capture schema source {{ asn }}\ncreate control tables for capture server\nquit\n' | asnclp
db2w connect to {{ db }} >/dev/null
db2w -tvf {{ script }}
rc=$?
db2 terminate >/dev/null 2>&1
exit $rc
