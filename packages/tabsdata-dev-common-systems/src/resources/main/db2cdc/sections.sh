{#-
  Copyright 2026 Tabsdata Inc.

  Several read-only steps over one connection, each one's output after a marker
  line naming it: a query (db2 -x), or, prefixed `!`, a shell command and its
  status. Values: db, marker, steps (name -> step).
-#}
db2 connect to {{ db }} >/dev/null 2>&1
{% for name, step in steps.items() -%}
echo '{{ marker }}{{ name }}'
{% if step.startswith("!") -%}
{{ step[1:] }} 2>&1; echo "rc=$?"
{% else -%}
db2 -x "{{ step }}"
{% endif -%}
{% endfor -%}
db2 terminate >/dev/null 2>&1
