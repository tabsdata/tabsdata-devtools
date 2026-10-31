#
# Copyright 2026 Tabsdata Inc.
#

# _common.sh -- the plumbing every smoke script shares. Source it after
# parsing options, then call `common_init`. Everything it defines starts with
# `common_`, so a script reads unambiguously.
#
#   common_init LOG VERBOSE               screen/log wiring, colours, the window
#   common_screen TEXT                    a line for the screen (and, plain, the log)
#   common_stage [--continue] NAME "what" open a stage (closes the previous one as ok)
#   common_run CMD...                     echo CMD (credentials masked) and run it in
#                                         THIS shell; a failure fails the stage
#   common_run_shown TEXT CMD...          same, echoing and recording TEXT instead of CMD
#   common_run_retry N PAUSE CMD...       same, retried up to N times PAUSE seconds apart
#   common_note TEXT                      a line under the stage, collapsed with the rest
#   common_remark TEXT                    a yellow line after the stage that stays (closes it as ok)
#   common_finish                         report + final verdict; the exit status
#   common_display CMD...                 CMD as text with credentials masked
#   common_instance_pids NAME             pids of the km processes of a tdkserver instance
#   common_instance_stop NAME TDD_DIR [OPTS...]
#                                         stop an instance a previous run left, wait it out
#   common_tdkserver_expect NAME running|stopped
#   common_instance_gone NAME             no km process and no folder left after a delete
#   common_tdkserver_pods_running NAME SERVICE...
#                                         every SERVICE has a Running, Ready pod in `tdkserver status`
#   common_kubeportforward_start KUBECONFIG NAMESPACE SERVICE LOCAL [REMOTE]
#                                         `kubectl port-forward LOCAL:REMOTE` (REMOTE defaults to
#                                         LOCAL) in the background under a supervisor that relaunches
#                                         it whenever it exits, waited for on LOCAL; a stage command
#                                         on its own, no common_run in front
#   common_kubeportforward_ensure         before a stage that needs the server: LOCAL answers, or
#                                         the forward is started afresh; a stage command, bare
#   common_kubeportforward_stop           end it (also on exit: the script traps EXIT to it)
#   common_k8s_namespace_exists KUBECONFIG CONTEXT NAMESPACE
#                                         is it there? (asked at most once per report)
#   common_k8s_report KUBECONFIG CONTEXT NAMESPACE [TAIL]
#                                         pods, jobs, events and failed pods' logs, into the log
#   common_help REQUIRED                  paint a help page from stdin; REQUIRED options in red
#   common_fill_placeholder FILE... -- PLACEHOLDER VALUE
#                                         replace a `${{kind:name}}` placeholder in config files
#   common_fill_pem FILE... -- PLACEHOLDER VALUE
#                                         the same for a multi-line PEM: a YAML block scalar
#   common_xp_expand_all                 --xp-suites ALL -> every suite dir, in SUITE_LIST and
#                                         STAGE_NAMES; once tdd is loaded, before the first stage
#                                         `tdkserver status` must agree with the expected state
#   common_tabsdata_setup_info common_screen|common_note
#                                         the instance (running?), the venv, how to use/stop/remove them
#
# Whatever is an algorithm rather than stage keeping is `tdd _smoke`, written
# once for both families: the config edits (set-uv-index, set-fn-resources,
# fill-placeholder, fill-pem, fill-storage, placeholders-left), called by the
# scripts as stage commands, `common_run tdd _smoke ...`; and, under the
# functions here, the masking (display), the reading of `tdkserver status`
# (instance-state, pods-ready), a local instance's processes (instance-pids,
# instance-stop, instance-gone), the screen beyond the stage lines (window,
# pointers, paint-help) and the supervised port-forward (forward-start,
# forward-ensure, forward-stop). So a script loads tdd first.
#
# The script declares STAGE_NAMES (in order) before the first `common_stage`.
# `common_on_stage_failed` is called after a failed stage's recap, before the report,
# to say what was left standing: the default here describes the tabsdata
# instance and venv named by the script's INSTANCE, SERVER, VENV, VENV_TYPE and
# TDD_DIR_OPT (nothing when INSTANCE is unset); a script may define its own
# after sourcing this file.
#
# Screen model. A stage prints a blue header, then one line per command as it
# runs. Everything a command prints goes to the log; on a terminal, a rolling
# window of the last WINDOW log lines is redrawn under the running command and
# erased when it ends (--verbose streams it all instead). A stage that passes
# COLLAPSES its command lines into one green `ok (Ns)`; a stage that fails
# keeps them EXPANDED, each marked ✓ or ✗, closes with a red `error (Ns)` and
# lists under `look at:` the log files the failed command named (details:,
# errors:, lane log:, "full output in") plus, when the run goes on, this log --
# so the failure can be read while the rest runs. Then the run stops, unless the
# stage was opened with --continue, in which case the failure is recorded and
# the next stage runs. The closing report
# lists every stage as ok / failed / failed, continued / not done.
#
# bash 3.2 (macOS) is enough: indexed arrays, no associative ones.

# The system's temp folder, as Python's tempfile finds it: $TMPDIR, else /tmp
# (macOS gives every user their own). Logs and work folders default under it.
COMMON_TMP="${TMPDIR:-/tmp}"
COMMON_TMP="${COMMON_TMP%/}"

WINDOW="${WINDOW:-10}"

common_init() {
    LOG="$1"
    VERBOSE="${2:-0}"
    mkdir -p "$(dirname "$LOG")"
    exec 3>&1                                  # the common_screen: the original stdout
    TTY=0
    [ -t 1 ] && TTY=1
    if [ "$TTY" = 1 ] && [ -z "${NO_COLOR:-}" ]; then
        BLUE=$'\033[38;5;33m'; GREEN=$'\033[32m'; RED=$'\033[31m'; YELLOW=$'\033[33m'; DIM=$'\033[2m'; RESET=$'\033[0m'
    else
        BLUE=""; GREEN=""; RED=""; YELLOW=""; DIM=""; RESET=""
    fi
    WIDTH="$(common_width)"
    ESC="$(printf '\033')"
    # Lines under the stage header can be collapsed (cursor arithmetic) only on
    # a terminal that is not streaming command output.
    COLLAPSE=0
    [ "$TTY" = 1 ] && [ "$VERBOSE" = 0 ] && COLLAPSE=1
    if [ "$VERBOSE" = 1 ]; then
        exec > >(tee -a "$LOG") 2>&1           # commands: common_screen and log
    else
        exec >>"$LOG" 2>&1                     # commands: log only
    fi
    STAGE_STATUS=()
    STAGE_SECONDS=()
    NS_EXISTS_KEY=""; NS_EXISTS_RC=1   # common_k8s_namespace_exists' one-slot memo
    STAGE_I=-1
    STAGE_T0=0
    STAGE_LINES=0
    STAGE_CMDS=()
    STAGE_CMD_STATUS=()
    STAGE_CONTINUE=0
    CURRENT=""
    CONTINUED=0
    WINDOW_PID=""
    WINDOW_FROM=0
    PORTFORWARD_PID=""
    PORTFORWARD_ARGS=()   # what common_kubeportforward_start was given, for _ensure
    RUN_T0="$(date +%s)"
}

# Seconds as 1h 2m 3s / 2m 3s / 3s.
common_duration() {
    local s="$1"
    if [ "$s" -ge 3600 ]; then
        printf '%dh %dm %ds' "$((s / 3600))" "$((s % 3600 / 60))" "$((s % 60))"
    elif [ "$s" -ge 60 ]; then
        printf '%dm %ds' "$((s / 60))" "$((s % 60))"
    else
        printf '%ds' "$s"
    fi
}

# A line for the screen; plain (no colour) into the log too, so the log reads
# like the screen. With --verbose the screen IS the tee'd log, so once is enough.
common_screen() {
    if [ "$VERBOSE" = 1 ]; then
        printf '%s\n' "$*"
    else
        printf '%s\n' "$*" >&3
        printf '%s\n' "$*" | sed -E "s/${ESC}\[[0-9;]*m//g"
    fi
}

# The terminal's width, asked of the controlling tty itself -- stdout may be
# the log by now, COLUMNS is a shell variable no shell exports, and `tput cols`
# inside $(...) sees a pipe and answers terminfo's 80. Re-read where it matters,
# so a resize mid-run is honoured.
common_width() {
    local w
    w="$(stty size 2>/dev/null </dev/tty)"
    w="${w##* }"
    [ "${w:-0}" -gt 0 ] 2>/dev/null || w="${COLUMNS:-120}"
    printf '%s' "$w"
}

# Plain text cut to the terminal width: a line under a stage must not wrap,
# the collapse counts lines.
common_fit() {
    printf '%s' "$1" | cut -c1-"$(($(common_width) - 6))"
}

# A line under the current stage header, counted for the collapse.
common_note() {
    common_screen "    $(common_fit "$1")"
    STAGE_LINES=$((STAGE_LINES + 1))
}

# A yellow line that STAYS on the screen: a note under a stage collapses with
# it when the stage passes, so this closes the running stage as ok first and
# prints outside any stage -- for a workaround or a caveat the reader should
# still see once the run has gone green.
common_remark() {
    common_stage_ok
    common_screen "    ${YELLOW}$1${RESET}"
}

# ---------------------------------------------------------------- window
# The rolling window shows the last WINDOW lines the RUNNING COMMAND wrote --
# everything the log gained since the window opened, not the log's tail
# (`tdd _smoke window`, on the screen). It is ended by a stop file rather than a
# signal: started in the background through the `tdd` function, the job is a
# subshell, and a signal to it would not reach the program drawing.
common_window_start() {
    [ "$COLLAPSE" = 1 ] || return 0
    WINDOW_FROM="$(wc -c <"$LOG" 2>/dev/null | tr -d ' ')"
    WINDOW_STOP="$LOG.window-stop"
    rm -f "$WINDOW_STOP"
    tdd _smoke window --log "$LOG" --from "${WINDOW_FROM:-0}" --lines "$WINDOW" \
        --stop "$WINDOW_STOP" --parent "$$" ${DIM:+--dim} 2>&3 >/dev/null &
    WINDOW_PID=$!
}

common_window_stop() {
    [ -n "$WINDOW_PID" ] || return 0
    : >"$WINDOW_STOP"
    wait "$WINDOW_PID" 2>/dev/null
    rm -f "$WINDOW_STOP"
    WINDOW_PID=""
    printf '\033[J' >&3
}

# ---------------------------------------------------------------- masking
# A command line as text with every credential masked (`tdd _smoke display`):
# the value after --password/--token/--*-key and the like, a URL's
# user:password, a NAME=value whose NAME says PASSWORD/SECRET/TOKEN/KEY/_PAT.
common_display() {
    tdd _smoke display -- "$@"
}

# ---------------------------------------------------------------- stages
common_elapsed() {
    echo $(( $(date +%s) - STAGE_T0 ))
}

# Erase the lines printed under the current header (terminal, non-verbose).
common_collapse() {
    if [ "$COLLAPSE" = 1 ] && [ "$STAGE_LINES" -gt 0 ]; then
        printf '\033[%dA\033[J' "$STAGE_LINES" >&3
    fi
    STAGE_LINES=0
}

# The stage's commands, each with its outcome -- what a failed stage leaves
# on the screen in place of the collapsed list.
common_recap() {
    local i=0 mark
    while [ "$i" -lt "${#STAGE_CMDS[@]}" ]; do
        case "${STAGE_CMD_STATUS[$i]}" in
            ok) mark="${GREEN}✓${RESET}" ;;
            failed) mark="${RED}✗${RESET}" ;;
            *) mark="${YELLOW}·${RESET}" ;;
        esac
        common_screen "    $mark $(common_fit "${STAGE_CMDS[$i]}")"
        i=$((i + 1))
    done
}

# Close the running stage as ok: its command lines collapse into one line.
common_stage_ok() {
    [ "$STAGE_I" -ge 0 ] || return 0
    [ -z "${STAGE_STATUS[$STAGE_I]:-}" ] || return 0
    STAGE_STATUS[$STAGE_I]="ok"
    STAGE_SECONDS[$STAGE_I]="$(common_elapsed)"
    common_collapse
    common_screen "    ${GREEN}ok${RESET} (${STAGE_SECONDS[$STAGE_I]}s)"
}

# stage [--continue] NAME "what it does"
common_stage() {
    common_stage_ok
    STAGE_CONTINUE=0
    if [ "$1" = "--continue" ]; then
        STAGE_CONTINUE=1
        shift
    fi
    STAGE_I=$((STAGE_I + 1))
    CURRENT="$1"
    STAGE_T0="$(date +%s)"
    STAGE_LINES=0
    STAGE_CMDS=()
    STAGE_CMD_STATUS=()
    common_screen ""
    # No "/total": stages are conditional (--llm-domain, --keep, --xp-suites), and a count
    # promised upfront reads as a lie when the run legitimately skips some.
    common_screen "${BLUE}==> [$((STAGE_I + 1))] $1 -- $2${RESET}   ${DIM}$(date +%H:%M:%S)${RESET}"
}

# A stage failed: expand its commands with their outcomes, close it in red,
# then stop -- or, for a --continue stage, record it and carry on.
common_stage_failed() {
    local why="$1" rc="${2:-1}"
    common_window_stop
    STAGE_SECONDS[$STAGE_I]="$(common_elapsed)"
    common_collapse
    common_recap
    if [ "$STAGE_CONTINUE" = 1 ]; then
        STAGE_STATUS[$STAGE_I]="continued"
        CONTINUED=$((CONTINUED + 1))
        common_screen "    ${RED}error${RESET} (${STAGE_SECONDS[$STAGE_I]}s) -- $why"
        common_pointers "log $LOG"
        common_screen "    ${YELLOW}continuing: this stage does not stop the run${RESET}"
        return 0
    fi
    STAGE_STATUS[$STAGE_I]="failed"
    common_screen "    ${RED}error${RESET} (${STAGE_SECONDS[$STAGE_I]}s) -- $why"
    common_pointers
    if type common_on_stage_failed >/dev/null 2>&1; then
        common_on_stage_failed
    fi
    common_report
    common_screen "${RED}$(basename "$0"): FAILED at stage $CURRENT   (log: $LOG)${RESET}"
    exit "$rc"
}

# Where to look, printed under a failed command while the run goes on: the log
# files the command itself named (`details: PATH`, `errors: PATH`, `lane log:`,
# `full output in PATH` -- every tdd command writes a failure log and says so),
# taken from what it wrote to the log since it started (CMD_LOG_FROM) by `tdd
# _smoke pointers`, plus any EXTRA "label path" given.
common_pointers() {
    local found
    found="$(tdd _smoke pointers --log "$LOG" --from "${CMD_LOG_FROM:-0}" 2>/dev/null)"
    [ $# -gt 0 ] && found="${found:+$found
}$*"
    [ -n "$found" ] || return 0
    common_screen "    ${YELLOW}look at:${RESET}"
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        common_screen "      ${DIM}${line% *}${RESET}  ${line##* }"   # label may be two words; the path has none
    done <<POINTERS
$found
POINTERS
}

# Run CMD in THIS shell (tdd venv/env change the environment). Returns 0, or
# 1 after a --continue stage swallowed the failure; a fatal failure exits.
common_run() {
    common_run_shown "$(common_display "$@")" "$@"
}

# common_run_shown TEXT CMD... -- common_run, but the stage records and echoes TEXT
# in place of CMD: for a helper that stands for a real command (the port-forward
# shows its kubectl line, not the function that babysits it).
common_run_shown() {
    local shown="$1" rc
    shift
    STAGE_CMDS[${#STAGE_CMDS[@]}]="$shown"
    STAGE_CMD_STATUS[${#STAGE_CMD_STATUS[@]}]="running"
    common_note "${DIM}\$${RESET} $shown"
    echo "\$ $shown"
    CMD_LOG_FROM="$(wc -c <"$LOG" 2>/dev/null | tr -d ' ')"
    common_window_start
    "$@"
    rc=$?
    common_window_stop
    if [ $rc -ne 0 ]; then
        STAGE_CMD_STATUS[$((${#STAGE_CMD_STATUS[@]} - 1))]="failed"
        common_stage_failed "$shown exited $rc" "$rc"
        return 1
    fi
    STAGE_CMD_STATUS[$((${#STAGE_CMD_STATUS[@]} - 1))]="ok"
    return 0
}

# common_run_retry N PAUSE CMD... -- for a probe of something that comes up on its own
# time (a server after start): the command is the readiness check.
common_run_retry() {
    local attempts="$1" pause="$2" attempt=1 rc shown
    shift 2
    shown="$(common_display "$@")"
    STAGE_CMDS[${#STAGE_CMDS[@]}]="$shown"
    STAGE_CMD_STATUS[${#STAGE_CMD_STATUS[@]}]="running"
    common_note "${DIM}\$${RESET} $shown   ${DIM}(up to $attempts attempts, ${pause}s apart)${RESET}"
    echo "\$ $shown   (up to $attempts attempts, ${pause}s apart)"
    CMD_LOG_FROM="$(wc -c <"$LOG" 2>/dev/null | tr -d ' ')"
    common_window_start
    while :; do
        "$@"
        rc=$?
        if [ $rc -eq 0 ]; then
            common_window_stop
            STAGE_CMD_STATUS[$((${#STAGE_CMD_STATUS[@]} - 1))]="ok"
            [ "$attempt" -gt 1 ] && common_note "succeeded on attempt $attempt"
            return 0
        fi
        if [ "$attempt" -ge "$attempts" ]; then
            STAGE_CMD_STATUS[$((${#STAGE_CMD_STATUS[@]} - 1))]="failed"
            common_stage_failed "$shown failed $attempts times (last exit $rc)" "$rc"
            return 1
        fi
        echo "attempt $attempt/$attempts failed (exit $rc); retrying in ${pause}s"
        attempt=$((attempt + 1))
        sleep "$pause"
    done
}

# ---------------------------------------------------------------- tabsdata instances
# The processes of a local instance are found BY NAME (`tdd _smoke`): every one
# of them carries the instance folder on its command line, `instances/NAME/`.
# That is how a previous run's leftovers are recognised without a pid file.
common_instance_pids() {
    tdd _smoke instance-pids --instance "$1"
}

common_instance_running() {
    [ -n "$(common_instance_pids "$1")" ]
}

# common_instance_stop NAME TDD_DIR [TDKSERVER_OPTS...] -- end the km processes of an
# instance a previous run left running, and WAIT until every one is gone: a km
# still winding down would kill the new cluster through reused pid files. Meant
# for `common_run`: sub-steps go to the log.
common_instance_stop() {
    local instance="$1" tdd_dir="$2"
    shift 2
    tdd _smoke instance-stop --instance "$instance" --tdd-dir "$tdd_dir" -- "$@"
}

# common_tdkserver_pods_running NAME SERVICE... -- every SERVICE has a pod
# that is Running and Ready in `tdd tdkserver status`, and no pod of the
# instance is in another state (`tdd _smoke pods-ready` reads the Pods table).
# Meant for `common_run_retry`: the pods come up after quickstart/start return.
common_tdkserver_pods_running() {
    local instance="$1" out verdict
    shift
    out="$(tdd tdkserver status --instance "$instance" --accept-terms y 2>&1)" || {
        printf '%s\n' "$out"
        echo "tdkserver status failed"
        return 1
    }
    verdict="$(printf '%s\n' "$out" | tdd _smoke pods-ready --instance "$instance" "$@")" || return 1
    [ "$verdict" = ready ]
}

# ---------------------------------------------------------------- kubectl / configs
# common_kubeportforward_start KUBECONFIG NAMESPACE SERVICE LOCAL [REMOTE] --
# `kubectl port-forward service/SERVICE LOCAL:REMOTE` under a supervisor that
# relaunches it whenever it exits (`tdd _smoke forward-start`), its output in
# the log; returns once LOCAL answers, or fails after ~60s. REMOTE defaults to
# LOCAL. The two are separate because only the local side can be taken -- by
# another run, another forward, a local tdkserver -- while the service's port
# in its own namespace clashes with nothing; a script moves LOCAL
# (--kube-port-forward) and leaves REMOTE the apiserver's. One at a time: a
# running forward is stopped first. A stage command by itself, shown as its
# kubectl line -- call it bare, like the stop.
#
# The forward still dies with the pods it points at, so it is re-established
# after every tdkserver start/restart, and ended before a stop, restart or
# config/env change, and on exit (`trap common_kubeportforward_stop EXIT`). What
# the start was given is kept in PORTFORWARD_ARGS, so an ensure can start afresh.
common_kubeportforward_start() {
    local kubeconfig="$1" namespace="$2" service="$3" local_port="$4" remote_port="${5:-$4}"
    PORTFORWARD_ARGS=("$kubeconfig" "$namespace" "$service" "$local_port" "$remote_port")
    common_run_shown \
        "kubectl port-forward --kubeconfig $kubeconfig --namespace $namespace service/$service $local_port:$remote_port   (background, relaunched when it exits)" \
        common_kubeportforward_call forward-start
}

# How long kubectl must have been up for its exit to count as a dropped tunnel,
# relaunched without a pause.
PORTFORWARD_STEADY="${PORTFORWARD_STEADY:-10}"

# common_kubeportforward_call ACTION -- `tdd _smoke ACTION` on this run's
# forward, then PORTFORWARD_PID from its state file: the supervisor's pid, or
# nothing when no forward is up.
common_kubeportforward_call() {
    local rc
    tdd _smoke "$1" \
        --kubeconfig "${PORTFORWARD_ARGS[0]}" --namespace "${PORTFORWARD_ARGS[1]}" \
        --service "${PORTFORWARD_ARGS[2]}" --local "${PORTFORWARD_ARGS[3]}" \
        --remote "${PORTFORWARD_ARGS[4]}" --state "$LOG.forward" --stop "$LOG.forward-stop" \
        --log "$LOG" --parent "$$" --steady "$PORTFORWARD_STEADY"
    rc=$?
    PORTFORWARD_PID=""
    [ -r "$LOG.forward" ] && read -r PORTFORWARD_PID <"$LOG.forward"
    return "$rc"
}

# common_kubeportforward_ensure -- before a stage that needs the server: the
# forward's port answers, or the forward is started afresh from what the last
# start was given (`tdd _smoke forward-ensure`) -- and a fresh start that fails
# fails the stage in its own words, rather than the suite failing lane by lane
# with "not logged in", which is what a dead forward looks like from tdk. A
# stage command, called bare; in a --continue stage, `|| continue` skips the
# suite.
common_kubeportforward_ensure() {
    if [ "${#PORTFORWARD_ARGS[@]}" -lt 5 ]; then
        echo "common_kubeportforward_ensure: no forward was started" >&2
        return 1
    fi
    common_run_shown \
        "port-forward 127.0.0.1:${PORTFORWARD_ARGS[3]} -> service/${PORTFORWARD_ARGS[2]}:${PORTFORWARD_ARGS[4]} answering   (started afresh if not)" \
        common_kubeportforward_call forward-ensure
}

# common_kubeportforward_stop -- end the forward, if one is up (`tdd _smoke
# forward-stop`). Bare, in a stage or from the EXIT trap; a no-op otherwise, so
# it is safe anywhere.
common_kubeportforward_stop() {
    [ "${#PORTFORWARD_ARGS[@]}" -ge 5 ] || return 0
    common_kubeportforward_call forward-stop
}

# common_help REQUIRED -- paint a help page read from stdin the way every tdd
# command paints one (`tdd _smoke paint-help`): a heading bold, an entry's term
# cyan, an option named in REQUIRED (space separated) red. Colours on a
# terminal only, and never under NO_COLOR. --help is read while the options
# are, before the script loads tdd, so it is loaded here from the tdd dir known
# so far; without one the page is printed as it is.
common_help() {
    if ! type tdd >/dev/null 2>&1 && [ -r "${TDD_DIR_OPT:-}/tdd-source.sh" ]; then
        # shellcheck disable=SC1090
        . "$TDD_DIR_OPT/tdd-source.sh" >/dev/null 2>&1
    fi
    if type tdd >/dev/null 2>&1; then
        tdd _smoke paint-help --required "$1"
    else
        cat
    fi
}

# common_k8s_report KUBECONFIG CONTEXT NAMESPACE [TAIL] -- what the cluster knows
# about the failure, into the log.
#
# A stage fails saying `Init job 'ins-dbmanager' failed` and the reason is inside
# a pod that the next run's clean-previous deletes. So the whole picture goes to
# the log while it still exists: every pod and job with its status, the
# namespace's recent events (an image that would not pull, a volume that would
# not mount, a quota), and for every pod that did not finish cleanly its events
# and its logs.
#
# --all-containers because a tabsdata pod does its real work in init containers
# (0000-cabundle, 0010-venvloader) before the main one starts, and plain
# `kubectl logs` shows only the default container and warns about the rest.
# --previous as well: a crashlooping pod has already thrown away the log that
# says why.
#
# Never fails and never hangs -- it runs inside a failure report, and a dead
# cluster must not turn a legible failure into a stuck script.
# common_k8s_namespace_exists KUBECONFIG CONTEXT NAMESPACE -- is the namespace there?
#
# A failure report asks this twice: once to decide whether its `namespace` lines
# are telling the truth, once here before collecting. On a cluster that has
# stopped answering -- which is often exactly why the run failed -- each ask
# costs the whole --request-timeout, so the answer is remembered. A report is a
# snapshot; a namespace does not appear halfway through one.
common_k8s_namespace_exists() {
    local key="$1|$2|$3"
    if [ "$key" != "$NS_EXISTS_KEY" ]; then
        kubectl --kubeconfig "$1" --context "$2" --request-timeout=20s \
            get namespace "$3" >/dev/null 2>&1
        NS_EXISTS_RC=$?
        NS_EXISTS_KEY="$key"
    fi
    return "$NS_EXISTS_RC"
}

common_k8s_report() {
    local kubeconfig="$1" context="$2" namespace="$3" tail="${4:-60}"
    local k pod phase ready
    k=(kubectl --kubeconfig "$kubeconfig" --context "$context" --namespace "$namespace" --request-timeout=20s)
    echo ""
    echo "================ kubernetes: namespace $namespace on $context"
    if ! common_k8s_namespace_exists "$kubeconfig" "$context" "$namespace"; then
        echo "(no namespace $namespace on this cluster -- nothing to collect)"
        return 0
    fi
    "${k[@]}" get pods,jobs -o wide 2>&1
    echo ""
    echo "---------------- events (oldest first)"
    "${k[@]}" get events --sort-by=.lastTimestamp 2>&1 | tail -40
    "${k[@]}" get pods \
        -o 'jsonpath={range .items[*]}{.metadata.name}{"\t"}{.status.phase}{"\t"}{range .status.containerStatuses[*]}{.ready}{","}{end}{range .status.initContainerStatuses[*]}{.ready}{","}{end}{"\n"}{end}' \
        2>/dev/null |
        while IFS="$(printf '\t')" read -r pod phase ready; do
            [ -n "$pod" ] || continue
            # a pod that ran to completion, or is up with every container ready,
            # has nothing to explain
            case "$phase" in
                Succeeded) continue ;;
                Running) case "$ready" in *false*) ;; *) continue ;; esac ;;
            esac
            echo ""
            echo "---------------- pod $pod ($phase): events"
            "${k[@]}" describe pod "$pod" 2>&1 | sed -n '/^Events:/,$p'
            echo "---------------- pod $pod: last $tail lines, every container"
            "${k[@]}" logs "$pod" --all-containers=true --prefix --tail="$tail" 2>&1
            # only a restarted container has a previous log, and that is the one
            # holding the error the restart erased
            "${k[@]}" logs "$pod" --all-containers=true --prefix --previous --tail="$tail" 2>/dev/null |
                sed "1i\\
---------------- pod $pod: the log before the last restart"
        done
    echo "================ end kubernetes"
}

# common_resolve_uv_index VALUE -- print the URL VALUE stands for (`tdd _smoke
# uv-index`, where the named ones live, so every script means the same by @dev):
# `@dev`, `@dev:NAME` (namespace NAME on the dev index) and `@prod` resolve,
# anything else passes through, and empty stays empty (no index asked for). An
# unknown `@marker` is refused here rather than passed on: uv would take it for
# a URL and fail several stages later, in a message about a failed install that
# says nothing about the option that caused it.
common_resolve_uv_index() {
    local url
    url="$(tdd _smoke uv-index --value "$1")" || return 1
    if [ -n "$1" ] && [ -z "$url" ]; then
        # `.sh` stripped: this stands beside the scripts' own option
        # errors, which name themselves without it.
        echo "$(basename "$0" .sh): unknown --uv-index marker: $1 (@dev, @dev:NAME, @prod, or a URL)" >&2
        return 1
    fi
    printf '%s' "$url"
}

# common_fill_placeholder FILE... -- PLACEHOLDER VALUE -- replace every literal
# occurrence of PLACEHOLDER (`${{literal:tdk_database_host}}`, `${{secret}}`,
# ...) in the files with VALUE, as a stage command (`tdd _smoke
# fill-placeholder`). The value travels in the environment, never on a command
# line: it can be a password.
common_fill_placeholder() {
    local files=()
    while [ $# -gt 0 ] && [ "$1" != "--" ]; do files[${#files[@]}]="$1"; shift; done
    shift
    _TDD_SMOKE_VALUE="$2" common_run tdd _smoke fill-placeholder --placeholder "$1" "${files[@]}"
}

# common_fill_pem FILE... -- PLACEHOLDER VALUE -- the same for a multi-line PEM,
# written as a YAML block scalar (`tdd _smoke fill-pem`).
common_fill_pem() {
    local files=()
    while [ $# -gt 0 ] && [ "$1" != "--" ]; do files[${#files[@]}]="$1"; shift; done
    shift
    _TDD_SMOKE_VALUE="$2" common_run tdd _smoke fill-pem --placeholder "$1" "${files[@]}"
}

# common_xp_expand_all -- `--xp-suites ALL` becomes the suite dirs `tdd xp
# one-shot --suite ALL` would run (`list-suites` reports them as `dirs`), one
# entry of SUITE_LIST each, and the `xp-ALL` of STAGE_NAMES their `xp-<dir>`
# stages: a smoke runs one stage and one named project per selector, and a
# one-shot over many selectors refuses --suite-run/--project. Any other
# SUITE_LIST is left as given. Call it once tdd is loaded and before the first
# `common_stage`; it exits when xp names no dir.
common_xp_expand_all() {
    local all dirs dir name
    local names=()
    [ "${#SUITE_LIST[@]}" -eq 1 ] || return 0
    all="${SUITE_LIST[0]}"
    [ "$(printf '%s' "$all" | tr '[:lower:]' '[:upper:]')" = ALL ] || return 0
    dirs="$(tdd xp list-suites --format json | tdd _smoke event-field --field dirs)"
    if [ -z "$dirs" ]; then
        common_screen "${RED}$(basename "$0"): --xp-suites $all: tdd xp list-suites named no suite dir${RESET}"
        exit 1
    fi
    SUITE_LIST=()
    for dir in $dirs; do SUITE_LIST[${#SUITE_LIST[@]}]="$dir"; done
    for name in "${STAGE_NAMES[@]}"; do
        if [ "$name" = "xp-$all" ]; then
            for dir in "${SUITE_LIST[@]}"; do names[${#names[@]}]="xp-$dir"; done
        else
            names[${#names[@]}]="$name"
        fi
    done
    STAGE_NAMES=("${names[@]}")
    common_screen "  --xp-suites $all -> ${SUITE_LIST[*]}"
}

# common_instance_gone NAME -- after a trash or delete: no km process of the
# instance left (by name) and no instance folder. Meant for `common_run`.
common_instance_gone() {
    tdd _smoke instance-gone --instance "$1"
}

# common_tdkserver_expect NAME running|stopped -- `tdd tdkserver status` on the
# instance, asserting the state a stage just produced; tdkserver exits 0 either
# way, so the state is read from its text (`tdd _smoke instance-state`). Meant
# for `common_run`, right after a quickstart/start/stop -- those return before
# the state is fully settled, and a start that "worked" but left nothing
# running is exactly what this catches.
common_tdkserver_expect() {
    local instance="$1" expect="$2" out rc found
    out="$(tdd tdkserver status --instance "$instance" --accept-terms y 2>&1)"
    rc=$?
    printf '%s\n' "$out"
    if [ "$rc" -ne 0 ]; then
        echo "tdkserver status exited $rc"
        return 1
    fi
    found="$(printf '%s\n' "$out" | tdd _smoke instance-state --instance "$instance")" || return 1
    if [ "$found" != "$expect" ]; then
        echo "instance $instance is $found, expected $expect"
        return 1
    fi
    echo "instance $instance is $expect, as expected"
    return 0
}

# common_tabsdata_setup_info common_screen|common_note -- what a smoke script's setup looks like
# right now, for the eyes: the instance and whether its km processes run (by
# name), the venv, and the commands to use, stop and remove them. $1 is the
# printer: `common_screen` outside a stage, `common_note` under one. Reads the script's
# INSTANCE, SERVER, VENV, VENV_TYPE, TDD_DIR_OPT, and the optional SMOKE_DOMAINS,
# XP_PROJECTS, NAMES_PREFIX.
#
# Only what EXISTS is listed. A run that dies in an early stage -- a stale
# credential, a missing system -- has built neither instance nor venv, and
# printing them anyway, with cleanup commands for paths that were never written,
# sends the reader chasing ghosts at the one moment they are trying to read a
# failure. The instance and the venv are on disk, so they are asked; the domains
# and xp projects are not ours to probe cheaply, so each script appends its own
# as it creates them and the lists are taken at their word.
common_tabsdata_setup_info() {
    local out="${1:-common_screen}" running="not running" any=0 venv_dir instance_dir venv_rm="" pids
    instance_dir="$HOME/.tabsdata/instances/$INSTANCE"
    venv_dir="$TDD_DIR_OPT/managed-venvs/$VENV_TYPE/$VENV"
    if [ -e "$venv_dir" ]; then
        any=1
        venv_rm="; tdd venv delete --name $VENV"
    fi
    if [ -e "$instance_dir" ]; then
        any=1
        pids=($(common_instance_pids "$INSTANCE"))
        if [ "${#pids[@]}" -gt 0 ]; then
            running="running (${#pids[@]} processes), server http://$SERVER"
        fi
        "$out" "instance   $INSTANCE -- $running; folder $instance_dir"
    fi
    [ ! -e "$venv_dir" ] || "$out" "venv       $VENV ($VENV_TYPE) at $venv_dir"
    if [ -e "$instance_dir" ]; then
        "$out" "use them   export _TDD_VENV=$VENV; tdd tdk status${PROFILE:+ --profile $PROFILE}; tdd tdkserver status --instance $INSTANCE --accept-terms y"
        "$out" "stop       _TDD_VENV=$VENV tdd tdkserver stop --instance $INSTANCE -y --accept-terms y"
        "$out" "remove     _TDD_VENV=$VENV tdd tdkserver delete --instance $INSTANCE --trash true -y --accept-terms y$venv_rm"
    elif [ -e "$venv_dir" ]; then
        "$out" "remove     tdd venv delete --name $VENV"
    fi
    # Domains the script created itself (SMOKE_DOMAINS) and the xp
    # instances/projects it named (XP_PROJECTS), each with its teardown.
    for d in ${SMOKE_DOMAINS:-}; do
        any=1
        "$out" "domain     $d -- tdd domain destroy --domain $d --force"
    done
    for x in ${XP_PROJECTS:-}; do
        any=1
        "$out" "xp         $x -- tdd xp destroy-project --project $x --force; tdd xp destroy-domains --suite-run $x --force; tdd xp destroy-instance --suite-run $x"
    done
    [ "$any" = 1 ] || "$out" "nothing    this run had built no instance, venv or domain yet"
    [ -z "${NAMES_PREFIX:-}" ] || "$out" "all names  start with $NAMES_PREFIX: tdd domain list, tdd xp list-instances, ls ~/.tabsdata/instances"
}

# The default `common_on_stage_failed`: a failed run leaves everything standing, say
# what and how to reach it. Nothing to say when the script has no instance.
common_on_stage_failed() {
    [ -n "${INSTANCE:-}" ] || return 0
    common_screen ""
    common_screen "$(basename "$0"): left for you to look at"
    common_tabsdata_setup_info common_indented
}

common_indented() {
    common_screen "  $1"
}

# Every stage, one line each, then the total run time.
common_report() {
    local i=0 name status secs
    common_screen ""
    common_screen "$(basename "$0"): stages"
    for name in "${STAGE_NAMES[@]}"; do
        status="${STAGE_STATUS[$i]:-}"
        secs="${STAGE_SECONDS[$i]:-}"
        case "$status" in
            ok) common_screen "  ${GREEN}✓${RESET} $name${secs:+ (${secs}s)}" ;;
            failed) common_screen "  ${RED}✗${RESET} $name (failed${secs:+ after ${secs}s})" ;;
            continued) common_screen "  ${YELLOW}✗${RESET} $name (failed after ${secs}s, continued)" ;;
            *) common_screen "  ${YELLOW}·${RESET} $name (not done)" ;;
        esac
        i=$((i + 1))
    done
    common_screen "$(basename "$0"): total $(common_duration "$(($(date +%s) - RUN_T0))"), log $LOG"
}

# The end: close the last stage, report, verdict. A --continue failure does
# not fail the run; it is named.
common_finish() {
    common_stage_ok
    common_report
    if [ "$CONTINUED" -gt 0 ]; then
        common_screen "${YELLOW}$(basename "$0"): COMPLETED, $CONTINUED stage(s) failed and were continued   (log: $LOG)${RESET}"
    else
        common_screen "${GREEN}$(basename "$0"): ALL STAGES OK   (log: $LOG)${RESET}"
    fi
    exit 0
}
