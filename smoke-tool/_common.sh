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
#   common_set_fn_resources FILE MEMORY DISK
#                                         size the function pods in a tabsdata.yaml, and only them
#   common_fill_pem FILE... -- PLACEHOLDER VALUE
#                                         the same for a multi-line PEM: a YAML block scalar
#   common_placeholders_left DIR          fail while a required placeholder remains in DIR/*.yaml
#                                         `tdkserver status` must agree with the expected state
#   common_tabsdata_setup_info common_screen|common_note
#                                         the instance (running?), the venv, how to use/stop/remove them
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
    w="$(stty size 2>/dev/null </dev/tty | awk '{print $2}')"
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
# everything the log gained since the window opened -- not the log's tail: the
# log also carries a plain copy of every screen line, and replaying the stage
# header and the previous `ok` inside the window read as if the run had looped.
common_window_start() {
    [ "$COLLAPSE" = 1 ] || return 0
    WINDOW_FROM="$(wc -c <"$LOG" 2>/dev/null | tr -d ' ')"
    (
        trap 'exit 0' TERM
        while :; do
            width="$(common_width)"
            lines="$(tail -c +"$((${WINDOW_FROM:-0} + 1))" "$LOG" 2>/dev/null | tail -n "$WINDOW" | tr -d '\r' | sed -E "s/${ESC}\[[0-9;?]*[A-Za-z]//g" | cut -c1-"$((width - 8))")"
            n=0
            while IFS= read -r line; do
                printf '\033[2K      %s%s%s\n' "$DIM" "$line" "$RESET"
                n=$((n + 1))
            done <<LINES
$lines
LINES
            while [ "$n" -lt "$WINDOW" ]; do printf '\033[2K\n'; n=$((n + 1)); done
            printf '\033[%dA' "$WINDOW"
            sleep 0.5
        done
    ) >&3 &
    WINDOW_PID=$!
}

common_window_stop() {
    [ -n "$WINDOW_PID" ] || return 0
    kill "$WINDOW_PID" 2>/dev/null
    wait "$WINDOW_PID" 2>/dev/null
    WINDOW_PID=""
    printf '\033[J' >&3
}

# ---------------------------------------------------------------- masking
# A command line as text with every credential masked: the value after
# --password/-p/--token/--secret/--pat/--*-key/--*-token/--*-secret/--*-password
# (space or = form), the user:password of a URL, and a NAME=value whose NAME says
# PASSWORD/SECRET/TOKEN/KEY/_PAT.
common_display() {
    local out="" arg key mask_next=0
    for arg in "$@"; do
        if [ "$mask_next" = 1 ]; then
            out="$out ***"
            mask_next=0
            continue
        fi
        case "$arg" in
            --password | -p | --token | --secret | --pat | --*-key | --*-token | --*-secret | --*-password)
                out="$out $arg"
                mask_next=1
                ;;
            --password=* | --token=* | --secret=* | --pat=* | --*-key=* | --*-token=* | --*-secret=* | --*-password=*)
                out="$out ${arg%%=*}=***"
                ;;
            *://*:*@*)
                out="$out $(printf '%s' "$arg" | sed -E 's#(://)[^/@]*@#\1***@#')"
                ;;
            *)
                case "$arg" in
                    [A-Za-z_]*=*)
                        key="${arg%%=*}"
                        case "$key" in
                            *PASSWORD* | *SECRET* | *TOKEN* | *KEY* | *_PAT | *_PAT_*) arg="$key=***" ;;
                        esac
                        ;;
                esac
                out="$out $arg"
                ;;
        esac
    done
    printf '%s' "${out# }"
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
# taken from what it wrote to the log since it started (CMD_LOG_FROM), the last
# few distinct ones (a summary comes last), plus any EXTRA "label path" given.
common_pointers() {
    local found
    found="$(tail -c +"$((${CMD_LOG_FROM:-0} + 1))" "$LOG" 2>/dev/null |
        sed -E "s/${ESC}\[[0-9;?]*[A-Za-z]//g" |
        sed -n -E 's#^[[:space:]]*(details|errors|lane log|lane errors|log):[[:space:]]+(/[^[:space:]]+).*#\1 \2#p; s#^.*full output in (/[^[:space:]]+).*#output \1#p' |
        awk '!seen[$0]++' | tail -n 6)"
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
    local attempts="$1" pause="$2" attempt=1 rc
    shift 2
    STAGE_CMDS[${#STAGE_CMDS[@]}]="$(common_display "$@")"
    STAGE_CMD_STATUS[${#STAGE_CMD_STATUS[@]}]="running"
    common_note "${DIM}\$${RESET} $(common_display "$@")   ${DIM}(up to $attempts attempts, ${pause}s apart)${RESET}"
    echo "\$ $(common_display "$@")   (up to $attempts attempts, ${pause}s apart)"
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
            common_stage_failed "$(common_display "$@") failed $attempts times (last exit $rc)" "$rc"
            return 1
        fi
        echo "attempt $attempt/$attempts failed (exit $rc); retrying in ${pause}s"
        attempt=$((attempt + 1))
        sleep "$pause"
    done
}

# ---------------------------------------------------------------- tabsdata instances
# The processes of a tdkserver instance are found BY NAME: every one of them
# (the km supervisor, the servers, the workers it forks) carries the instance
# folder on its command line, `instances/NAME/`. That is how a previous run's
# leftovers are recognised without a pid file to trust.
common_instance_pids() {
    pgrep -f "instances/$1/" 2>/dev/null
}

common_instance_running() {
    common_instance_pids "$1" >/dev/null
}

# A tdkserver able to stop an instance a previous run left behind: one in a
# managed venv under TDD_DIR, else one on PATH that actually runs (a pyenv shim
# may not be wired here). Prints the path, or nothing.
common_previous_tdkserver() {
    local candidate
    for candidate in "$1"/managed-venvs/*/*/bin/tdkserver "$(command -v tdkserver 2>/dev/null)"; do
        if [ -n "$candidate" ] && [ -x "$candidate" ] && "$candidate" --accept-terms y --version >/dev/null 2>&1; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

# common_instance_stop NAME TDD_DIR [TDKSERVER_OPTS...] -- end the km processes of an
# instance a previous run left running, and WAIT until every one is gone.
# Stop it properly first (tdkserver stop), then end the processes still holding
# the folder, then escalate. The wait matters: a km still winding down after a
# TERM escalates to SIGKILL on the pids it tracked ~50s later -- and by then a
# new instance in the same folder has REUSED those pid files, so the new
# cluster is what gets killed (seen: control-plane "process exited (signal 9)"
# 44s into quickstart). Meant for `common_run`: sub-steps go to the log.
common_instance_stop() {
    local instance="$1" tdd_dir="$2" prev waited=0
    shift 2
    if ! common_instance_running "$instance"; then
        echo "no km processes of instance $instance running"
        return 0
    fi
    echo "instance $instance still running ($(common_instance_pids "$instance" | wc -l | tr -d ' ') processes): $(common_instance_pids "$instance" | tr '\n' ' ')"
    prev="$(common_previous_tdkserver "$tdd_dir")"
    if [ -n "$prev" ]; then
        echo "\$ $prev stop --instance $instance $*   (best effort)"
        "$prev" stop --instance "$instance" "$@" || true
    fi
    if common_instance_running "$instance"; then
        echo "\$ pkill -f instances/$instance/   (processes still holding the instance folder)"
        pkill -f "instances/$instance/" || true
    fi
    while common_instance_running "$instance" && [ "$waited" -lt 90 ]; do
        sleep 3
        waited=$((waited + 3))
    done
    if common_instance_running "$instance"; then
        echo "\$ pkill -9 -f instances/$instance/   (still there after ${waited}s)"
        pkill -9 -f "instances/$instance/" || true
        sleep 3
    fi
    if common_instance_running "$instance"; then
        echo "instance $instance still has processes after ${waited}s: $(common_instance_pids "$instance" | tr '\n' ' ')"
        return 1
    fi
    echo "instance $instance gone after ${waited}s"
    return 0
}

# common_tdkserver_pods_running NAME SERVICE... -- the Pods table of
# `tdd tdkserver status`: every SERVICE must have at least one pod named
# `<SERVICE>-...` that is Running and Ready (n/n), and no pod of the instance
# may be in another state. Rows look like `│ srv-apiserver-58cc-pfkch │ Running
# │ 1/1 │ 2s │`; the Pods section runs until the next table title. Meant for
# `common_run_retry`: the pods come up after quickstart/start return.
common_tdkserver_pods_running() {
    local instance="$1" out pods bad missing svc name status ready
    shift
    out="$(tdd tdkserver status --instance "$instance" --accept-terms y 2>&1)" || {
        printf '%s\n' "$out"
        echo "tdkserver status failed"
        return 1
    }
    pods="$(printf '%s\n' "$out" | sed -E "s/$(printf '\033')\[[0-9;]*m//g" | awk '
        /^Pods/ {p=1; next}
        /^(Deployments|CronJobs|Jobs|Services|StatefulSets)/ {p=0}
        p && /^│/ && $2 != "Name" {gsub(/│/, ""); print $1, $2, $3}')"
    if [ -z "$pods" ]; then
        printf '%s\n' "$out"
        echo "no pods listed for instance $instance"
        return 1
    fi
    echo "pods:"
    printf '%s\n' "$pods" | sed 's/^/  /'
    # Ready is `n/m`: ready when both halves agree (awk has no backreferences).
    bad="$(printf '%s\n' "$pods" | awk '{split($3, r, "/")} $2 != "Running" || r[1] != r[2] {print $1 " (" $2 " " $3 ")"}')"
    missing=""
    for svc in "$@"; do
        printf '%s\n' "$pods" | awk -v s="$svc-" '{split($3, r, "/")} index($1, s) == 1 && $2 == "Running" && r[1] == r[2] {found=1} END {exit !found}' \
            || missing="$missing $svc"
    done
    if [ -n "$missing" ] || [ -n "$bad" ]; then
        [ -z "$missing" ] || echo "no Running, Ready pod for:$missing"
        [ -z "$bad" ] || echo "pods not Running/Ready: $(printf '%s' "$bad" | tr '\n' ' ')"
        return 1
    fi
    echo "every expected service pod is Running and Ready: $*"
    return 0
}

# ---------------------------------------------------------------- kubectl / configs
# common_kubeportforward_start KUBECONFIG NAMESPACE SERVICE LOCAL [REMOTE] --
# `kubectl port-forward service/SERVICE LOCAL:REMOTE` in the background, its
# output in the log, kept in PORTFORWARD_PID; returns once LOCAL answers (or
# fails after ~60s). REMOTE defaults to LOCAL. The two are separate because only
# the local side can be taken -- by another run, another forward, a local
# tdkserver -- while the service's port in its own namespace clashes with
# nothing; a script moves LOCAL (--kube-port-forward) and leaves REMOTE the
# apiserver's. One at a time: a running forward is stopped first. A stage
# command by itself, shown as its kubectl line -- call it bare, like the stop.
#
# SUPERVISED. The forward is one long-lived stream through the cluster's tunnel,
# and the tunnel drops on its own: on AKS the node autoprovisioner replacing the
# node that carries the konnectivity agents ended a run's forward mid-suite
# (`error: lost connection to pod`), twice in two days, and every stage after it
# failed in a second as "not logged in". kubectl does not reconnect, so a
# supervisor subshell relaunches it whenever it exits: a drop costs the requests
# in flight and nothing after them. What the start was given is kept in
# PORTFORWARD_ARGS so common_kubeportforward_ensure can start afresh without it.
# The forward still dies with the pods it points at, so it is re-established
# after every tdkserver start/restart, and ended before a stop, restart or
# config/env change, and on exit (`trap common_kubeportforward_stop EXIT`).
common_kubeportforward_start() {
    local kubeconfig="$1" namespace="$2" service="$3" local_port="$4" remote_port="${5:-$4}"
    PORTFORWARD_ARGS=("$kubeconfig" "$namespace" "$service" "$local_port" "$remote_port")
    common_run_shown \
        "kubectl port-forward --kubeconfig $kubeconfig --namespace $namespace service/$service $local_port:$remote_port   (background, relaunched when it exits)" \
        common_kubeportforward_launch "${PORTFORWARD_ARGS[@]}"
}

# The body of the start: what common_run_shown runs and judges.
common_kubeportforward_launch() {
    local kubeconfig="$1" namespace="$2" service="$3" local_port="$4" remote_port="${5:-$4}" waited=0
    common_kubeportforward_stop
    # taken already -- another run, a forward a --keep run left, a local tdkserver:
    # kubectl would fail to bind while the probe below answered, and the run
    # would log in to whatever is there
    if (exec 3<>"/dev/tcp/127.0.0.1/$local_port") 2>/dev/null; then
        echo "127.0.0.1:$local_port is already taken; pick another with --kube-port-forward"
        return 1
    fi
    # The supervisor. kubectl runs in the background of the subshell and is
    # waited for, so a TERM from common_kubeportforward_stop interrupts the wait
    # and the trap ends kubectl and leaves the loop; the pause between relaunches
    # is backgrounded and waited for the same way, so a stop never waits it out.
    # A subshell starts with the script's traps cleared, so the EXIT trap that
    # stops the forward does not run again inside it.
    (
        child=""
        trap '[ -n "$child" ] && kill "$child" 2>/dev/null; exit 0' TERM INT
        while :; do
            kubectl port-forward --kubeconfig "$kubeconfig" --namespace "$namespace" "service/$service" "$local_port:$remote_port" &
            child=$!
            wait "$child"
            echo "port-forward: kubectl exited $? (the tunnel dropped?); relaunching in 2s"
            sleep 2 &
            child=$!
            wait "$child"
        done
    ) >>"$LOG" 2>&1 &
    PORTFORWARD_PID=$!
    while ! (exec 3<>"/dev/tcp/127.0.0.1/$local_port") 2>/dev/null; do
        if ! kill -0 "$PORTFORWARD_PID" 2>/dev/null; then
            echo "port-forward supervisor exited (see the log above)"
            PORTFORWARD_PID=""
            return 1
        fi
        if [ "$waited" -ge 60 ]; then
            echo "port $local_port not answering after ${waited}s (kubectl's exits are in the log above)"
            common_kubeportforward_stop
            return 1
        fi
        sleep 2
        waited=$((waited + 2))
    done
    echo "port-forward up: 127.0.0.1:$local_port -> service/$service:$remote_port in $namespace (supervisor pid $PORTFORWARD_PID)"
    return 0
}

# common_kubeportforward_ensure -- before a stage that needs the server: the
# forward's port answers, or the forward is started afresh from what the last
# start was given. A tunnel drop is recovered by the supervisor within seconds,
# so this first gives it up to 20s; a supervisor that is gone, or a port still
# dead after that, gets a fresh start; and a fresh start that fails fails the
# stage -- in its own words, rather than the suite failing lane by lane with
# "not logged in", which is what a dead forward looks like from tdk. A stage
# command, called bare; in a --continue stage, `|| continue` skips the suite.
common_kubeportforward_ensure() {
    if [ "${#PORTFORWARD_ARGS[@]}" -lt 5 ]; then
        echo "common_kubeportforward_ensure: no forward was started" >&2
        return 1
    fi
    common_run_shown \
        "port-forward 127.0.0.1:${PORTFORWARD_ARGS[3]} -> service/${PORTFORWARD_ARGS[2]}:${PORTFORWARD_ARGS[4]} answering   (started afresh if not)" \
        common_kubeportforward_ensure_body
}

common_kubeportforward_ensure_body() {
    local local_port="${PORTFORWARD_ARGS[3]}" waited=0
    while [ -n "${PORTFORWARD_PID:-}" ] && kill -0 "$PORTFORWARD_PID" 2>/dev/null; do
        if (exec 3<>"/dev/tcp/127.0.0.1/$local_port") 2>/dev/null; then
            [ "$waited" -gt 0 ] && echo "port-forward back after ${waited}s (the supervisor relaunched kubectl)"
            echo "port-forward up: 127.0.0.1:$local_port (supervisor pid $PORTFORWARD_PID)"
            return 0
        fi
        if [ "$waited" -ge 20 ]; then
            echo "port $local_port not answering after ${waited}s with the supervisor alive; starting the forward afresh"
            break
        fi
        sleep 2
        waited=$((waited + 2))
    done
    if [ -z "${PORTFORWARD_PID:-}" ] || ! kill -0 "$PORTFORWARD_PID" 2>/dev/null; then
        echo "port-forward supervisor is gone; starting the forward afresh"
    fi
    common_kubeportforward_launch "${PORTFORWARD_ARGS[@]}"
}

# common_kubeportforward_stop -- end the forward, if one is up. Bare, in a stage or
# from the EXIT trap; a no-op otherwise, so it is safe anywhere. The supervisor
# ends its kubectl on TERM; a kubectl it did not get to end (the supervisor
# killed outright) is swept by its command line, which is this run's alone.
common_kubeportforward_stop() {
    [ -n "${PORTFORWARD_PID:-}" ] || return 0
    kill "$PORTFORWARD_PID" 2>/dev/null
    wait "$PORTFORWARD_PID" 2>/dev/null
    if [ "${#PORTFORWARD_ARGS[@]}" -ge 5 ]; then
        pkill -f "port-forward --kubeconfig ${PORTFORWARD_ARGS[0]} --namespace ${PORTFORWARD_ARGS[1]} service/${PORTFORWARD_ARGS[2]} ${PORTFORWARD_ARGS[3]}:${PORTFORWARD_ARGS[4]}" 2>/dev/null
    fi
    echo "port-forward stopped (supervisor pid $PORTFORWARD_PID)"
    PORTFORWARD_PID=""
}

# common_help REQUIRED -- paint a help page read from stdin the way every tdd
# command paints one: a heading bold, an entry's term cyan. An option whose name
# is in REQUIRED (space separated) is painted RED instead: on a page where half
# a dozen options are mandatory, that belongs where the eye already is and not
# only in the prose. Colours on a terminal only, and never under NO_COLOR.
#
# A painter, not a layout engine: these pages are hand-aligned in the script
# that owns them, so nothing here moves a column.
common_help() {
    # decided HERE, where fd 1 is still the command's stdout: inside $(...) it
    # is the capture pipe and `[ -t 1 ]` would always answer "no terminal"
    local _tdd_tty=0
    [ -t 1 ] && [ -z "${NO_COLOR:-}" ] && _tdd_tty=1
    awk -v required=" $1 " -v tty="$_tdd_tty" '
    BEGIN {
        if (tty) { bold = "\033[1m"; cyan = "\033[36m"; red = "\033[31m"; off = "\033[0m" }
    }
    function painted(l,   start, stop, term, name, colour, m) {
        if (!tty) return l
        if (l ~ /^[a-z][a-z0-9 \/_-]*:$/) { section = 1; return bold l off }
        if (l ~ /^(usage|examples?|options?):( |$)/) {
            m = index(l, ":")
            section = 0
            return bold substr(l, 1, m) off substr(l, m + 1)
        }
        # A line starting at column 1 ends the section it followed: what is
        # indented under a prose paragraph belongs to the paragraph, not to a
        # term list. The closing "drivers added ..." block is exactly that, and
        # its first package name was being painted as if it were an option.
        # (No apostrophes in here: the awk program is inside single quotes.)
        if (l !~ /^ / && l != "") section = 0
        if (section && match(l, /^ {1,6}[^ ]/)) {
            start = RSTART + RLENGTH - 1
            stop = start
            while (stop < length(l) && substr(l, stop + 1, 2) != "  ") stop++
            # a long term sits on a line of its own, its description on the
            # next: there is no two-space run, and the term is the whole line
            if (stop >= length(l)) { stop = length(l); sub(/ +$/, "", l) }
            term = substr(l, start, stop - start + 1)
            name = term
            sub(/[ ,].*/, "", name)
            colour = (index(required, " " name " ") > 0) ? red : cyan
            return substr(l, 1, start - 1) colour term off substr(l, stop + 1)
        }
        return l
    }
    { print painted($0) }'
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

# The named indexes `--uv-index` takes in place of a URL. Here rather than in
# each script, because the four have to mean the same thing by @dev -- and
# because a CloudFront hostname is not something a reader can check by eye on a
# command line, which is the whole point of having a name for it.
COMMON_UV_INDEX_DEV="https://d3mm0r95u5i3hf.cloudfront.net/simple/"
COMMON_UV_INDEX_PROD="https://pypi.tabsdata.com/simple/"

# common_resolve_uv_index VALUE -- print the URL VALUE stands for: `@dev` and
# `@prod` resolve, anything else passes through, and empty stays empty (no
# index asked for). An unknown `@marker` is refused here rather than passed on:
# uv would take it for a URL and fail several stages later, in a message about a
# failed install that says nothing about the option that caused it.
common_resolve_uv_index() {
    case "$1" in
        @dev) printf '%s' "$COMMON_UV_INDEX_DEV" ;;
        @prod) printf '%s' "$COMMON_UV_INDEX_PROD" ;;
        @*)
            # `.sh` stripped: this stands beside the scripts' own option
            # errors, which name themselves without it.
            echo "$(basename "$0" .sh): unknown --uv-index marker: $1 (@dev, @prod, or a URL)" >&2
            return 1
            ;;
        *) printf '%s' "$1" ;;
    esac
}

# common_set_uv_index FILE URI -- point a tabsdata.yaml's UV_INDEX at URI. The
# replacement is a function rather than a template, so nothing in the URI is
# ever read as a backreference, and the line keeps its own indentation.
common_set_uv_index() {
    TDD_UV_INDEX="$2" python3 - "$1" <<'PYEOF'
import os, re, sys

path, uri = sys.argv[1], os.environ["TDD_UV_INDEX"]
with open(path, encoding="utf-8") as fh:
    text = fh.read()
with open(path, "w", encoding="utf-8") as fh:
    fh.write(re.sub(r"(?m)^(\s*UV_INDEX:).*$", lambda m: f"{m.group(1)} {uri}", text))
PYEOF
}

# common_set_fn_resources FILE MEMORY DISK -- size the FUNCTION pods in a
# tabsdata.yaml: the memory: and disk: under pods.function.resources, and only
# those. The file carries a resources block per service as well, so the block is
# found by structure -- the `function:` key, its `resources:` one level in, the
# two lines one level further -- and each value is rewritten on its own line
# with the indentation kept, so tdkserver's shape check against the template
# (StructureMismatch) sees the template's shape. Fails unless exactly one memory
# and one disk line were rewritten: a config that only looks sized is the
# failure to catch here, at configure, not at the first function pod that will
# not schedule. A stage command: call it through common_run.
common_set_fn_resources() {
    TDD_FN_MEMORY="$2" TDD_FN_DISK="$3" python3 - "$1" <<'PYEOF'
import os, re, sys

path = sys.argv[1]
want = {"memory": os.environ["TDD_FN_MEMORY"], "disk": os.environ["TDD_FN_DISK"]}
with open(path, encoding="utf-8") as fh:
    lines = fh.read().splitlines(keepends=True)


def indent(line):
    return len(line) - len(line.lstrip(" "))


def inside(i, depth):
    # still within the block opened at `depth`: deeper, or blank
    return i < len(lines) and (not lines[i].strip() or indent(lines[i]) > depth)


done = {}
i = 0
while i < len(lines):
    fn = re.match(r"^(\s*)function:\s*$", lines[i])
    if not fn:
        i += 1
        continue
    fn_depth = len(fn.group(1))
    i += 1
    while inside(i, fn_depth):
        res = re.match(r"^(\s*)resources:\s*$", lines[i])
        if not res:
            i += 1
            continue
        res_depth = len(res.group(1))
        i += 1
        while inside(i, res_depth):
            key = re.match(r"^(\s*)(memory|disk):.*$", lines[i])
            if key:
                lines[i] = f"{key.group(1)}{key.group(2)}: {want[key.group(2)]}\n"
                done[key.group(2)] = done.get(key.group(2), 0) + 1
            i += 1
if done != {"memory": 1, "disk": 1}:
    sys.stderr.write(
        f"{path}: expected one memory and one disk line under function.resources, rewrote {done or 'none'}\n"
    )
    sys.exit(1)
with open(path, "w", encoding="utf-8") as fh:
    fh.write("".join(lines))
print(f"function pods: memory {want['memory']}, disk {want['disk']}")
PYEOF
}

# common_fill_placeholder FILE... -- PLACEHOLDER VALUE -- replace every literal
# occurrence of PLACEHOLDER (`${{literal:tdk_database_host}}`, `${{secret}}`,
# ...) in the files with VALUE.
#
# A literal replace on both sides: the placeholder holds `${{`, `?` and `:`, and
# the value can be a password, a PEM or JSON, so neither may be read as a
# pattern or as a backreference. The value travels in the environment, never on
# a command line. python3 rather than sed (which would interpret both sides) or
# perl (which would not, but is a second interpreter for what these scripts
# already do in python -- see common_fill_pem and each script's fill_storage).
common_fill_placeholder() {
    local files=()
    while [ $# -gt 0 ] && [ "$1" != "--" ]; do files[${#files[@]}]="$1"; shift; done
    shift
    PH="$1" VAL="$2" python3 - "${files[@]}" <<'PYEOF'
import os, sys

ph, val = os.environ["PH"], os.environ["VAL"]
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    if ph in text:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text.replace(ph, val))
PYEOF
}

# common_fill_pem FILE... -- PLACEHOLDER VALUE -- replace a whole `key: PLACEHOLDER`
# line with a YAML block scalar holding VALUE. What a multi-line certificate needs:
# substituted inline the way common_fill_placeholder does it, a PEM's newlines
# would continue the plain scalar and YAML would fold them into spaces -- the file
# still parses, and then no certificate ever loads. The block is indented two past
# the key's own indent, so it works wherever the key sits. Refuses an empty value
# or a placeholder that is not there: both leave a config that only looks filled.
common_fill_pem() {
    local files=()
    while [ $# -gt 0 ] && [ "$1" != "--" ]; do files[${#files[@]}]="$1"; shift; done
    shift
    PH="$1" VAL="$2" python3 - "${files[@]}" <<'PEMEOF'
import os, sys

ph, val = os.environ["PH"], os.environ["VAL"].strip()
if not val:
    sys.exit(f"nothing to fill {ph} with: the value is empty")
hits = 0
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as fh:
        lines = fh.readlines()
    out = []
    for line in lines:
        if ph not in line:
            out.append(line)
            continue
        hits += 1
        key = line.split(":", 1)[0]
        pad = " " * (len(key) - len(key.lstrip()) + 2)
        out.append(f"{key}: |\n")
        out.extend(f"{pad}{one}\n" for one in val.splitlines())
    if out != lines:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("".join(out))
if not hits:
    sys.exit(f"{ph} is not in any of: {' '.join(sys.argv[1:])}")
print(f"filled {ph} with {len(val.splitlines())} lines of PEM")
PEMEOF
}

# common_placeholders_left DIR -- fail, listing them, while a REQUIRED
# placeholder remains in DIR/*.yaml: `${{literal:..}}` or `${{secret:..}}` /
# `${{secret}}` without the optional `?`. `system:` and `secretAuto:` are
# tabsdata's to fill; `?` ones may stay. Meant for `common_run`.
common_placeholders_left() {
    local left
    # unfilled placeholder lines hold no values, so they are shown as they are
    left="$(grep -nE '\$\{\{(literal|secret)(:[^}?]*)?\}\}' "$1"/*.yaml 2>/dev/null)"
    if [ -n "$left" ]; then
        echo "required placeholders still to fill:"
        printf '%s\n' "$left" | sed 's/^/  /'
        return 1
    fi
    echo "no required placeholder left in $1"
    return 0
}

# common_instance_gone NAME -- after `tdkserver delete --trash true`: no km
# process of the instance left (by name) and no instance folder. Meant for
# `common_run`.
common_instance_gone() {
    local instance="$1" folder="$HOME/.tabsdata/instances/$1" rc=0
    if common_instance_running "$instance"; then
        echo "instance $instance still has processes: $(common_instance_pids "$instance" | tr '\n' ' ')"
        rc=1
    fi
    if [ -e "$folder" ]; then
        echo "instance folder still exists: $folder"
        rc=1
    fi
    [ "$rc" = 0 ] && echo "instance $instance is gone: no processes, no folder"
    return "$rc"
}

# common_tdkserver_expect NAME running|stopped -- `tdd tdkserver status` on the
# instance, asserting the state a stage just produced. tdkserver exits 0 either
# way. kminus says `Instance 'NAME' is not running.` when stopped and lists the
# workloads otherwise; eks always draws the Deployments/Pods/CronJobs/Jobs tables
# and says nothing -- stopped is the tables being empty. So a sentence decides
# when there is one, else the Deployments and Pods rows do: none means stopped.
# Meant for `common_run`, right after a quickstart/start/stop -- those return
# before the state is fully settled, and a start that "worked" but left nothing
# running is exactly what this catches.
common_tdkserver_expect() {
    local instance="$1" expect="$2" out rc
    out="$(tdd tdkserver status --instance "$instance" --accept-terms y 2>&1)"
    rc=$?
    printf '%s\n' "$out"
    if [ "$rc" -ne 0 ]; then
        echo "tdkserver status exited $rc"
        return 1
    fi
    case "$out" in
        *"does not exist"*) rc=missing ;;
        *"is not running"* | *"is stopped"* | *"was already stopped"*) rc=stopped ;;
        *"Deployments"*"┌"*)
            if [ "$(common_tdkserver_workload_rows "$out")" -gt 0 ]; then rc=running; else rc=stopped; fi ;;
        *) rc=running ;;
    esac
    if [ "$rc" != "$expect" ]; then
        echo "instance $instance is $rc, expected $expect"
        return 1
    fi
    echo "instance $instance is $expect, as expected"
    return 0
}

# common_tdkserver_workload_rows OUTPUT -- how many data rows the Deployments and
# Pods tables of a `tdkserver status` listing hold (the rows between a table's
# `├` rule and its `└` bottom). Jobs and CronJobs are left out: a completed init
# job can outlive a stop, a deployment or pod cannot.
common_tdkserver_workload_rows() {
    printf '%s\n' "$1" | awk '
        /^(Deployments|Pods)[[:space:]]*$/ { keep = 1; next }
        /^(CronJobs|Jobs)[[:space:]]*$/    { keep = 0; next }
        /^├/ { body = 1; next }
        /^└/ { body = 0; next }
        keep && body && /^│/ { n++ }
        END { print n + 0 }'
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
    local out="${1:-common_screen}" running="not running" any=0 venv_dir instance_dir venv_rm=""
    instance_dir="$HOME/.tabsdata/instances/$INSTANCE"
    venv_dir="$TDD_DIR_OPT/managed-venvs/$VENV_TYPE/$VENV"
    if [ -e "$venv_dir" ]; then
        any=1
        venv_rm="; tdd venv delete --name $VENV"
    fi
    if [ -e "$instance_dir" ]; then
        any=1
        if common_instance_running "$INSTANCE"; then
            running="running ($(common_instance_pids "$INSTANCE" | wc -l | tr -d ' ') processes), server http://$SERVER"
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
