#!/usr/bin/env bash
#
# Copyright 2026 Tabsdata Inc.
#

# Tabsdata EKS smoke test.
#
# Every name this run creates starts with sm_<NAME> (--name): the instance and
# the venv ARE sm_<NAME>; domains and xp instances/projects are sm_<NAME>__<what>;
# the k8s namespace is sm-<name>. The kminus flavour is tabsdata-km-smoke.sh.

set -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

usage() {
    cat <<'HELP'
usage: tabsdata-eks-smoke.sh --name NAME --tabsdata-version VERSION [--tabsdata-extras EXTRAS]
                   [--venv-type pyenv|uv|conda] [--python-version VERSION]
                   [--kubeconfig FILE] [--uv-index URI] [--suites LIST]
                   [--llm anthropic|openai] [--expect-pods LIST] [--force] [--keep]
                   [--stop-after STAGE] [--log FILE] [--tdd-dir DIR] [--verbose]

Tabsdata EKS smoke test.

options:
  --name NAME         REQUIRED: the run's name, alphanumeric. Everything created
                      is sm_NAME -- the tdkserver instance and the managed venv --
                      or sm_NAME__<what> (domains, xp instances/projects); the
                      k8s namespace is sm-<name> (lowercased: RFC 1123)
  --tabsdata-version VERSION
                      REQUIRED: the tabsdata release to install, tabsdata[EXTRAS]==VERSION
  --tabsdata-extras EXTRAS
                      the extras to install (default: all)
  --venv-type TYPE    pyenv, uv or conda (default: pyenv)
  --python-version VERSION
                      interpreter for the venv (default: 3.12.13 -- the exact
                      version the instance builds its own environments with)
  --kubeconfig FILE   the EKS kubeconfig (default: ~/.kube/config); exported as
                      KUBECONFIG for tdkserver and passed to every kubectl
  --uv-index URI      Python package index (default: none): used by the tabsdata
                      install and written into tabsdata.yaml (UV_INDEX) for the pods
  --suites LIST       comma-separated xp suite selectors, one stage each
                      (default: test,tableframe_api,dataquality,grok/s3_examples,
                      grok/s3_world_csv,cloud-connectors -- container-connectors and
                      the fs-backed grok suites stay out: docker systems and local
                      paths are unreachable from function pods running in EKS)
  --llm anthropic|openai
                      create a domain on that system (sm_NAME__llm_<llm>), read its
                      API key and write it into aiagent.yaml (default: no LLM)
  --expect-pods LIST  service names whose pods must be Running and Ready after
                      every start, per `tdkserver status` (default: srv-apiserver)
  -f, --force         a venv, instance or namespace of this name already existing
                      is an error unless this is given: then they are removed and
                      recreated (default: fail)
  --keep              on success, leave everything as it is: instance running,
                      namespace, domains, venv, xp setups (xp one-shot --keep);
                      the port-forward is still stopped -- the closing report
                      prints the command to re-establish it
                      (default: no -- domains destroyed, instance deleted,
                      namespace deleted, venv deleted; a failed run always
                      leaves everything standing)
  --stop-after STAGE  stop (exit 0, everything left standing) after the named
                      stage -- any name the screen prints, e.g. systems, configure,
                      forward-1, xp-<suite> (/ replaced by _), cleanup
  --log FILE          log file (default: /tmp/smoke-sm_NAME-<start time>.log)
  --tdd-dir DIR       the tdd dir to source (default: $TDD_DIR, else ~/.tdd)
  --verbose           show every command's output as it happens (default: a
                      rolling window of the running command's last lines)
  -h, --help          this help

The drivers added to the instance's fn and ag venvs (tdkserver venv update):
  mysql-connector-python==9.6.0  psycopg2-binary==2.9.12  oracledb==3.2.0
HELP
}

NAME=""                  # required; everything is sm_$NAME
LLM=""                   # anthropic | openai | empty
EXPECT_PODS="srv-apiserver"
VENV_TYPE="pyenv"
PYTHON="3.12.13"
TABSDATA_VERSION=""      # required
TABSDATA_EXTRAS="all"
KUBECONFIG_OPT="$HOME/.kube/config"
PORT="2457"              # tdkserver's apiserver port; the port-forward mirrors it locally
UV_INDEX_URI=""
# grok only through its s3 sub-suites: the fs-backed ones stage files on a local
# path the EKS function pods cannot see.
SUITES="test,tableframe_api,dataquality,grok/s3_examples,grok/s3_world_csv,cloud-connectors"
FORCE=""                 # 1 with --force; empty otherwise
KEEP=""                  # 1 with --keep; empty otherwise (so ${KEEP:+--keep} works)
STOP_AFTER=""
LOG=""
VERBOSE=0
TDD_DIR_OPT="${TDD_DIR:-$HOME/.tdd}"
REQUIREMENTS="mysql-connector-python==9.6.0
psycopg2-binary==2.9.12
oracledb==3.2.0"

while [ $# -gt 0 ]; do
    case "$1" in
        --name) NAME="$2"; shift 2 ;;
        --llm) LLM="$2"; shift 2 ;;
        --expect-pods) EXPECT_PODS="$2"; shift 2 ;;
        --venv-type) VENV_TYPE="$2"; shift 2 ;;
        --python-version) PYTHON="$2"; shift 2 ;;
        --tabsdata-version) TABSDATA_VERSION="$2"; shift 2 ;;
        --tabsdata-extras) TABSDATA_EXTRAS="$2"; shift 2 ;;
        --kubeconfig) KUBECONFIG_OPT="$2"; shift 2 ;;
        --uv-index) UV_INDEX_URI="$2"; shift 2 ;;
        --suites) SUITES="$2"; shift 2 ;;
        --force | -f) FORCE=1; shift ;;
        --keep) KEEP=1; shift ;;
        --stop-after) STOP_AFTER="$2"; shift 2 ;;
        --log) LOG="$2"; shift 2 ;;
        --tdd-dir) TDD_DIR_OPT="$2"; shift 2 ;;
        --verbose) VERBOSE=1; shift ;;
        -h | --help) usage; exit 0 ;;
        *) echo "tabsdata-eks-smoke: unknown option: $1 (see --help)" >&2; exit 1 ;;
    esac
done
case "$VENV_TYPE" in pyenv | uv | conda) ;; *) echo "tabsdata-eks-smoke: --venv-type must be pyenv, uv or conda" >&2; exit 1 ;; esac
case "$LLM" in "" | anthropic | openai) ;; *) echo "tabsdata-eks-smoke: --llm must be anthropic or openai" >&2; exit 1 ;; esac
case "$NAME" in *[!A-Za-z0-9]*) echo "tabsdata-eks-smoke: --name must be alphanumeric (it becomes part of domain and namespace names)" >&2; exit 1 ;; "") echo "tabsdata-eks-smoke: --name NAME is required (everything created is sm_NAME)" >&2; exit 1 ;; esac
if [ -z "$TABSDATA_VERSION" ]; then
    echo "tabsdata-eks-smoke: --tabsdata-version VERSION is required (the tabsdata release to install)" >&2
    exit 1
fi
if [ ! -r "$KUBECONFIG_OPT" ]; then
    echo "tabsdata-eks-smoke: no kubeconfig at $KUBECONFIG_OPT (pass --kubeconfig)" >&2
    exit 1
fi
# the k8s namespace must be RFC 1123 (lowercase, hyphens), hence sm-<name>
BASE="sm_$NAME"
NAMES_PREFIX="$BASE"     # what the failure summary tells the reader to look for
INSTANCE="$BASE"
VENV="$BASE"
NAMESPACE="sm-$(printf '%s' "$NAME" | tr 'A-Z' 'a-z')"
STAMP="$(date +%Y%m%d-%H%M%S)"
RDS_DOMAIN="${BASE}__rds"
S3_DOMAIN="${BASE}__s3"
LLM_DOMAIN="${LLM:+${BASE}__llm_${LLM}}"
XP_PROJECTS=""           # the xp instance/project names this run creates, for --keep and failures
SMOKE_DOMAINS="$RDS_DOMAIN $S3_DOMAIN $LLM_DOMAIN"
EXPECT_POD_LIST="$(printf '%s' "$EXPECT_PODS" | tr ',' ' ')"
LOG="${LOG:-/tmp/smoke-$INSTANCE-$STAMP.log}"
WORK="$(mktemp -d "/tmp/smoke-$INSTANCE-$STAMP.XXXX")"
SERVER="http://127.0.0.1:$PORT"
TABSDATA_SPEC="tabsdata[$TABSDATA_EXTRAS]==$TABSDATA_VERSION"
TDK_OPTS=(-y --accept-terms y)
CONFIGS="$HOME/.tabsdata/instances/$INSTANCE/init/input/configs"
export KUBECONFIG="$KUBECONFIG_OPT"   # start/stop/create resolve the cluster from it; init wants it as --kubeconfig
KUBECTL=(kubectl --kubeconfig "$KUBECONFIG_OPT")
SUITE_LIST=()
for suite in $(printf '%s' "$SUITES" | tr ',' ' '); do SUITE_LIST[${#SUITE_LIST[@]}]="$suite"; done
if [ "${#SUITE_LIST[@]}" -eq 0 ]; then
    echo "tabsdata-eks-smoke: --suites needs at least one selector" >&2
    exit 1
fi
STAGE_NAMES=(unset-td unset-pypi set-crypto systems pycache clean-previous create-venv install)
[ "$TABSDATA_VERSION" = "2.0.2" ] && STAGE_NAMES[${#STAGE_NAMES[@]}]="cdc-driver"
for stage in domains namespace init configure create start-1 pods-1 forward-1 login-1 stop-1 venv-update start-2 pods-2 forward-2 login-2; do STAGE_NAMES[${#STAGE_NAMES[@]}]="$stage"; done
for suite in "${SUITE_LIST[@]}"; do STAGE_NAMES[${#STAGE_NAMES[@]}]="xp-$(printf '%s' "$suite" | tr '/' '_')"; done
STAGE_NAMES[${#STAGE_NAMES[@]}]="cleanup"

# shellcheck disable=SC1091
. "$HERE/_common.sh"

# What this run would create must not already exist -- someone's setup could be
# behind those names. --force says they are ours to replace.
if [ -z "$FORCE" ]; then
    EXISTING=""
    for d in "$TDD_DIR_OPT"/managed-venvs/*/"$VENV"; do
        [ -e "$d" ] && EXISTING="$EXISTING venv:$d"
    done
    [ -e "$HOME/.tabsdata/instances/$INSTANCE" ] && EXISTING="$EXISTING instance:$HOME/.tabsdata/instances/$INSTANCE"
    "${KUBECTL[@]}" get namespace "$NAMESPACE" >/dev/null 2>&1 && EXISTING="$EXISTING namespace:$NAMESPACE"
    if [ -n "$EXISTING" ]; then
        echo "tabsdata-eks-smoke: already exists:$EXISTING" >&2
        echo "tabsdata-eks-smoke: pass --force to delete and recreate them, or pick another --name" >&2
        exit 1
    fi
fi

common_init "$LOG" "$VERBOSE"
trap common_kubeportforward_stop EXIT      # the forward never outlives the script

# the generic failure block plus the EKS pieces
common_on_stage_failed() {
    common_screen ""
    common_screen "$(basename "$0"): left for you to look at"
    common_tabsdata_setup_info common_indented
    common_indented "namespace  $NAMESPACE on the cluster of $KUBECONFIG_OPT -- kubectl delete namespace $NAMESPACE (the context still points at it)"
    common_indented "reach it   kubectl port-forward --kubeconfig $KUBECONFIG_OPT --namespace $NAMESPACE service/net-apiserver $PORT:$PORT &   then: _TDD_VENV=$VENV tdd tdk login --server $SERVER"
}

# fill_storage FILE -- the twelve positional ${{secret}} of apiserver.storage.yaml:
# per mount (ROOT/BUNDLES/IMAGES) the uri under the s3 domain's URI, and the s3
# system's region/credentials on every mount. Values travel in the environment
# (they are credentials); python because awk/sed would fight the &/\ a secret may hold.
fill_storage() {
    ST_FILE="$1" python3 - <<'PYEOF'
import os, re
path = os.environ["ST_FILE"]
uri = os.environ["S3D__URI"].rstrip("/")
sub = {"ROOT": f"{uri}/data/", "BUNDLES": f"{uri}/bundles/", "IMAGES": f"{uri}/images/"}
fixed = {
    "aws_region": os.environ.get("S3S__REGION", ""),
    "aws_access_key_id": os.environ.get("S3S__ACCESS_KEY", ""),
    "aws_secret_access_key": os.environ.get("S3S__SECRET_KEY", ""),
}
out, mount = [], None
for line in open(path):
    m = re.match(r"\s*- id: (\w+)", line)
    if m:
        mount = m.group(1)
    if "${{secret}}" in line:
        key = line.split(":", 1)[0].strip()
        if key == "uri" and mount in sub:
            line = line.replace("${{secret}}", sub[mount])
        elif key in fixed:
            line = line.replace("${{secret}}", fixed[key])
    out.append(line)
open(path, "w").write("".join(out))
PYEOF
}

common_screen "tabsdata-eks-smoke: effective options"
common_screen "  --name              $NAME   -> instance and venv $BASE, namespace $NAMESPACE, domains ${BASE}__<what>"
common_screen "  --venv-type         $VENV_TYPE"
common_screen "  --python-version    $PYTHON"
common_screen "  --tabsdata-version  $TABSDATA_VERSION"
common_screen "  --tabsdata-extras   $TABSDATA_EXTRAS   -> installs $TABSDATA_SPEC"
common_screen "  --kubeconfig        $KUBECONFIG_OPT   (exported as KUBECONFIG)"
common_screen "  --uv-index          $(common_display "${UV_INDEX_URI:-(none)}")"
common_screen "  --suites            $SUITES   -> xp projects ${BASE}__xp_<ts>_<suite>"
common_screen "  --llm               ${LLM:-(none)}${LLM:+   -> domain $LLM_DOMAIN}"
common_screen "  --expect-pods       $EXPECT_PODS"
common_screen "  --force             $([ -n "$FORCE" ] && echo "yes (replace an existing venv/instance/namespace)" || echo "no (an existing one is an error)")"
common_screen "  --keep              $([ -n "$KEEP" ] && echo "yes (also: xp one-shot --keep)" || echo "no (domains, instance, namespace and venv deleted at the end)")"
common_screen "  --stop-after        ${STOP_AFTER:-(run everything)}"
common_screen "  --log               $LOG"
common_screen "  --tdd-dir           $TDD_DIR_OPT"
common_screen "  --verbose           $([ "$VERBOSE" = 1 ] && echo yes || echo "no (rolling window of $WINDOW log lines)")"
common_screen "  server              $SERVER through kubectl port-forward service/net-apiserver"
common_screen "  drivers for fn/ag   $(printf '%s' "$REQUIREMENTS" | tr '\n' ' ')"
if [ ! -r "$TDD_DIR_OPT/tdd-source.sh" ]; then
    common_screen "${RED}tabsdata-eks-smoke: no tdd dir at $TDD_DIR_OPT (tdd-source.sh missing); install with cargo make install or pass --tdd-dir${RESET}"
    exit 1
fi
# shellcheck disable=SC1090
. "$TDD_DIR_OPT/tdd-source.sh"

tdd venv deactivate >/dev/null 2>&1 || true

common_stage unset-td "unset every TD_* variable (tdd env unset --td spares the crypto key)"
common_run tdd env unset --td
common_checkpoint unset-td

common_stage unset-pypi "unset the Python package index variables"
common_run tdd env unset --py-idx --py-default-idx
common_checkpoint unset-pypi

common_stage set-crypto "set _TDD_CRYPTO_KEY"
common_run tdd env set --crypto
common_checkpoint set-crypto

common_stage systems "dev and fs, awspostgres, s3 (and --llm) plus every system the suites need must be in the tdd store"
# checked UPFRONT: a run missing one must fail before anything is built
common_run tdd system create --type dev --sys dev --force
# fs needs an explicit absolute root: its default is target/backends/<name>
# against the CWD, which once landed inside a checkout.
common_run tdd system create --type fs --sys fs --sys-path "$TDD_DIR_OPT/data/fs-root" --force
for suite in "${SUITE_LIST[@]}"; do
    common_run tdd xp list-systems --suite "$suite"
done
common_run tdd system status --sys awspostgres
common_run tdd system status --sys s3
[ -z "$LLM" ] || common_run tdd system status --sys "$LLM"
common_checkpoint systems

common_stage pycache "purge tabsdata from the uv and pip caches"
common_run tdd pycache clean
common_checkpoint pycache

common_stage clean-previous "remove what a previous $INSTANCE left (--force; nothing exists otherwise)"
# scoped to THIS run's names; the namespace delete waits -- a create over a
# Terminating namespace fails confusingly
if [ -d "$HOME/.tabsdata/instances/$INSTANCE" ]; then
    common_note "a previous instance folder exists; best-effort delete, then remove it"
    tdd tdkserver delete --instance "$INSTANCE" --trash true "${TDK_OPTS[@]}" || true
    common_run rm -rf "$HOME/.tabsdata/instances/$INSTANCE"
fi
if "${KUBECTL[@]}" get namespace "$NAMESPACE" >/dev/null 2>&1; then
    common_run "${KUBECTL[@]}" delete namespace "$NAMESPACE" --wait=true --timeout=180s
fi
common_checkpoint clean-previous

common_stage create-venv "leave any active venv, then create and activate the managed venv $VENV ($VENV_TYPE, python $PYTHON)"
# Whatever this shell was in has to go first: `tdd venv create` refuses under a
# venv tdd did not activate, and the one a developer is most likely to be
# standing in -- their project's own -- is exactly that. --force is what leaves
# one tdd did not enter, and says "no venv was active" rather than failing when
# the shell is already clean.
common_run tdd venv deactivate --force
# shellcheck disable=SC2086
common_run tdd venv create --name "$VENV" --type "$VENV_TYPE" --python "$PYTHON" ${FORCE:+--force}
common_checkpoint create-venv

common_stage install "uv pip install $TABSDATA_SPEC into $VENV"
# shellcheck disable=SC2086
common_run uv pip install ${UV_INDEX_URI:+--index "$UV_INDEX_URI" --index-strategy unsafe-best-match} "$TABSDATA_SPEC"
for program in tdkserver tdk; do
    common_run test -x "$(dirname "$(command -v python)")/$program"
done
common_checkpoint install

# tabsdata 2.0.2 ships no psycopg2 with its Postgres connector (it sits in the
# `test` extra), yet the CDC plugin imports it when tdk loads the connectors, so
# every postgrescdc collection create fails. Until tabsdata ships it, put it in
# the client venv for that version -- and say so, since it is not tabsdata's own.
if [ "$TABSDATA_VERSION" = "2.0.2" ]; then
    common_stage cdc-driver "tabsdata 2.0.2 workaround: psycopg2-binary into $VENV for the Postgres CDC plugin"
    # shellcheck disable=SC2086
    common_run uv pip install ${UV_INDEX_URI:+--index "$UV_INDEX_URI" --index-strategy unsafe-best-match} psycopg2-binary==2.9.11
    common_checkpoint cdc-driver
    common_remark "workaround: tabsdata 2.0.2 ships no psycopg2 with its Postgres connector; psycopg2-binary was installed into $VENV so the CDC plugin loads"
fi

common_stage domains "domains $RDS_DOMAIN, $S3_DOMAIN${LLM:+, $LLM_DOMAIN} -- the instance's database, storage${LLM:+ and LLM key}"
# Each domain is this run's slice of the shared system. Values are eval'd into
# THIS shell, never echoed; they fill the config files below.
common_run tdd domain create --sys awspostgres --domain "$RDS_DOMAIN" --force
common_note "eval \$(tdd domain info --domain $RDS_DOMAIN --format export --prefix RDS)   (values not shown)"
eval "$(tdd domain info --domain "$RDS_DOMAIN" --format export --prefix RDS 2>/dev/null)"
common_run test -n "${RDS__EXTERNAL_HOST:+set}${RDS__PORT:+set}${RDS__DATABASE:+set}${RDS__USER:+set}${RDS__PASSWORD:+set}"
# A postgres domain names both networks its instance answers on, and the address
# that matters here is the pods', not this laptop's: the function pods reach the
# instance from inside the VPC, which is what INTERNAL_HOST holds. Falling back
# to the external one covers an RDS endpoint that is reachable either way (the
# usual case, and the single endpoint that worked before the split).
RDS_POD_HOST="${RDS__INTERNAL_HOST:-$RDS__EXTERNAL_HOST}"
if [ -n "${RDS__INTERNAL_HOST:-}" ]; then
    common_note "database: the pods get awspostgres's INTERNAL_HOST (its in-VPC address)"
else
    common_remark "awspostgres records no INTERNAL_HOST; the pods get EXTERNAL_HOST ($RDS__EXTERNAL_HOST) -- fine if that endpoint routes from inside the cluster, and the reason to record the private one if it does not"
fi
common_run tdd domain create --sys s3 --domain "$S3_DOMAIN" --force
common_note "eval \$(tdd domain info --domain $S3_DOMAIN --format export --prefix S3D; tdd system info --sys s3 --format export --prefix S3S)"
eval "$(tdd domain info --domain "$S3_DOMAIN" --format export --prefix S3D 2>/dev/null)"
eval "$(tdd system info --sys s3 --format export --prefix S3S 2>/dev/null)"
common_run test -n "${S3D__URI:+set}${S3S__REGION:+set}"
if [ -n "$LLM" ]; then
    common_run tdd domain create --sys "$LLM" --domain "$LLM_DOMAIN" --force
    common_note "eval \$(tdd domain info --domain $LLM_DOMAIN --format export --prefix LLM)   (the key is not shown)"
    eval "$(tdd domain info --domain "$LLM_DOMAIN" --format export --prefix LLM 2>/dev/null)"
    common_run test -n "${LLM__API_KEY:+set}"
fi
common_checkpoint domains

common_stage namespace "create the namespace $NAMESPACE and point the kubeconfig context at it"
# tdkserver reads the namespace from the current context, not a flag
PREV_NAMESPACE="$("${KUBECTL[@]}" config view --minify -o jsonpath='{.contexts[0].context.namespace}' 2>/dev/null)"
common_note "current context namespace: ${PREV_NAMESPACE:-(none)} (restored at cleanup)"
common_run "${KUBECTL[@]}" create namespace "$NAMESPACE"
common_run "${KUBECTL[@]}" config set-context --current --namespace "$NAMESPACE"
common_checkpoint namespace

common_stage init "tdkserver init --provider eks --instance $INSTANCE (the editable config folder)"
common_run tdd tdkserver init --provider eks --instance "$INSTANCE" --kubeconfig "$KUBECONFIG_OPT" "${TDK_OPTS[@]}"
common_run test -d "$CONFIGS"
common_checkpoint init

common_stage configure "fill the config files from the domains: database, storage, LLM key, uv index"
# Named placeholders are shared across files; the storage file's ${{secret}}
# are positional. Values travel in the environment, never on a command line.
common_note "database: \${{literal:tdk_database_*}} and \${{secret:postgres_system_*}} from $RDS_DOMAIN"
common_fill_placeholder "$CONFIGS"/*.yaml -- '${{literal:tdk_database_host}}' "$RDS_POD_HOST"
common_fill_placeholder "$CONFIGS"/*.yaml -- '${{literal:tdk_database_port}}' "$RDS__PORT"
common_fill_placeholder "$CONFIGS"/*.yaml -- '${{literal:tdk_database_name}}' "$RDS__DATABASE"
common_fill_placeholder "$CONFIGS"/*.yaml -- '${{secret:postgres_system_user}}' "$RDS__USER"
common_fill_placeholder "$CONFIGS"/*.yaml -- '${{secret:postgres_system_password}}' "$RDS__PASSWORD"
common_note "storage: the ROOT/BUNDLES/IMAGES mounts under ${S3D__URI%/}/ with the s3 system's credentials"
fill_storage "$CONFIGS/apiserver.storage.yaml"
if [ -n "$LLM" ]; then
    common_note "aiagent: the $LLM key from $LLM_DOMAIN"
    common_fill_placeholder "$CONFIGS/aiagent.yaml" -- "\${{secret:$LLM-key?}}" "$LLM__API_KEY"
fi
if [ -n "$UV_INDEX_URI" ]; then
    common_note "tabsdata.yaml: UV_INDEX -> $(common_display "$UV_INDEX_URI")"
    UVX="$UV_INDEX_URI" perl -pi -e 's/^(\s*UV_INDEX:).*$/$1 $ENV{UVX}/' "$CONFIGS/tabsdata.yaml"
fi
common_run common_placeholders_left "$CONFIGS"
common_run tdd tdkserver config check --instance "$INSTANCE" --init --accept-terms y
common_checkpoint configure

common_stage create "tdkserver create (upload the config), then delete the plaintext input folder"
common_run tdd tdkserver create --instance "$INSTANCE" --port "$PORT" "${TDK_OPTS[@]}"
# the input folder holds the secrets in plain text; create uploaded them --
# `config get --with-secrets` fetches them back
common_run rm -rf "$HOME/.tabsdata/instances/$INSTANCE/init"
common_checkpoint create

common_stage start-1 "tdkserver start (the first start builds environments and runs the db setup)"
common_run tdd tdkserver start --instance "$INSTANCE" "${TDK_OPTS[@]}"
common_run common_tdkserver_expect "$INSTANCE" running
common_checkpoint start-1

common_stage pods-1 "every expected service pod is Running: $EXPECT_PODS"
# shellcheck disable=SC2086
common_run_retry 30 10 common_tdkserver_pods_running "$INSTANCE" $EXPECT_POD_LIST
common_checkpoint pods-1

common_stage forward-1 "kubectl port-forward service/net-apiserver $PORT:$PORT (background)"
common_kubeportforward_start "$KUBECONFIG_OPT" "$NAMESPACE" net-apiserver "$PORT"
common_checkpoint forward-1

common_stage login-1 "tdk login as admin on $SERVER"
common_run_retry 30 5 tdd tdk login --server "$SERVER" --user admin --password tabsdata
common_checkpoint login-1

common_stage stop-1 "tdkserver stop (the port-forward dies with the pods)"
# rule: end the port-forward before tabsdata stops, restarts, or takes a tdkserver
# config or env change -- it holds the pods' connections and dies with them
common_kubeportforward_stop
common_run tdd tdkserver stop --instance "$INSTANCE" "${TDK_OPTS[@]}"
common_run common_tdkserver_expect "$INSTANCE" stopped
common_checkpoint stop-1

common_stage venv-update "update the instance's fn and ag venvs with the DB drivers"
printf '%s\n' "$REQUIREMENTS" > "$WORK/requirements.txt"
common_note "requirements: $(printf '%s' "$REQUIREMENTS" | tr '\n' ' ')"
for name in fn ag; do
    common_run tdd tdkserver venv update --instance "$INSTANCE" --name "$name" --requirements "$WORK/requirements.txt" "${TDK_OPTS[@]}"
done
common_checkpoint venv-update

common_stage start-2 "tdkserver start"
common_run tdd tdkserver start --instance "$INSTANCE" "${TDK_OPTS[@]}"
common_run common_tdkserver_expect "$INSTANCE" running
common_checkpoint start-2

common_stage pods-2 "every expected service pod is Running: $EXPECT_PODS"
# shellcheck disable=SC2086
common_run_retry 30 10 common_tdkserver_pods_running "$INSTANCE" $EXPECT_POD_LIST
common_checkpoint pods-2

common_stage forward-2 "kubectl port-forward service/net-apiserver $PORT:$PORT (re-established after start)"
common_kubeportforward_start "$KUBECONFIG_OPT" "$NAMESPACE" net-apiserver "$PORT"
common_checkpoint forward-2

common_stage login-2 "tdk login as admin on $SERVER"
common_run_retry 30 5 tdd tdk login --server "$SERVER" --user admin --password tabsdata
common_checkpoint login-2

for suite in "${SUITE_LIST[@]}"; do
    project="${BASE}__xp_$(date -u +%Y%m%dT%H%M%S)_$(printf '%s' "$suite" | tr -c 'A-Za-z0-9\n' '_')"
    XP_PROJECTS="$XP_PROJECTS $project"
    common_stage --continue "xp-$(printf '%s' "$suite" | tr '/' '_')" "xp one-shot $suite as $project (continue on error)"
    # shellcheck disable=SC2086
    common_run tdd xp one-shot --suite "$suite" --project "$project" ${KEEP:+--keep}
    common_checkpoint "xp-$(printf '%s' "$suite" | tr '/' '_')"
done

if [ -n "$KEEP" ]; then
    common_stage cleanup "keeping the whole setup as it is (--keep; the port-forward is stopped)"
    common_kubeportforward_stop
    common_note "re-establish: kubectl port-forward --kubeconfig $KUBECONFIG_OPT --namespace $NAMESPACE service/net-apiserver $PORT:$PORT &"
    common_note "then: export _TDD_VENV=$VENV; tdd tdk login --server $SERVER --user admin --password ***"
    common_note "the kubeconfig's current context still points at $NAMESPACE (was: ${PREV_NAMESPACE:-none})"
    common_tabsdata_setup_info common_note
else
    common_stage cleanup "destroy the domains, delete the instance, the namespace $NAMESPACE and the venv"
    common_kubeportforward_stop
    # xp (no --keep) destroyed its own domains; ours go youngest first -- the RDS
    # database and the bucket prefix disappear with them
    [ -z "$LLM_DOMAIN" ] || common_run tdd domain destroy --domain "$LLM_DOMAIN" --force
    common_run tdd domain destroy --domain "$S3_DOMAIN" --force
    common_run tdd domain destroy --domain "$RDS_DOMAIN" --force
    # delete works here: the cluster is external, so it survives the workload
    # and configmap removal (unlike kminus, where delete stops the cluster first)
    common_run tdd tdkserver delete --instance "$INSTANCE" --trash true "${TDK_OPTS[@]}"
    common_run "${KUBECTL[@]}" delete namespace "$NAMESPACE" --wait=true --timeout=300s
    if [ -n "$PREV_NAMESPACE" ]; then
        common_run "${KUBECTL[@]}" config set-context --current --namespace "$PREV_NAMESPACE"
    else
        common_run "${KUBECTL[@]}" config unset "contexts.$("${KUBECTL[@]}" config current-context).namespace"
    fi
    common_run tdd venv deactivate
    common_run tdd venv delete --name "$VENV"
fi
rm -rf "$WORK"
common_finish
