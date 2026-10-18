{#-
  Copyright 2026 Tabsdata Inc.

  Kill every session of the user `name`, so DROP USER can proceed; a session
  that cannot be killed is skipped. One PL/SQL block. Values: name.
-#}
BEGIN
  FOR s IN (SELECT sid, serial# FROM v$session WHERE username = UPPER('{{ name }}')) LOOP
    BEGIN
      EXECUTE IMMEDIATE 'ALTER SYSTEM KILL SESSION ''' || s.sid || ',' || s.serial# || ''' IMMEDIATE';
    EXCEPTION WHEN OTHERS THEN NULL;
    END;
  END LOOP;
END;
