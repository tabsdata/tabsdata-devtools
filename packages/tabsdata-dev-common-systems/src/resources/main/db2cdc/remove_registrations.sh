{#-
  Copyright 2026 Tabsdata Inc.

  CAPSTOP every source, wait for asncap to take them (looped here, as
  wait_until.sh does), remove the registrations, then say which CD tables are
  left after a marker line. When the stops are not all taken and `require` is
  set, the removal is skipped while asncap runs -- it still holds those
  registrations, and its next insert into a dropped CD table stops it -- and the
  marker line says `held` instead, followed by what tells a capture program
  that is behind from one that is stuck. Values: db, asn, sources, taken (the
  query that counts the sources whose latest stop is taken), removal
  (statements), stagings (an SQL list), marker, timeout, poll, require.
-#}
{%- set listed -%}
{% for source in sources %}'{{ source }}'{{ ", " if not loop.last }}{% endfor %}
{%- endset %}
db2 connect to {{ db }} >/dev/null 2>&1
rows=$(mktemp); got=''
{% if require -%}
# db2 runs in this shell, never in $(...): a subshell has no connection.
look() { db2 -x "$2" > "$rows" 2>&1; echo "$1: $(tr -s " \t\n" " " < "$rows")"; }
rows_of() { echo "$1:"; db2 -x "$2" 2>&1; }
restart="select hex(max_commitseq), hex(min_inflightseq) from {{ asn }}.ibmsnap_restart"
look "Capture restart position (max commitseq, min in-flight seq) before the wait" "$restart" > "$rows.before"
{% endif -%}
{% for source in sources -%}
db2w -v "insert into {{ asn }}.ibmsnap_signal (signal_type, signal_subtype, signal_input_in, signal_state) values ('CMD', 'CAPSTOP', '{{ source }}', 'P')"
{% endfor -%}
while [ $SECONDS -lt {{ timeout }} ]; do
  db2 -x "{{ taken }}" > "$rows" 2>&1
  got=$(tr -s " \t\n" " " < "$rows" | sed "s/^ //; s/ $//")
  if [ "$got" = "{{ sources | length }}" ]; then break; fi
  sleep {{ poll }}
done
{% if require -%}
if [ "$got" != "{{ sources | length }}" ] && ! asnccmd capture_server={{ db }} capture_schema={{ asn }} status 2>&1 | grep -q ASN0506E; then
  echo '{{ marker }}held'
  echo "Waited ${SECONDS}s; $got of {{ sources | length }} stop(s) taken."
  cat "$rows.before"
  look "Capture restart position now" "$restart"
  look "Current log position" "select hex(current_lsn) from table(mon_get_transaction_log(-1))"
  look "Capture heartbeat (synchtime) and now" "select synchtime, current timestamp from {{ asn }}.ibmsnap_register where global_record = 'Y'"
  rows_of "Latest stops of the sources (source, state, time)" "select signal_input_in, signal_state, signal_time from {{ asn }}.ibmsnap_signal where signal_type = 'CMD' and signal_subtype = 'CAPSTOP' and signal_input_in in ({{ listed }}) order by signal_time desc fetch first {{ sources | length * 3 }} rows only"
  rows_of "Registrations (source, state, CD table)" "select trim(source_owner) || '.' || trim(source_table), state, cd_table from {{ asn }}.ibmsnap_register where trim(source_owner) || '.' || trim(source_table) in ({{ listed }})"
  rows_of "Lock waits (waiting, holder, holder handle, table, mode requested, waited ms)" "select req_application_name, hld_application_name, hld_application_handle, trim(tabschema) || '.' || trim(tabname), lock_mode_requested, lock_wait_elapsed_time from sysibmadm.mon_lockwaits"
  rows_of "Oldest open units of work (handle, start, state, log bytes used)" "select application_handle, uow_start_time, workload_occurrence_state, uow_log_space_used from table(mon_get_unit_of_work(null, -1)) where uow_start_time is not null order by uow_start_time fetch first 5 rows only"
  echo "Capture status:"
  asnccmd capture_server={{ db }} capture_schema={{ asn }} status show details 2>&1
  rm -f "$rows" "$rows.before"
  db2 terminate >/dev/null 2>&1
  exit 0
fi
{% endif -%}
rm -f "$rows" "$rows.before"
{% for sql in removal -%}
db2w -v "{{ sql }}"
{% endfor -%}
echo '{{ marker }}left'
db2 -x "select tabname from syscat.tables where tabschema = '{{ asn }}' and tabname in ({{ stagings }})"
db2 terminate >/dev/null 2>&1
