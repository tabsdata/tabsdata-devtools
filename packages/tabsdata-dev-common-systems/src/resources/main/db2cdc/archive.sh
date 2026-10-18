{#-
  Copyright 2026 Tabsdata Inc.

  Archive logging, then the baseline offline backup asncap refuses to start
  without. Values: db, archive, backup (folders under $HOME).
-#}
mkdir -p $HOME/{{ archive }} $HOME/{{ backup }}
db2w connect to {{ db }} >/dev/null
db2w update db cfg for {{ db }} using logarchmeth1 disk:$HOME/{{ archive }}/
db2 connect reset >/dev/null 2>&1
db2 terminate >/dev/null 2>&1
db2 force applications all >/dev/null 2>&1
sleep 5
db2 deactivate database {{ db }} >/dev/null 2>&1
db2w backup db {{ db }} to $HOME/{{ backup }}/
