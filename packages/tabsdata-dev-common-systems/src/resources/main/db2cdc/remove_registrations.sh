{#-
  Copyright 2026 Tabsdata Inc.

  CAPSTOP every source, wait for asncap to take them (looped here, as
  wait_until.sh does), remove the registrations, then say which CD tables are
  left after a marker line. Values: db, asn, sources, pending (the query that
  counts the stops not yet taken), removal (statements), stagings (an SQL list),
  marker, timeout, poll.
-#}
db2 connect to {{ db }} >/dev/null 2>&1
{% for source in sources -%}
db2w -v "insert into {{ asn }}.ibmsnap_signal (signal_type, signal_subtype, signal_input_in, signal_state) values ('CMD', 'CAPSTOP', '{{ source }}', 'P')"
{% endfor -%}
rows=$(mktemp); got=''
while [ $SECONDS -lt {{ timeout }} ]; do
  db2 -x "{{ pending }}" > "$rows" 2>&1
  got=$(tr -s " \t\n" " " < "$rows" | sed "s/^ //; s/ $//")
  if [ "$got" = "0" ]; then break; fi
  sleep {{ poll }}
done
rm -f "$rows"
{% for sql in removal -%}
db2w -v "{{ sql }}"
{% endfor -%}
echo '{{ marker }}left'
db2 -x "select tabname from syscat.tables where tabschema = '{{ asn }}' and tabname in ({{ stagings }})"
db2 terminate >/dev/null 2>&1
