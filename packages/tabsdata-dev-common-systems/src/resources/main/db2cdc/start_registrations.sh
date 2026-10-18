{#-
  Copyright 2026 Tabsdata Inc.

  Register tables for capture in one call over one connection: DATA CAPTURE
  CHANGES on each, one asnclp run writing every registration, then the
  statements in `after` (prune control rows, CAPSTART signals). Any failure ends
  the call. Values: db, asn, schema, tables, script, registrations (table,
  staging pairs), old_prefix, after.
-#}
{%- from "db2cdc/lib.sh" import or_exit -%}
cd "$HOME"
db2w connect to {{ db }} >/dev/null{{ or_exit() }}
{% for table in tables -%}
db2w -v "alter table {{ schema }}.{{ table }} data capture changes"{{ or_exit() }}
{% endfor -%}
rm -f {{ script }}
printf 'set output capture script {{ script }}\nset server capture to db {{ db }}\nset capture schema source {{ asn }}\n{% for table, staging in registrations %}create registration ({{ schema }}.{{ table }}) differential refresh stage {{ asn }}.{{ staging }} cols all image both prefix {{ old_prefix }} options capture all\n{% endfor %}quit\n' | asnclp
db2w -tvf {{ script }}{{ or_exit() }}
{% for sql in after -%}
db2w -v "{{ sql }}"{{ or_exit() }}
{% endfor -%}
db2 terminate >/dev/null 2>&1
