{#-
  Copyright 2026 Tabsdata Inc.

  Drop the per-schema roles tabsdata created under one domain, and only those:
  the roles its user administers whose names start with that user's. ADMIN alone
  does not say a role is the domain's -- it also holds ADMIN on the shared
  across-projects role -- so the prefix does. `starts_with` rather than LIKE:
  no '%' in any statement, the driver would read it as a placeholder.
  Values: user.
-#}
DO $$
DECLARE r text;
BEGIN
  FOR r IN
    SELECT g.rolname FROM pg_auth_members m
    JOIN pg_roles g ON g.oid = m.roleid
    JOIN pg_roles o ON o.oid = m.member
    WHERE o.rolname = '{{ user }}' AND m.admin_option
    AND starts_with(g.rolname, '{{ user }}')
  LOOP
    EXECUTE 'DROP ROLE ' || quote_ident(r);
  END LOOP;
END $$
