#!/usr/bin/env bash
#
# Copyright 2026 Tabsdata Inc.
#

# Tabsdata GKE smoke test.
#
# The EKS flavour (tabsdata-eks-smoke.sh) against a Google Kubernetes Engine
# cluster: storage is a GCS bucket prefix instead of S3, and the database is
# whatever --db-system names -- gcppostgres, the Cloud SQL instance in the same
# project as the cluster, which is what a GKE run should be exercising. The five
# postgres types record one info block, so --db-system awspostgres (or
# azpostgres) reads the same keys and is a flag rather than an edit.
#
# Every name this run creates starts with sm_<NAME> (--name): the instance and
# the venv ARE sm_<NAME>; domains and xp instances/projects are sm_<NAME>__<what>;
# the k8s namespace is sm-<name>. The kminus flavour is tabsdata-km-smoke.sh.

set -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

usage() {
    cat <<'HELP'
usage: tabsdata-gke-smoke.sh --name NAME --tabsdata-version VERSION [--tabsdata-extras EXTRAS]
                   [--venv-type pyenv|uv|conda] [--python-version VERSION]
                   [--kubeconfig FILE] [--context NAME] [--provider NAME] [--db-system NAME]
                   [--uv-index URI] [--suites LIST]
                   [--llm anthropic|openai] [--expect-pods LIST] [--force] [--keep]
                   [--stop-after STAGE] [--log FILE] [--tdd-dir DIR] [--verbose]

Tabsdata GKE smoke test: a tdkserver instance on a Google Kubernetes Engine
cluster, its storage a prefix of the `gcs` system's bucket and its database a
domain of --db-system, exercised with xp suites.

Get a kubeconfig for the cluster first:
  gcloud container clusters get-credentials CLUSTER --region REGION --project PROJECT
which needs gke-gcloud-auth-plugin on PATH (gcloud components install gke-gcloud-auth-plugin).

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
  --kubeconfig FILE   the GKE kubeconfig (default: ~/.kube/config); exported as
                      KUBECONFIG for tdkserver and passed to every kubectl
  --context NAME      the context in that file to run against (default: the current
                      one if it is a GKE context, else the file's only GKE one).
                      --kubeconfig picks the file, the context picks the cluster.
                      Made current for the run -- tdkserver reads the current
                      context itself -- and the previous one is put back at cleanup
  --provider NAME     the tdkserver init provider for this cluster (default: gke).
                      It is an option because the provider name is tdkserver's to
                      define: if `init` refuses it, name the one it accepts here
  --db-system NAME    the system the instance's database domain comes from: any
                      of the five postgres types, which share one info block
                      (default: gcppostgres -- the Cloud SQL instance beside the
                      cluster; awspostgres or azpostgres to cross clouds)
  --uv-index URI      Python package index (default: none): used by the tabsdata
                      install and written into tabsdata.yaml (UV_INDEX) for the pods
  --suites LIST       comma-separated xp suite selectors, one stage each
                      (default: test,tableframe_api,dataquality,grok/s3_examples,
                      grok/s3_world_csv,cloud-connectors -- cloud-connectors covers
                      cloud-connectors/gcs; container-connectors and the fs-backed
                      grok suites stay out: docker systems and local paths are
                      unreachable from function pods running in GKE)
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
                      stage -- any name the screen prints, e.g. cluster, systems,
                      configure, forward-1, xp-<suite> (/ replaced by _), cleanup
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
CONTEXT_OPT=""           # empty: resolved from the kubeconfig below
PROVIDER="gke"           # tdkserver's name for this kind of cluster
DB_SYSTEM="gcppostgres"  # Cloud SQL, beside the cluster; --db-system crosses clouds
PORT="2457"              # tdkserver's apiserver port; the port-forward mirrors it locally
UV_INDEX_URI=""
# grok only through its s3 sub-suites: the fs-backed ones stage files on a local
# path the GKE function pods cannot see. S3 itself they reach over the internet.
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
        --context) CONTEXT_OPT="$2"; shift 2 ;;
        --provider) PROVIDER="$2"; shift 2 ;;
        --db-system) DB_SYSTEM="$2"; shift 2 ;;
        --uv-index) UV_INDEX_URI="$2"; shift 2 ;;
        --suites) SUITES="$2"; shift 2 ;;
        --force | -f) FORCE=1; shift ;;
        --keep) KEEP=1; shift ;;
        --stop-after) STOP_AFTER="$2"; shift 2 ;;
        --log) LOG="$2"; shift 2 ;;
        --tdd-dir) TDD_DIR_OPT="$2"; shift 2 ;;
        --verbose) VERBOSE=1; shift ;;
        -h | --help) usage; exit 0 ;;
        *) echo "tabsdata-gke-smoke: unknown option: $1 (see --help)" >&2; exit 1 ;;
    esac
done
case "$VENV_TYPE" in pyenv | uv | conda) ;; *) echo "tabsdata-gke-smoke: --venv-type must be pyenv, uv or conda" >&2; exit 1 ;; esac
case "$LLM" in "" | anthropic | openai) ;; *) echo "tabsdata-gke-smoke: --llm must be anthropic or openai" >&2; exit 1 ;; esac
case "$NAME" in *[!A-Za-z0-9]*) echo "tabsdata-gke-smoke: --name must be alphanumeric (it becomes part of domain and namespace names)" >&2; exit 1 ;; "") echo "tabsdata-gke-smoke: --name NAME is required (everything created is sm_NAME)" >&2; exit 1 ;; esac
if [ -z "$TABSDATA_VERSION" ]; then
    echo "tabsdata-gke-smoke: --tabsdata-version VERSION is required (the tabsdata release to install)" >&2
    exit 1
fi
if [ ! -r "$KUBECONFIG_OPT" ]; then
    echo "tabsdata-gke-smoke: no kubeconfig at $KUBECONFIG_OPT (pass --kubeconfig)" >&2
    echo "tabsdata-gke-smoke: get one with: gcloud container clusters get-credentials CLUSTER --region REGION --project PROJECT" >&2
    exit 1
fi
# --kubeconfig picks the FILE; the CONTEXT is what picks the cluster, and one
# kubeconfig holds every cluster a developer has. Unpinned, a GKE run talks to
# whatever context happened to be current -- an EKS one, say, which then fails
# deep inside a later stage complaining about AWS credentials, rather than
# about a cluster it was never meant to reach.
KUBE_CONTEXTS="$(kubectl --kubeconfig "$KUBECONFIG_OPT" config view -o jsonpath='{range .contexts[*]}{.name}{"\t"}{.context.cluster}{"\n"}{end}' 2>/dev/null)"
KUBE_NAMES="$(printf '%s\n' "$KUBE_CONTEXTS" | awk -F'\t' 'NF { print $1 }')"
# a GKE context by either name: `gcloud container clusters get-credentials`
# writes gke_<project>_<region>_<cluster> as both, and it is the context name
# that a rename would touch
KUBE_GKE="$(printf '%s\n' "$KUBE_CONTEXTS" | awk -F'\t' '$1 ~ /^gke_/ || $2 ~ /^gke_/ { print $1 }')"
CURRENT_CONTEXT="$(kubectl --kubeconfig "$KUBECONFIG_OPT" config current-context 2>/dev/null)"
CONTEXT_NOTE=""
if [ -n "$CONTEXT_OPT" ]; then
    if ! printf '%s\n' "$KUBE_NAMES" | grep -qxF -- "$CONTEXT_OPT"; then
        echo "tabsdata-gke-smoke: no context '$CONTEXT_OPT' in $KUBECONFIG_OPT; it has:" >&2
        printf '%s\n' "$KUBE_NAMES" | sed 's/^/  /' >&2
        exit 1
    fi
    CONTEXT="$CONTEXT_OPT"
elif [ -n "$CURRENT_CONTEXT" ] && printf '%s\n' "$KUBE_GKE" | grep -qxF -- "$CURRENT_CONTEXT"; then
    CONTEXT="$CURRENT_CONTEXT"
elif [ "$(printf '%s\n' "$KUBE_GKE" | grep -c .)" = 1 ]; then
    # one candidate is not a guess: there is nothing else it could have meant
    CONTEXT="$(printf '%s\n' "$KUBE_GKE" | grep .)"
    CONTEXT_NOTE="the current context (${CURRENT_CONTEXT:-none}) is not a GKE one; this is the file's only GKE context"
else
    echo "tabsdata-gke-smoke: the current context is ${CURRENT_CONTEXT:-(none)}, which is not a GKE one," >&2
    echo "tabsdata-gke-smoke: and $KUBECONFIG_OPT holds $(printf '%s\n' "$KUBE_GKE" | grep -c .) GKE contexts -- pass --context NAME:" >&2
    printf '%s\n' "$KUBE_NAMES" | sed 's/^/  /' >&2
    exit 1
fi
# the k8s namespace must be RFC 1123 (lowercase, hyphens), hence sm-<name>
BASE="sm_$NAME"
NAMES_PREFIX="$BASE"     # what the failure summary tells the reader to look for
INSTANCE="$BASE"
VENV="$BASE"
NAMESPACE="sm-$(printf '%s' "$NAME" | tr 'A-Z' 'a-z')"
STAMP="$(date +%Y%m%d-%H%M%S)"
DB_DOMAIN="${BASE}__db"
GCS_DOMAIN="${BASE}__gcs"
LLM_DOMAIN="${LLM:+${BASE}__llm_${LLM}}"
XP_PROJECTS=""           # the xp instance/project names this run creates, for --keep and failures
SMOKE_DOMAINS="$DB_DOMAIN $GCS_DOMAIN $LLM_DOMAIN"
EXPECT_POD_LIST="$(printf '%s' "$EXPECT_PODS" | tr ',' ' ')"
LOG="${LOG:-/tmp/smoke-$INSTANCE-$STAMP.log}"
WORK="$(mktemp -d "/tmp/smoke-$INSTANCE-$STAMP.XXXX")"
SERVER="http://127.0.0.1:$PORT"
TABSDATA_SPEC="tabsdata[$TABSDATA_EXTRAS]==$TABSDATA_VERSION"
TDK_OPTS=(-y --accept-terms y)
CONFIGS="$HOME/.tabsdata/instances/$INSTANCE/init/input/configs"
export KUBECONFIG="$KUBECONFIG_OPT"   # start/stop/create resolve the cluster from it; init wants it as --kubeconfig
KUBECTL=(kubectl --kubeconfig "$KUBECONFIG_OPT" --context "$CONTEXT")
SUITE_LIST=()
for suite in $(printf '%s' "$SUITES" | tr ',' ' '); do SUITE_LIST[${#SUITE_LIST[@]}]="$suite"; done
if [ "${#SUITE_LIST[@]}" -eq 0 ]; then
    echo "tabsdata-gke-smoke: --suites needs at least one selector" >&2
    exit 1
fi
STAGE_NAMES=(unset-td unset-pypi set-crypto cluster systems pycache clean-previous create-venv install)
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
        echo "tabsdata-gke-smoke: already exists:$EXISTING" >&2
        echo "tabsdata-gke-smoke: pass --force to delete and recreate them, or pick another --name" >&2
        exit 1
    fi
fi

common_init "$LOG" "$VERBOSE"
trap common_kubeportforward_stop EXIT      # the forward never outlives the script

# the generic failure block plus the GKE pieces
common_on_stage_failed() {
    common_screen ""
    common_screen "$(basename "$0"): left for you to look at"
    common_tabsdata_setup_info common_indented
    common_indented "namespace  $NAMESPACE on $CONTEXT -- kubectl delete namespace $NAMESPACE (the kubeconfig is still on that context, pointed at it)"
    common_indented "reach it   kubectl port-forward --kubeconfig $KUBECONFIG_OPT --namespace $NAMESPACE service/net-apiserver $PORT:$PORT &   then: _TDD_VENV=$VENV tdd tdk login --server $SERVER"
}

# fill_storage FILE -- the per-mount ${{secret}} of apiserver.storage.yaml: the
# uri under the gcs domain's URI, and the bucket credentials on every mount.
#
# Which credential keys a GCS mount asks for is tabsdata's to decide, and there
# are two ways to reach a bucket: natively with the service-account key, or over
# the S3 protocol with the interop HMAC pair (which is why the gcs system carries
# both). Rather than assume one, fill whichever keys the generated file actually
# has, and report the ones met. A key neither branch knows is left alone --
# common_placeholders_left then fails the stage naming it, which is a one-line
# fix here rather than a broken instance.
#
# Values travel in the environment (they are credentials); python because
# awk/sed would fight the &/\ a service-account key may hold.
fill_storage() {
    ST_FILE="$1" python3 - <<'PYEOF'
import json, os, re

path = os.environ["ST_FILE"]
uri = os.environ["GCSD__URI"].rstrip("/")
sub = {"ROOT": f"{uri}/data/", "BUNDLES": f"{uri}/bundles/", "IMAGES": f"{uri}/images/"}

# the service-account key is inline JSON or a path to it (see the gcs backend)
sa = os.environ.get("GCSD__SERVICE_ACCOUNT_KEY", "")
if sa and not sa.lstrip().startswith("{"):
    with open(os.path.expanduser(sa), encoding="utf-8") as fh:
        sa = fh.read()
sa = sa.strip()

fixed = {
    # native GCS, whichever spelling the config uses
    "google_service_account_key": sa,
    "gcp_service_account_key": sa,
    "service_account_key": sa,
    "google_service_account": sa,
    # GCS over the S3 protocol: the interop HMAC pair against Google's endpoint
    "aws_access_key_id": os.environ.get("GCSD__HMAC_ACCESS_KEY", ""),
    "aws_secret_access_key": os.environ.get("GCSD__HMAC_SECRET_KEY", ""),
    "aws_endpoint": "https://storage.googleapis.com",
    "aws_endpoint_url": "https://storage.googleapis.com",
    "aws_region": "auto",
}


def scalar(value):
    """VALUE as a YAML double-quoted scalar. JSON's string escaping is a subset
    of YAML's, so json.dumps produces exactly one, and it round-trips to the
    same string. Left bare, a value that happens to be JSON -- the service
    account key is -- reads back as a flow MAPPING, and tdkserver compares the
    filled file's shape against the template's scalar placeholder and refuses
    the whole config (ResolverError::StructureMismatch). Everything goes through
    it, so no value can change the file's shape."""
    return json.dumps(value)


out, mount, filled, unknown, empty = [], None, [], [], []
for line in open(path, encoding="utf-8"):
    m = re.match(r"\s*- id: (\w+)", line)
    if m:
        mount = m.group(1)
    if "${{secret}}" in line:
        key = line.split(":", 1)[0].strip()
        if key == "uri" and mount in sub:
            line = line.replace("${{secret}}", scalar(sub[mount]))
            filled.append(f"{mount}.uri")
        elif key in fixed:
            if fixed[key]:
                line = line.replace("${{secret}}", scalar(fixed[key]))
                filled.append(key)
            else:
                empty.append(key)
        else:
            unknown.append(key)
    out.append(line)
open(path, "w", encoding="utf-8").write("".join(out))

print("filled:", ", ".join(sorted(set(filled))) or "(nothing)")
if empty:
    print("no value for:", ", ".join(sorted(set(empty))), "-- the gcs system has none set")
if unknown:
    print("not filled (unknown to fill_storage):", ", ".join(sorted(set(unknown))))
PYEOF
}

common_screen "tabsdata-gke-smoke: effective options"
common_screen "  --name              $NAME   -> instance and venv $BASE, namespace $NAMESPACE, domains ${BASE}__<what>"
common_screen "  --venv-type         $VENV_TYPE"
common_screen "  --python-version    $PYTHON"
common_screen "  --tabsdata-version  $TABSDATA_VERSION"
common_screen "  --tabsdata-extras   $TABSDATA_EXTRAS   -> installs $TABSDATA_SPEC"
common_screen "  --kubeconfig        $KUBECONFIG_OPT   (exported as KUBECONFIG)"
common_screen "  --context           $CONTEXT   (made current for the run, restored at cleanup)"
[ -z "$CONTEXT_NOTE" ] || common_screen "                      ($CONTEXT_NOTE)"
common_screen "  --provider          $PROVIDER   -> tdkserver init --provider $PROVIDER"
common_screen "  --db-system         $DB_SYSTEM   -> domain $DB_DOMAIN"
common_screen "  storage             gcs   -> domain $GCS_DOMAIN (a prefix of the gcs system's bucket)"
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
    common_screen "${RED}tabsdata-gke-smoke: no tdd dir at $TDD_DIR_OPT (tdd-source.sh missing); install with cargo make install or pass --tdd-dir${RESET}"
    exit 1
fi
# shellcheck disable=SC1090
. "$TDD_DIR_OPT/tdd-source.sh"

common_stage unset-td "unset every TD_* variable (tdd env unset --td spares the crypto key)"
common_run tdd env unset --td
common_checkpoint unset-td

common_stage unset-pypi "unset the Python package index variables"
common_run tdd env unset --py-idx --py-default-idx
common_checkpoint unset-pypi

common_stage set-crypto "set _TDD_CRYPTO_KEY"
common_run tdd env set --crypto
common_checkpoint set-crypto

common_stage cluster "make $CONTEXT current and check it reaches the cluster (GKE needs gke-gcloud-auth-plugin)"
# In front of everything that costs time: without the auth plugin, or pointed at
# another cloud's context, kubectl fails deep inside a later stage with a message
# about credentials rather than about which cluster it was talking to. Pinning
# here is also what carries --context to tdkserver, which resolves the cluster
# and the namespace from the current context itself, not from our flags.
PREV_CONTEXT="$("${KUBECTL[@]}" config current-context 2>/dev/null)"
common_note "current context: ${PREV_CONTEXT:-(none)} (restored at cleanup)"
[ -z "$CONTEXT_NOTE" ] || common_note "$CONTEXT_NOTE"
if [ "$PREV_CONTEXT" != "$CONTEXT" ]; then
    common_run "${KUBECTL[@]}" config use-context "$CONTEXT"
fi
common_run "${KUBECTL[@]}" version --output=yaml
common_run "${KUBECTL[@]}" get namespaces
common_checkpoint cluster

common_stage systems "dev and fs, $DB_SYSTEM, gcs (and --llm) plus every system the suites need must be in the tdd store"
# checked UPFRONT: a run missing one must fail before anything is built
common_run tdd system create --type dev --sys dev --force
# fs needs an explicit absolute root: its default is target/backends/<name>
# against the CWD, which once landed inside a checkout.
common_run tdd system create --type fs --sys fs --sys-path "$TDD_DIR_OPT/data/fs-root" --force
for suite in "${SUITE_LIST[@]}"; do
    common_run tdd xp list-systems --suite "$suite"
done
common_run tdd system status --sys "$DB_SYSTEM"
common_run tdd system status --sys gcs
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

common_stage domains "domains $DB_DOMAIN, $GCS_DOMAIN${LLM:+, $LLM_DOMAIN} -- the instance's database, storage${LLM:+ and LLM key}"
# Each domain is this run's slice of the shared system. Values are eval'd into
# THIS shell, never echoed; they fill the config files below.
common_run tdd domain create --sys "$DB_SYSTEM" --domain "$DB_DOMAIN" --force
common_note "eval \$(tdd domain info --domain $DB_DOMAIN --format export --prefix DB)   (values not shown)"
eval "$(tdd domain info --domain "$DB_DOMAIN" --format export --prefix DB 2>/dev/null)"
common_run test -n "${DB__EXTERNAL_HOST:+set}${DB__PORT:+set}${DB__DATABASE:+set}${DB__USER:+set}${DB__PASSWORD:+set}"
# A postgres domain names both networks its instance answers on, and the address
# that matters here is the pods', not this laptop's: the function pods reach a
# Cloud SQL instance over its private IP, which is what INTERNAL_HOST holds.
# Falling back to the external one covers an instance that has no private
# address (or a store that never recorded it) -- the same single endpoint that
# worked before the split.
DB_POD_HOST="${DB__INTERNAL_HOST:-$DB__EXTERNAL_HOST}"
if [ -n "${DB__INTERNAL_HOST:-}" ]; then
    common_note "database: the pods get $DB_SYSTEM's INTERNAL_HOST (its private-network address)"
else
    common_remark "$DB_SYSTEM records no INTERNAL_HOST; the pods get EXTERNAL_HOST ($DB__EXTERNAL_HOST) -- fine if that address routes from inside the cluster, and the reason to record the private one if it does not"
fi
common_run tdd domain create --sys gcs --domain "$GCS_DOMAIN" --force
common_note "eval \$(tdd domain info --domain $GCS_DOMAIN --format export --prefix GCSD)   (the service-account key is not shown)"
eval "$(tdd domain info --domain "$GCS_DOMAIN" --format export --prefix GCSD 2>/dev/null)"
common_run test -n "${GCSD__URI:+set}${GCSD__BUCKET:+set}"
if [ -n "$LLM" ]; then
    common_run tdd domain create --sys "$LLM" --domain "$LLM_DOMAIN" --force
    common_note "eval \$(tdd domain info --domain $LLM_DOMAIN --format export --prefix LLM)   (the key is not shown)"
    eval "$(tdd domain info --domain "$LLM_DOMAIN" --format export --prefix LLM 2>/dev/null)"
    common_run test -n "${LLM__API_KEY:+set}"
fi
common_checkpoint domains

common_stage namespace "create the namespace $NAMESPACE and point $CONTEXT at it"
# tdkserver reads the namespace from the current context, not a flag. Set by
# name rather than --current: `config set-context --current` edits whatever the
# file says is current and ignores the --context we pass everywhere else, so
# the two are never allowed to drift apart.
PREV_NAMESPACE="$("${KUBECTL[@]}" config view --minify -o jsonpath='{.contexts[0].context.namespace}' 2>/dev/null)"
common_note "current context namespace: ${PREV_NAMESPACE:-(none)} (restored at cleanup)"
common_run "${KUBECTL[@]}" create namespace "$NAMESPACE"
common_run "${KUBECTL[@]}" config set-context "$CONTEXT" --namespace "$NAMESPACE"
common_checkpoint namespace

common_stage init "tdkserver init --provider $PROVIDER --instance $INSTANCE (the editable config folder)"
common_run tdd tdkserver init --provider "$PROVIDER" --instance "$INSTANCE" --kubeconfig "$KUBECONFIG_OPT" "${TDK_OPTS[@]}"
common_run test -d "$CONFIGS"
common_checkpoint init

common_stage configure "fill the config files from the domains: database, storage, LLM key, uv index"
# Named placeholders are shared across files; the storage file's ${{secret}}
# are positional. Values travel in the environment, never on a command line.
common_note "database: \${{literal:tdk_database_*}} and \${{secret:postgres_system_*}} from $DB_DOMAIN"
common_fill_placeholder "$CONFIGS"/*.yaml -- '${{literal:tdk_database_host}}' "$DB_POD_HOST"
common_fill_placeholder "$CONFIGS"/*.yaml -- '${{literal:tdk_database_port}}' "$DB__PORT"
common_fill_placeholder "$CONFIGS"/*.yaml -- '${{literal:tdk_database_name}}' "$DB__DATABASE"
common_fill_placeholder "$CONFIGS"/*.yaml -- '${{secret:postgres_system_user}}' "$DB__USER"
common_fill_placeholder "$CONFIGS"/*.yaml -- '${{secret:postgres_system_password}}' "$DB__PASSWORD"
# Cloud SQL signs with a CA of its own, per instance, so there is no bundle to
# bake into an image: gke's template is the only one asking for the certificate
# inline (`secret:`), where eks/aks/fargate name a path tdkserver fills itself.
# The domain carries the PEM for exactly this reason. ssl_mode stays a `system:`
# placeholder -- tdkserver puts verify-ca there for every cloud provider, which
# is what the domain asks for anyway.
common_note "database TLS: $DB__SSLMODE with the instance's own CA, from $DB_DOMAIN"
common_fill_pem "$CONFIGS/dbmanager.database.yaml" -- '${{secret:tdk_database_ssl_root_cert_pem}}' "$DB__SERVER_CA_CERT_PEM"
common_note "storage: the ROOT/BUNDLES/IMAGES mounts under ${GCSD__URI%/}/ with the gcs system's credentials"
common_run fill_storage "$CONFIGS/apiserver.storage.yaml"
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
    common_note "the kubeconfig is still on $CONTEXT (was: ${PREV_CONTEXT:-none}), namespace $NAMESPACE (was: ${PREV_NAMESPACE:-none})"
    common_tabsdata_setup_info common_note
else
    common_stage cleanup "destroy the domains, delete the instance, the namespace $NAMESPACE and the venv"
    common_kubeportforward_stop
    # xp (no --keep) destroyed its own domains; ours go youngest first -- the
    # database and the bucket prefix disappear with them
    [ -z "$LLM_DOMAIN" ] || common_run tdd domain destroy --domain "$LLM_DOMAIN" --force
    common_run tdd domain destroy --domain "$GCS_DOMAIN" --force
    common_run tdd domain destroy --domain "$DB_DOMAIN" --force
    # delete works here: the cluster is external, so it survives the workload
    # and configmap removal (unlike kminus, where delete stops the cluster first)
    common_run tdd tdkserver delete --instance "$INSTANCE" --trash true "${TDK_OPTS[@]}"
    common_run "${KUBECTL[@]}" delete namespace "$NAMESPACE" --wait=true --timeout=300s
    if [ -n "$PREV_NAMESPACE" ]; then
        common_run "${KUBECTL[@]}" config set-context "$CONTEXT" --namespace "$PREV_NAMESPACE"
    else
        common_run "${KUBECTL[@]}" config unset "contexts.$CONTEXT.namespace"
    fi
    # and the shell that ran this gets its cluster back
    if [ -n "$PREV_CONTEXT" ] && [ "$PREV_CONTEXT" != "$CONTEXT" ]; then
        common_run "${KUBECTL[@]}" config use-context "$PREV_CONTEXT"
    fi
    common_run tdd venv deactivate
    common_run tdd venv delete --name "$VENV"
fi
rm -rf "$WORK"
common_finish
