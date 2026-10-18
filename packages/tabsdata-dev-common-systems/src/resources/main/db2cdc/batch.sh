{#-
  Copyright 2026 Tabsdata Inc.

  Several statements over one connection; unless keep_going, the first to fail
  stops the batch and fails it. Values: db, statements, keep_going.
-#}
{%- from "db2cdc/lib.sh" import or_exit -%}
{%- set stop = "" if keep_going else or_exit() -%}
db2w connect to {{ db }} >/dev/null{{ stop }}
{% for sql in statements -%}
db2w -v "{{ sql }}"{{ stop }}
{% endfor -%}
db2 terminate >/dev/null 2>&1
