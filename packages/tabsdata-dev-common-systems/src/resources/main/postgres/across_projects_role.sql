{#-
  Copyright 2026 Tabsdata Inc.

  The server-wide role every domain shares, created if missing. One statement;
  no '%' in it, the driver would read it as a placeholder. Values: role.
-#}
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{{ role }}') THEN
    CREATE ROLE "{{ role }}" NOBYPASSRLS NOLOGIN;
  END IF;
END $$
