{#-
  Copyright 2026 Tabsdata Inc.

  CAPSTOP every source, wait for asncap to take them (looped here, as
  wait_until.sh does), remove the registrations, then say which CD tables are
  left after a marker line. When the stops are not all taken and `require` is
  set, the removal is skipped while asncap runs -- it still holds those
  registrations, and its next insert into a dropped CD table stops it -- and the
  marker line says `held` instead. Values: db, asn, sources, taken (the query
  that counts the sources whose latest stop is taken), removal (statements),
  stagings (an SQL list), marker, timeout, poll, require.
-#}
db2 connect to {{ db }} >/dev/null 2>&1
{% for source in sources -%}
db2w -v "insert into {{ asn }}.ibmsnap_signal (signal_type, signal_subtype, signal_input_in, signal_state) values ('CMD', 'CAPSTOP', '{{ source }}', 'P')"
{% endfor -%}
rows=$(mktemp); got=''
while [ $SECONDS -lt {{ timeout }} ]; do
  db2 -x "{{ taken }}" > "$rows" 2>&1
  got=$(tr -s " \t\n" " " < "$rows" | sed "s/^ //; s/ $//")
  if [ "$got" = "{{ sources | length }}" ]; then break; fi
  sleep {{ poll }}
done
rm -f "$rows"
{% if require -%}
if [ "$got" != "{{ sources | length }}" ] && ! asnccmd capture_server={{ db }} capture_schema={{ asn }} status 2>&1 | grep -q ASN0506E; then
  echo '{{ marker }}held'
  db2 terminate >/dev/null 2>&1
  exit 0
fi
{% endif -%}
{% for sql in removal -%}
db2w -v "{{ sql }}"
{% endfor -%}
echo '{{ marker }}left'
db2 -x "select tabname from syscat.tables where tabschema = '{{ asn }}' and tabname in ({{ stagings }})"
db2 terminate >/dev/null 2>&1
