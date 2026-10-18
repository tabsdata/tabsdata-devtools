{#-
  Copyright 2026 Tabsdata Inc.

  SQL*Plus on stdin: exits non-zero unless the service answers a query.
-#}
WHENEVER SQLERROR EXIT FAILURE;
SELECT 1 FROM DUAL;
EXIT;
