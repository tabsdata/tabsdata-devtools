{#-
  Copyright 2026 Tabsdata Inc.

  Poll a query until its row reads `expected` (columns space-separated), in the
  container over ONE connection; exit 3 with the last row read at the timeout.
  bash's SECONDS counts from the shell's start: a deadline, where a count of
  looks would add every query's own time to the timeout. The query runs in THIS
  shell, its rows to a file: the CLP ties the connection to the process that
  made it, and `$(db2 ...)` runs db2 in a subshell, which has none (SQL1024N).
  Values: db, sql, expected, timeout, poll.
-#}
db2 connect to {{ db }} >/dev/null 2>&1
rows=$(mktemp); got=''
while [ $SECONDS -lt {{ timeout }} ]; do
  db2 -x "{{ sql }}" > "$rows" 2>&1
  got=$(tr -s " \t\n" " " < "$rows" | sed "s/^ //; s/ $//")
  if [ "$got" = "{{ expected }}" ]; then rm -f "$rows"; db2 terminate >/dev/null 2>&1; exit 0; fi
  sleep {{ poll }}
done
rm -f "$rows"
echo "last read: $got"
db2 terminate >/dev/null 2>&1
exit 3
