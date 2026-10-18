{#-
  Copyright 2026 Tabsdata Inc.

  Pieces the db2cdc scripts share. `or_exit`, appended to a step of a
  multi-statement call, makes a failure end the call there, the connection
  closed first.
-#}
{%- macro or_exit() %} || { r=$?; db2 terminate >/dev/null 2>&1; exit "$r"; }{% endmacro -%}
