#!/usr/bin/env bash
#
# Copyright 2026 Tabsdata Inc.
#

# Tabsdata AKS smoke test.
#
# The EKS flavour (smoke-eks.sh) against an Azure Kubernetes Service
# cluster: storage is an Azure Blob container prefix instead of S3, and the
# database is whatever --db-domain names -- azpostgres, the flexible server in
# the same subscription as the cluster, which is what an AKS run should be
# exercising. The five postgres types record one info block, so --db-domain
# awspostgres (or gcppostgres) reads the same keys and is a flag rather than an
# edit.
#
# Every name this run creates starts with sm_<NAME> (--name): the instance and
# the venv ARE sm_<NAME>; domains and xp instances/projects are sm_<NAME>__<what>;
# the k8s namespace is --kube-namespace. The kminus flavour is smoke-km.sh.

set -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# sourced before the arguments are read, so --help is painted like a tdd command
# shellcheck disable=SC1091
. "$HERE/_common.sh"

# Nothing here is guessed. A cluster run reaches a named cluster in a named
# namespace and installs from a named index, and the wrong default for any of
# them is a confusing failure -- or a quiet success somewhere nobody meant to
# touch. These are the options common_help paints red.
REQUIRED_OPTIONS="--name --kube-config --kube-context --td-version"

usage() {
    cat <<'HELP' | common_help "$REQUIRED_OPTIONS"
usage: smoke-aks.sh --name NAME --kube-config FILE --kube-context NAME --td-version VERSION
                   [--kube-namespace NAME] [--kube-port-forward PORT] [--uv-index URI]
                   [--db-domain SYSTEM] [--storage-domain SYSTEM] [--llm-domain SYSTEM]
                   [--provider NAME] [--td-extras EXTRAS] [--td-fn-memory SIZE]
                   [--td-fn-disk SIZE] [--venv-type uv|pyenv|conda] [--py-version VERSION]
                   [--xp-suites LIST] [--expect-pods LIST] [--force] [--keep]
                   [--profile NAME] [--log FILE] [--tdd-dir DIR] [--verbose]

Tabsdata AKS smoke test: a tdkserver instance on an Azure Kubernetes Service
cluster, its storage a prefix of the `azureblob` system's container and its
database a domain of --db-domain, exercised with xp suites.

Get a kubeconfig for the cluster first:
  az aks get-credentials --subscription 9dd049b8-201a-41da-88e5-d6123d9f157a \
      --resource-group tabsdata-dev --name tabsdata-aks-dev
That writes a context named after the cluster -- tabsdata-aks-dev -- which is
what --context defaults to. The subscription is spelled out because the cluster
lives in Developer while `az account show` reports CI.

options:
  --name NAME         REQUIRED: the run's name, alphanumeric. Everything created
                      is sm_NAME -- the tdkserver instance and the managed venv --
                      or sm_NAME__<what> (domains, xp instances/projects)
  --kube-config FILE  REQUIRED: the kubeconfig holding the cluster. It is never
                      modified: the run copies it and works on the copy
  --kube-context NAME
                      REQUIRED: the context in that file to run against. `az aks
                      get-credentials` names it after the cluster; the file
                      chooses nothing on its own, the context picks the cluster
  --kube-namespace NAME
                      the namespace to create and run in, RFC 1123 (lowercase,
                      digits, hyphens). Default: sm-<name>, lowercased
  --kube-port-forward PORT
                      the local port `kubectl port-forward` listens on for the
                      apiserver -- where tdk logs in. Only this side moves: the
                      apiserver's own port in the cluster stays 2457
                      (default: 12000; one per script -- km 10000, eks 11000,
                      aks 12000, gke 13000 -- so two runs on one machine
                      never fight over it)
  --td-version VERSION
                      REQUIRED: the tabsdata release to install, tabsdata[EXTRAS]==VERSION
  --td-extras EXTRAS
                      the extras to install (default: all)
  --td-fn-memory SIZE
                      memory of each function pod, written into tabsdata.yaml as
                      pods.function.resources.memory (default: 8Gi; the template
                      asks for 16Gi)
  --td-fn-disk SIZE   disk of each function pod, the same way (default: 32Gi;
                      the template asks for 64Gi)
  --venv-type TYPE    uv, pyenv or conda (default: uv)
  --py-version VERSION
                      interpreter for the venv (default: 3.12.13 -- the exact
                      version the instance builds its own environments with)
  --provider NAME     the tdkserver init provider for this cluster (default: aks).
                      It is an option because the provider name is tdkserver's to
                      define: if `init` refuses it, name the one it accepts here
  --db-domain SYSTEM  the system the instance's database is created on (default:
                      azpostgres). Every domain this run creates is named
                      sm_NAME__<system>, and --force recreates it. Any of the
                      five postgres types: they share one info block
                      (default: azpostgres -- the flexible server beside the
                      cluster; awspostgres or gcppostgres to cross clouds)
  --uv-index URI      the Python package index, used by the tabsdata install and
                      written into tabsdata.yaml (UV_INDEX) for the pods
                      URI is a URL, or @dev for the development index
                      (https://d3mm0r95u5i3hf.cloudfront.net/simple/), @dev:NAME
                      for namespace NAME on it (.../NAME/, what tdd pypi push
                      --at NAME publishes) or @prod for the published
                      one (https://pypi.tabsdata.com/simple/); not @local,
                      since the pods would read localhost as themselves
                      (default: none -- whatever uv is already configured with)
  --xp-suites LIST    comma-separated xp suite selectors, one stage each;
                      ALL for every suite dir
                      (default: test,tableframe_api,dataquality,grok/s3_examples,
                      grok/s3_world_csv,cloud-connectors/az -- az is the object-store
                      suite of this cloud; container-connectors and the fs-backed
                      grok suites stay out: docker systems and local paths are
                      unreachable from function pods running in AKS)
  --storage-domain SYSTEM
                      the system the instance's storage comes from (default:
                      azureblob). The config filling knows this cloud's option
                      keys; another cloud's storage leaves placeholders the run
                      then refuses
  --llm-domain SYSTEM
                      create a domain on that system too, read its API key and
                      write it into aiagent.yaml (default: no LLM)
  --expect-pods LIST  service names whose pods must be Running and Ready after
                      every start, per `tdkserver status` (default: srv-apiserver)
  --force, -f         a venv, instance or namespace of this name already existing
                      is an error unless this is given: then they are removed and
                      recreated (default: fail)
  --keep              on success, leave everything as it is: instance running,
                      namespace, domains, venv, xp setups (xp one-shot --keep);
                      the port-forward is still stopped -- the closing report
                      prints the command to re-establish it
                      (default: no -- domains destroyed, instance deleted,
                      namespace deleted, venv deleted; a failed run always
                      leaves everything standing)
  --profile NAME      the tdk connection profile every `tdk` call and every xp
                      suite uses (tdk COMMAND --profile NAME), so this run's
                      login never replaces another shell's on the same account
                      (default: sm_NAME)
  --log FILE          log file (default: <temp>/smoke-sm_NAME-<start time>.log;
                      <temp> is $TMPDIR, else /tmp)
  --tdd-dir DIR       the tdd dir to source (default: $TDD_DIR, else ~/.tdd)
  --verbose           show every command's output as it happens (default: a
                      rolling window of the running command's last lines)
  --help, -h          this help

The drivers added to the instance's fn and ag venvs (tdkserver venv update):
  pymysql==1.2.3  psycopg2-binary==2.9.12  oracledb==3.2.0

Worker logs: the run gives the apiserver the managed identity td-<namespace>-apiserver
in the cluster's resource group, its federated credential and a Log Analytics Data
Reader assignment on the Container Insights workspace limited to the namespace's
rows (each reused if it exists, written only if missing), runs test/test, reads
its workers' logs while their pods are there, and checks the copies Log Analytics
returns once the pods are gone match them line for line. It needs az
signed in to an account that can make what is missing (Managed Identity
Contributor on the group; roleAssignments/write on the workspace for the
assignment), the cluster's Workload Identity and Container Insights. If that
setup fails, the run says why and skips the check. az never installs an
extension during the run.
HELP
}

NAME=""                  # required; everything is sm_$NAME
STORAGE_SYSTEM="azureblob"   # --storage-domain: the system the instance's storage comes from
LLM_SYSTEM=""            # --llm-domain: none unless asked for
EXPECT_PODS="srv-apiserver"
VENV_TYPE="uv"
PYTHON="3.12.13"
TD_VERSION=""            # required
TD_EXTRAS="all"
FN_MEMORY="8Gi"          # --td-fn-memory: each function pod's memory; the template says 16Gi
FN_DISK="32Gi"           # --td-fn-disk: each function pod's disk; the template says 64Gi
KUBECONFIG_OPT=""        # required
CONTEXT=""               # required
NAMESPACE=""             # required
PROVIDER="aks"           # tdkserver's name for this kind of cluster
DB_SYSTEM="azpostgres"   # the flexible server beside the cluster; --db-domain crosses clouds
PORT="2457"              # the apiserver's port in the cluster: tdkserver create --port, the forward's far side
FORWARD_PORT="12000"     # --kube-port-forward: the local port the forward listens on; where tdk logs in.
                         # One per script (km 10000, eks 11000, aks 12000, gke 13000): the local end is the
                         # one thing two runs on a laptop can collide on, and they do run side by side.
UV_INDEX_URI=""
# grok only through its s3 sub-suites: the fs-backed ones stage files on a local
# path the AKS function pods cannot see, and there is no az-backed grok suite.
# S3 itself the pods reach over the internet, same as any other cloud's run.
#
# cloud-connectors by SUB-SUITE, unlike the gke flavour: the family also holds
# bigquery, databricks and snowflake, whose systems are not in the store, and
# `xp list-systems --suite cloud-connectors` exits 1 for the three -- the
# systems stage would fail before anything is built. az is the
# object-store suite of this cloud, which is what an AKS run is here to prove.
SUITES="test,tableframe_api,dataquality,grok/s3_examples,grok/s3_world_csv,cloud-connectors/az"
FORCE=""                 # 1 with --force; empty otherwise
KEEP=""                  # 1 with --keep; empty otherwise (so ${KEEP:+--keep} works)
LOG=""
PROFILE=""               # --profile: defaults to $BASE once --name is known
VERBOSE=0
TDD_DIR_OPT="${TDD_DIR:-$HOME/.tdd}"
REQUIREMENTS="pymysql==1.2.3
psycopg2-binary==2.9.12
oracledb==3.2.0"

while [ $# -gt 0 ]; do
    case "$1" in
        --name) NAME="$2"; shift 2 ;;
        --storage-domain) STORAGE_SYSTEM="$2"; shift 2 ;;
        --llm-domain) LLM_SYSTEM="$2"; shift 2 ;;
        --expect-pods) EXPECT_PODS="$2"; shift 2 ;;
        --venv-type) VENV_TYPE="$2"; shift 2 ;;
        --py-version) PYTHON="$2"; shift 2 ;;
        --td-version) TD_VERSION="$2"; shift 2 ;;
        --td-extras) TD_EXTRAS="$2"; shift 2 ;;
        --td-fn-memory) FN_MEMORY="$2"; shift 2 ;;
        --td-fn-disk) FN_DISK="$2"; shift 2 ;;
        --kube-config) KUBECONFIG_OPT="$2"; shift 2 ;;
        --kube-context) CONTEXT="$2"; shift 2 ;;
        --kube-namespace) NAMESPACE="$2"; shift 2 ;;
        --kube-port-forward) FORWARD_PORT="$2"; shift 2 ;;
        --provider) PROVIDER="$2"; shift 2 ;;
        --db-domain) DB_SYSTEM="$2"; shift 2 ;;
        --uv-index) UV_INDEX_URI="$2"; shift 2 ;;
        --xp-suites) SUITES="$2"; shift 2 ;;
        --force | -f) FORCE=1; shift ;;
        --keep) KEEP=1; shift ;;
        --log) LOG="$2"; shift 2 ;;
        --profile) PROFILE="$2"; shift 2 ;;
        --tdd-dir) TDD_DIR_OPT="$2"; shift 2 ;;
        --verbose) VERBOSE=1; shift ;;
        -h | --help) usage; exit 0 ;;
        *) echo "smoke-aks: unknown option: $1 (see --help)" >&2; exit 1 ;;
    esac
done
# tdd is loaded as soon as the line is read: resolving --uv-index, the checks,
# the banner and every stage go through it (tdd _smoke).
if [ ! -r "$TDD_DIR_OPT/tdd-source.sh" ]; then
    echo "smoke-aks: no tdd dir at $TDD_DIR_OPT (tdd-source.sh missing); install with cargo make install or pass --tdd-dir" >&2
    exit 1
fi
# shellcheck disable=SC1090
. "$TDD_DIR_OPT/tdd-source.sh"
UV_INDEX_URI="$(common_resolve_uv_index "$UV_INDEX_URI" --no-local)" || exit 1

case "$VENV_TYPE" in uv | pyenv | conda) ;; *) echo "smoke-aks: --venv-type must be uv, pyenv or conda" >&2; exit 1 ;; esac
missing=""
for _need in $REQUIRED_OPTIONS; do
    case "$_need" in
        --name) [ -n "$NAME" ] || missing="$missing $_need" ;;
        --kube-config) [ -n "$KUBECONFIG_OPT" ] || missing="$missing $_need" ;;
        --kube-context) [ -n "$CONTEXT" ] || missing="$missing $_need" ;;
        --td-version) [ -n "$TD_VERSION" ] || missing="$missing $_need" ;;
    esac
done
if [ -n "$missing" ]; then
    echo "smoke-aks: missing required option(s):$missing (see --help)" >&2
    exit 1
fi
case "$NAME" in *[!A-Za-z0-9]*) echo "smoke-aks: --name must be alphanumeric (it becomes part of domain and xp names)" >&2; exit 1 ;; esac
case "$NAMESPACE" in *[!a-z0-9-]* | -* | *-) echo "smoke-aks: --kube-namespace must be RFC 1123: lowercase letters, digits and inner hyphens" >&2; exit 1 ;; esac
case "$FORWARD_PORT" in '' | *[!0-9]*) echo "smoke-aks: --kube-port-forward must be a port number, 1-65535" >&2; exit 1 ;; esac
if [ "$FORWARD_PORT" -lt 1 ] || [ "$FORWARD_PORT" -gt 65535 ]; then echo "smoke-aks: --kube-port-forward must be a port number, 1-65535" >&2; exit 1; fi
QUANTITY='^[0-9]+(\.[0-9]+)?([EPTGMK]i?|m)?$'   # a Kubernetes quantity: 8Gi, 512Mi, 1.5G
[[ "$FN_MEMORY" =~ $QUANTITY ]] || { echo "smoke-aks: --td-fn-memory must be a Kubernetes quantity such as 8Gi or 512Mi" >&2; exit 1; }
[[ "$FN_DISK" =~ $QUANTITY ]] || { echo "smoke-aks: --td-fn-disk must be a Kubernetes quantity such as 32Gi" >&2; exit 1; }
# The one command this script never runs and always names: the kubeconfig is
# the user's to fetch, and a failure that is really a missing one says how.
AZ_CREDENTIALS="az aks get-credentials --subscription <ID> --resource-group <GROUP> --name <CLUSTER>"
if [ ! -r "$KUBECONFIG_OPT" ]; then
    echo "smoke-aks: no kubeconfig at $KUBECONFIG_OPT (pass --kube-config)" >&2
    echo "smoke-aks: get one with: $AZ_CREDENTIALS" >&2
    exit 1
fi
# --kube-config picks the FILE; the context is what picks the cluster, and one
# kubeconfig holds every cluster a developer has. Both are given, so there is
# nothing to infer here -- only to check, before anything is built.
KUBE_NAMES="$(kubectl --kubeconfig "$KUBECONFIG_OPT" config view -o jsonpath='{range .contexts[*]}{.name}{"\n"}{end}' 2>/dev/null)"
if ! printf '%s\n' "$KUBE_NAMES" | grep -qxF -- "$CONTEXT"; then
    echo "smoke-aks: no context '$CONTEXT' in $KUBECONFIG_OPT; it has:" >&2
    printf '%s\n' "$KUBE_NAMES" | sed 's/^/  /' >&2
    echo "smoke-aks: get a kubeconfig with: $AZ_CREDENTIALS" >&2
    exit 1
fi
# not required: the run's own name makes a good namespace, and RFC 1123 only
# needs it lowercased
NAMESPACE="${NAMESPACE:-sm-$(printf '%s' "$NAME" | tr 'A-Z' 'a-z')}"
BASE="sm_$NAME"
PROFILE="${PROFILE:-$BASE}"   # the tdk connection is this run's own, like every name it makes
NAMES_PREFIX="$BASE"     # what the failure summary tells the reader to look for
INSTANCE="$BASE"
VENV="$BASE"
STAMP="$(date +%Y%m%d-%H%M%S)"
DB_DOMAIN="${BASE}__${DB_SYSTEM}"
STORAGE_DOMAIN="${BASE}__${STORAGE_SYSTEM}"
LLM_DOMAIN="${LLM_SYSTEM:+${BASE}__${LLM_SYSTEM}}"
XP_PROJECTS=""           # the xp instance/project names this run creates, for --keep and failures
SMOKE_DOMAINS=""         # domains this run creates, appended as each one is (common_tabsdata_setup_info lists them)
LOGS_PROJECT="${BASE}__logs"   # the worker-logs stage's own xp run, kept until its logs are read
LOGS_SETUP=""            # 1 once that run is set up: the cleanup removes its domains
WORKER_LOGS=""           # 1 once worker-logs-setup has the identity and its assignment: init annotates with them
WORKER_LOGS_WHY=""       # why worker-logs-setup stopped, for the remark that says so
EXPECT_POD_LIST="$(printf '%s' "$EXPECT_PODS" | tr ',' ' ')"
LOG="${LOG:-$COMMON_TMP/smoke-$INSTANCE-$STAMP.log}"
LOGS_DIR="${LOG%.log}-worker-logs"   # the live and archived copies the worker-logs check compares
WORK="$(mktemp -d "$COMMON_TMP/smoke-$INSTANCE-$STAMP.XXXX")"
SERVER="http://127.0.0.1:$FORWARD_PORT"
TABSDATA_SPEC="tabsdata[$TD_EXTRAS]==$TD_VERSION"
TDK_OPTS=(-y --accept-terms y)
CONFIGS="$HOME/.tabsdata/instances/$INSTANCE/init/input/configs"
# tdkserver resolves the cluster and the namespace from the kubeconfig's CURRENT
# context, and `venv update`, `config` and `delete` take no --context to say
# otherwise. Rather than move the developer's current context out from under
# whatever else they have running, the run works on a COPY of the file with its
# own current context and namespace, and points tdkserver at that. What they
# passed in is only ever read.
RUN_KUBECONFIG="$WORK/kubeconfig"
cp "$KUBECONFIG_OPT" "$RUN_KUBECONFIG"
kubectl --kubeconfig "$RUN_KUBECONFIG" config use-context "$CONTEXT" >/dev/null
export KUBECONFIG="$RUN_KUBECONFIG"
KUBECTL=(kubectl --kubeconfig "$RUN_KUBECONFIG" --context "$CONTEXT")
# The apiserver reads a removed pod's log from Log Analytics as a managed
# identity of its own, limited to its namespace's rows, as the dguide's AKS
# worker logs page makes it by hand. What this run adds it removes; what it
# finds is reused and left. Every az call names the cluster's subscription --
# `az account set` is never run -- and az may not install an extension on its
# own: one once arrived unasked from a command that wanted it.
export AZURE_EXTENSION_USE_DYNAMIC_INSTALL=no
AKS_ID="td-$NAMESPACE-apiserver"
AKS_FC="aut-apiserver"   # the federated credential, named after the service account
AKS_SUBSCRIPTION=""
AKS_GROUP=""
AKS_WORKSPACE=""         # the workspace GUID the apiserver queries (customerId)
AKS_WORKSPACE_ID=""      # its resource id, the assignment's scope
AKS_CLIENT_ID=""
AKS_PRINCIPAL_ID=""
AKS_ID_CREATED=""        # set for each thing this run made: only those does the cleanup undo
AKS_FC_ADDED=""
AKS_RA_ADDED=""          # the assignment's id
SUITE_LIST=()
for suite in $(printf '%s' "$SUITES" | tr ',' ' '); do SUITE_LIST[${#SUITE_LIST[@]}]="$suite"; done
if [ "${#SUITE_LIST[@]}" -eq 0 ]; then
    echo "smoke-aks: --xp-suites needs at least one selector" >&2
    exit 1
fi
STAGE_NAMES=(unset-td unset-pypi set-crypto cluster systems pycache clean-previous create-venv install)
[ "$TD_VERSION" = "2.0.2" ] && STAGE_NAMES[${#STAGE_NAMES[@]}]="cdc-driver"
for stage in domains namespace worker-logs-setup init configure create start-1 pods-1 forward-1 login-1; do STAGE_NAMES[${#STAGE_NAMES[@]}]="$stage"; done
for stage in stop-1 venv-update start-2 pods-2 forward-2 login-2; do STAGE_NAMES[${#STAGE_NAMES[@]}]="$stage"; done
for suite in "${SUITE_LIST[@]}"; do STAGE_NAMES[${#STAGE_NAMES[@]}]="xp-$(printf '%s' "$suite" | tr '/' '_')"; done
STAGE_NAMES[${#STAGE_NAMES[@]}]="worker-logs"
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
        echo "smoke-aks: already exists:$EXISTING" >&2
        echo "smoke-aks: pass --force to delete and recreate them, or pick another --name" >&2
        exit 1
    fi
fi

common_init "$LOG" "$VERBOSE"
trap common_kubeportforward_stop EXIT      # the forward never outlives the script

# the generic failure block plus the AKS pieces
common_on_stage_failed() {
    common_screen ""
    common_screen "$(basename "$0"): left for you to look at"
    common_tabsdata_setup_info common_indented
    # only when the namespace is really there: a run that died before creating it
    # -- or against a cluster that stopped answering -- would otherwise be handed
    # a delete and a port-forward for something that does not exist
    if common_k8s_namespace_exists "$RUN_KUBECONFIG" "$CONTEXT" "$NAMESPACE"; then
        common_indented "namespace  $NAMESPACE on $CONTEXT -- kubectl --context $CONTEXT delete namespace $NAMESPACE"
        common_indented "reach it   kubectl --context $CONTEXT --namespace $NAMESPACE port-forward service/net-apiserver $FORWARD_PORT:$PORT &   then: _TDD_VENV=$VENV tdd tdk login --profile $PROFILE --server $SERVER"
        # the cluster's own account of the failure, collected while the namespace is
        # still there: `Init job 'ins-dbmanager' failed` names the job, and the
        # reason is in the pod it left behind
        common_indented "cluster    the failed pods' logs and the namespace's events are in the log"
    fi
    aks_left common_indented
    common_k8s_report "$RUN_KUBECONFIG" "$CONTEXT" "$NAMESPACE"
}

# What worker-logs-setup made, each with the command that undoes it -- for a
# failed or --keep run, which leaves them. The assignment goes first: one whose
# identity is gone lingers as an unknown principal.
aks_left() {
    local emit="$1" scope="--subscription $AKS_SUBSCRIPTION --resource-group $AKS_GROUP"
    [ -z "$AKS_RA_ADDED" ] ||
        "$emit" "azure role Log Analytics Data Reader for $AKS_ID -- az role assignment delete --ids $AKS_RA_ADDED"
    if [ -n "$AKS_ID_CREATED" ]; then
        "$emit" "identity   $AKS_ID -- az identity delete $scope --name $AKS_ID"
    elif [ -n "$AKS_FC_ADDED" ]; then
        "$emit" "credential $AKS_FC on $AKS_ID -- az identity federated-credential delete $scope --identity-name $AKS_ID --name $AKS_FC --yes"
    fi
}

# The steps of worker-logs-setup, each a stage command: a failure records why
# for the remark, since the stage's own lines are gone once it closes.
aks_why() {
    WORKER_LOGS_WHY="$1"
    echo "$1"
    return 1
}

# aks_retry CMD... -- a managed identity just made is not yet a principal Azure
# RBAC can assign to.
aks_retry() {
    local attempt=1
    until "$@"; do
        [ "$attempt" -lt 6 ] || return 1
        echo "attempt $attempt/6 failed; retrying in 10s" >&2   # stdout is the caller's value
        attempt=$((attempt + 1))
        sleep 10
    done
}

aks_provider() {
    [ "$PROVIDER" = aks ] ||
        aks_why "--provider $PROVIDER: only the aks provider's tabsdata.yaml has worker_logs" || return 1
}

aks_az_identity() {
    local account
    command -v az >/dev/null 2>&1 || aks_why "no az on the PATH" || return 1
    account="$(az account show --query user.name --output tsv)" ||
        aks_why "az account show failed: az login" || return 1
    echo "az account: $account"
}

# The kubeconfig names no subscription or resource group, and the cluster need
# not be in az's default subscription: it is the cluster, in any subscription
# the account sees, whose API server the context talks to.
aks_cluster() {
    local subscriptions sub found=""
    "${KUBECTL[@]}" config view --minify --output json >"$WORK/kubeview.json" ||
        aks_why "kubectl config view failed for context $CONTEXT" || return 1
    subscriptions="$(az account list --query '[].id' --output tsv)" ||
        aks_why "az account list failed" || return 1
    for sub in $subscriptions; do
        az aks list --subscription "$sub" --output json >"$WORK/aks-$sub.json" 2>/dev/null || continue
        found="$(tdd _smoke aks-cluster --clusters "$WORK/aks-$sub.json" <"$WORK/kubeview.json")" ||
            aks_why "the AKS clusters of subscription $sub could not be read" || return 1
        [ -z "$found" ] || break
    done
    [ -n "$found" ] ||
        aks_why "no AKS cluster in a subscription az sees has the API server of context $CONTEXT" || return 1
    read -r AKS_SUBSCRIPTION AKS_GROUP AKS_CLUSTER AKS_ISSUER AKS_WI AKS_WORKSPACE_ID <<<"$found"
    echo "cluster $AKS_CLUSTER in group $AKS_GROUP, subscription $AKS_SUBSCRIPTION"
}

aks_workload_identity() {
    [ "$AKS_WI" = true ] && [ "$AKS_ISSUER" != - ] ||
        aks_why "cluster $AKS_CLUSTER has no Workload Identity; once per cluster: az aks update --subscription $AKS_SUBSCRIPTION --resource-group $AKS_GROUP --name $AKS_CLUSTER --enable-oidc-issuer --enable-workload-identity" ||
        return 1
    echo "OIDC issuer: $AKS_ISSUER"
}

aks_workspace() {
    local found resource_only
    [ "$AKS_WORKSPACE_ID" != - ] ||
        aks_why "cluster $AKS_CLUSTER runs no Container Insights: the dguide's AKS worker logs page, step 4.2" || return 1
    found="$(az monitor log-analytics workspace show --ids "$AKS_WORKSPACE_ID" \
        --query '[customerId, features.enableLogAccessUsingOnlyResourcePermissions]' --output tsv)" ||
        aks_why "az monitor log-analytics workspace show $AKS_WORKSPACE_ID failed" || return 1
    read -r AKS_WORKSPACE resource_only <<<"$(printf '%s' "$found" | tr '\n' ' ')"
    [ "$resource_only" = true ] ||
        aks_why "workspace $AKS_WORKSPACE_ID requires workspace permissions: the namespace condition would not apply" ||
        return 1
    echo "workspace $AKS_WORKSPACE ($AKS_WORKSPACE_ID)"
}

aks_managed_identity() {
    local found scope=(--subscription "$AKS_SUBSCRIPTION" --resource-group "$AKS_GROUP" --name "$AKS_ID")
    if found="$(az identity show "${scope[@]}" --query '[clientId, principalId]' --output tsv 2>/dev/null)"; then
        echo "identity $AKS_ID exists: reused"
    else
        found="$(az identity create "${scope[@]}" --query '[clientId, principalId]' --output tsv)" ||
            aks_why "az identity create $AKS_ID failed: the account may lack Managed Identity Contributor on $AKS_GROUP" ||
            return 1
        AKS_ID_CREATED=1
    fi
    read -r AKS_CLIENT_ID AKS_PRINCIPAL_ID <<<"$(printf '%s' "$found" | tr '\n' ' ')"
    echo "identity $AKS_ID: client $AKS_CLIENT_ID, principal $AKS_PRINCIPAL_ID"
}

# Read first and written only when missing or pointing elsewhere, so a setup an
# admin made once is reused by an account that can only read it.
aks_federated_credential() {
    local found subject="system:serviceaccount:$NAMESPACE:aut-apiserver"
    local scope=(--subscription "$AKS_SUBSCRIPTION" --resource-group "$AKS_GROUP" --identity-name "$AKS_ID" --name "$AKS_FC")
    local spec=(--issuer "$AKS_ISSUER" --subject "$subject" --audiences api://AzureADTokenExchange)
    if found="$(az identity federated-credential show "${scope[@]}" --query '[issuer, subject]' --output tsv 2>/dev/null)"; then
        if [ "$(printf '%s' "$found" | tr '\n' ' ')" = "$AKS_ISSUER $subject" ]; then
            echo "credential $AKS_FC on $AKS_ID already trusts $subject"
            return 0
        fi
        echo "credential $AKS_FC on $AKS_ID trusts another issuer or subject: set to $subject"
        az identity federated-credential update "${scope[@]}" "${spec[@]}" >/dev/null ||
            aks_why "az identity federated-credential update $AKS_FC failed" || return 1
        return 0
    fi
    az identity federated-credential create "${scope[@]}" "${spec[@]}" >/dev/null ||
        aks_why "az identity federated-credential create $AKS_FC failed" || return 1
    AKS_FC_ADDED=1
}

aks_role_assignment() {
    local condition answer state
    condition="$(tdd _smoke aks-condition --namespace "$NAMESPACE")" || return 1
    answer="$(az role assignment list --scope "$AKS_WORKSPACE_ID" --output json |
        tdd _smoke aks-has-assignment --principal "$AKS_PRINCIPAL_ID" --namespace "$NAMESPACE")" ||
        aks_why "az role assignment list on $AKS_WORKSPACE_ID failed" || return 1
    state="${answer%% *}"
    if [ "$state" = present ]; then
        echo "$AKS_ID already reads the workspace under this namespace's condition"
        return 0
    fi
    [ "$state" = absent ] ||
        aks_why "$AKS_ID has a Log Analytics Data Reader assignment on the workspace with another condition; not adding a second (Azure grants the sum)" ||
        return 1
    AKS_RA_ADDED="$(aks_retry az role assignment create --assignee-object-id "$AKS_PRINCIPAL_ID" \
        --assignee-principal-type ServicePrincipal --role 3b03c2da-16b3-4a49-8834-0f8130efdd3b \
        --scope "$AKS_WORKSPACE_ID" --condition "$condition" --condition-version 2.0 --query id --output tsv)" ||
        aks_why "az role assignment create failed: the account may lack Microsoft.Authorization/roleAssignments/write on the workspace (the dguide's AKS page, step 5.2)" ||
        return 1
    echo "assignment $AKS_RA_ADDED (it can take up to 15 minutes to apply)"
}

# The apiserver names the workspace it queries once it has both the identity
# and the workspace; without either it has no Log Analytics reader at all.
aks_apiserver_reads_workspace() {
    local out
    out="$("${KUBECTL[@]}" --namespace "$NAMESPACE" logs deployment/srv-apiserver --container 1000-apiserver)" || return 1
    if printf '%s\n' "$out" | grep -F "Log Analytics workspace '$AKS_WORKSPACE'"; then
        return 0
    fi
    echo "the apiserver names no Log Analytics workspace '$AKS_WORKSPACE'; what it says of one:"
    printf '%s\n' "$out" | grep -F "Log Analytics" || echo "  nothing: it does not run as $AKS_ID"
    return 1
}

common_screen "smoke-aks: effective options"
common_screen "  --name              $NAME   -> instance and venv $BASE, namespace $NAMESPACE, domains ${BASE}__<what>"
common_screen "  --venv-type         $VENV_TYPE"
common_screen "  --py-version    $PYTHON"
common_screen "  --td-version        $TD_VERSION"
common_screen "  --td-extras   $TD_EXTRAS   -> installs $TABSDATA_SPEC"
common_screen "  --td-fn-memory      $FN_MEMORY   -> tabsdata.yaml pods.function.resources.memory"
common_screen "  --td-fn-disk        $FN_DISK   -> tabsdata.yaml pods.function.resources.disk"
common_screen "  --kube-config       $KUBECONFIG_OPT   (read only; the run works on a copy)"
common_screen "  --kube-context      $CONTEXT"
common_screen "  --kube-namespace    $NAMESPACE"
common_screen "  --kube-port-forward $FORWARD_PORT   -> server $SERVER; the apiserver itself listens on $PORT"
common_screen "  --provider          $PROVIDER   -> tdkserver init --provider $PROVIDER"
common_screen "  --db-domain         $DB_SYSTEM   -> domain $DB_DOMAIN"
common_screen "  storage             azureblob   -> domain $STORAGE_DOMAIN (a prefix of the azureblob system's container)"
common_screen "  --uv-index          $(common_display "${UV_INDEX_URI:-(none)}")"
common_screen "  --xp-suites            $SUITES   -> xp projects ${BASE}__xp_<ts>_<suite>"
common_screen "  --storage-domain    $STORAGE_SYSTEM   -> domain $STORAGE_DOMAIN"
common_screen "  --llm-domain        ${LLM_SYSTEM:-(none)}${LLM_SYSTEM:+   -> domain $LLM_DOMAIN}"
common_screen "  --expect-pods       $EXPECT_PODS"
common_screen "  --force             $([ -n "$FORCE" ] && echo "yes (replace an existing venv/instance/namespace)" || echo "no (an existing one is an error)")"
common_screen "  --keep              $([ -n "$KEEP" ] && echo "yes (also: xp one-shot --keep)" || echo "no (domains, instance, namespace and venv deleted at the end)")"
common_screen "  --profile           $PROFILE   -> tdk COMMAND --profile $PROFILE, xp --profile $PROFILE"
common_screen "  --log               $LOG"
common_screen "  --tdd-dir           $TDD_DIR_OPT"
common_screen "  --verbose           $([ "$VERBOSE" = 1 ] && echo yes || echo "no (rolling window of $WINDOW log lines)")"
common_screen "  server              $SERVER through kubectl port-forward service/net-apiserver $FORWARD_PORT:$PORT"
common_screen "  drivers for fn/ag   $(printf '%s' "$REQUIREMENTS" | tr '\n' ' ')"
common_screen "  worker logs         managed identity $AKS_ID, then test/test as $LOGS_PROJECT, read live, then back from Log Analytics once its pods are gone, and compared"
common_xp_expand_all

common_stage unset-td "unset every TD_* variable (tdd env unset --td spares the crypto key)"
common_run tdd env unset --td

common_stage unset-pypi "unset the Python package index variables"
common_run tdd env unset --py-idx --py-default-idx

common_stage set-crypto "set _TDD_CRYPTO_KEY"
common_run tdd env set --crypto

common_stage cluster "make $CONTEXT current and check it reaches the cluster"
# In front of everything that costs time: pointed at another cloud's context, or
# with credentials az never wrote, kubectl fails deep inside a later stage with a
# message about credentials rather than about which cluster it was talking to.
# Pinning here is also what carries --context to tdkserver, which resolves the
# cluster and the namespace from the current context itself, not from our flags.
common_note "the run's own kubeconfig is $RUN_KUBECONFIG, on context $CONTEXT"
# An AKS context name says nothing about the cloud it reaches, so show the
# endpoint it resolves to: an AKS one is *.azmk8s.io (or the sovereign clouds'
# azk8s.cn / containerservice.azure.us). Shown, never matched on -- the reader
# can see they are on the right cluster without the script pretending to know.
common_note "cluster endpoint: $("${KUBECTL[@]}" config view --minify -o jsonpath='{.clusters[0].cluster.server}' 2>/dev/null)"
common_run "${KUBECTL[@]}" version --output=yaml
common_run "${KUBECTL[@]}" get namespaces

common_stage systems "dev and fs, $DB_SYSTEM, azureblob (and --llm) plus every system the suites need must be in the tdd store"
# checked UPFRONT: a run missing one must fail before anything is built
common_run tdd system create --type dev --sys dev --force
# fs needs an explicit absolute root: its default is target/backends/<name>
# against the CWD, which once landed inside a checkout.
common_run tdd system create --type fs --sys fs --sys-path "$TDD_DIR_OPT/data/fs-root" --force
for suite in "${SUITE_LIST[@]}"; do
    common_run tdd xp list-systems --suite "$suite"
done
common_run tdd system status --sys "$DB_SYSTEM"
common_run tdd system status --sys azureblob
[ -z "$LLM_SYSTEM" ] || common_run tdd system status --sys "$LLM_SYSTEM"

common_stage pycache "purge tabsdata from the uv and pip caches"
common_run tdd pycache clean

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

common_stage create-venv "leave any active venv, then create and activate the managed venv $VENV ($VENV_TYPE, python $PYTHON)"
# Whatever this shell was in has to go first: `tdd venv create` refuses under a
# venv tdd did not activate, and the one a developer is most likely to be
# standing in -- their project's own -- is exactly that. --force is what leaves
# one tdd did not enter, and says "no venv was active" rather than failing when
# the shell is already clean.
common_run tdd venv deactivate --force
# shellcheck disable=SC2086
common_run tdd venv create --name "$VENV" --type "$VENV_TYPE" --python "$PYTHON" ${FORCE:+--force}

common_stage install "uv pip install $TABSDATA_SPEC into $VENV"
# shellcheck disable=SC2086
common_run uv pip install ${UV_INDEX_URI:+--index "$UV_INDEX_URI" --index-strategy unsafe-best-match} "$TABSDATA_SPEC"
for program in tdkserver tdk; do
    common_run test -x "$(dirname "$(command -v python)")/$program"
done

# tabsdata 2.0.2 ships no psycopg2 with its Postgres connector (it sits in the
# `test` extra), yet the CDC plugin imports it when tdk loads the connectors, so
# every postgrescdc collection create fails. Until tabsdata ships it, put it in
# the client venv for that version -- and say so, since it is not tabsdata's own.
if [ "$TD_VERSION" = "2.0.2" ]; then
    common_stage cdc-driver "tabsdata 2.0.2 workaround: psycopg2-binary into $VENV for the Postgres CDC plugin"
    # shellcheck disable=SC2086
    common_run uv pip install ${UV_INDEX_URI:+--index "$UV_INDEX_URI" --index-strategy unsafe-best-match} psycopg2-binary==2.9.11
    common_remark "workaround: tabsdata 2.0.2 ships no psycopg2 with its Postgres connector; psycopg2-binary was installed into $VENV so the CDC plugin loads"
fi

common_stage domains "domains $DB_DOMAIN, $STORAGE_DOMAIN${LLM_SYSTEM:+, $LLM_DOMAIN} -- the instance's database, storage${LLM_SYSTEM:+ and LLM key}"
# Each domain is this run's slice of the shared system. Values are eval'd into
# THIS shell, never echoed; they fill the config files below.
common_run tdd domain create --sys "$DB_SYSTEM" --domain "$DB_DOMAIN" --force
SMOKE_DOMAINS="$SMOKE_DOMAINS $DB_DOMAIN"
common_note "eval \$(tdd domain info --domain $DB_DOMAIN --format export --prefix DB)   (values not shown)"
eval "$(tdd domain info --domain "$DB_DOMAIN" --format export --prefix DB 2>/dev/null)"
common_run test -n "${DB__EXTERNAL_HOST:+set}${DB__PORT:+set}${DB__DATABASE:+set}${DB__USER:+set}${DB__PASSWORD:+set}"
# A postgres domain names both networks its instance answers on, and the address
# that matters here is the pods', not this laptop's: the function pods reach a
# flexible server over its private endpoint / VNet address, which is what
# INTERNAL_HOST holds. Falling back to the external one covers a server with
# public access on (or a store that never recorded the private name) -- the same
# single endpoint that worked before the split.
DB_POD_HOST="${DB__INTERNAL_HOST:-$DB__EXTERNAL_HOST}"
if [ -n "${DB__INTERNAL_HOST:-}" ]; then
    common_note "database: the pods get $DB_SYSTEM's INTERNAL_HOST (its private-network address)"
else
    common_remark "$DB_SYSTEM records no INTERNAL_HOST; the pods get EXTERNAL_HOST ($DB__EXTERNAL_HOST) -- fine if that address routes from inside the cluster, and the reason to record the private one if it does not"
fi
common_run tdd domain create --sys "$STORAGE_SYSTEM" --domain "$STORAGE_DOMAIN" --force
SMOKE_DOMAINS="$SMOKE_DOMAINS $STORAGE_DOMAIN"
common_note "eval \$(tdd domain info --domain $STORAGE_DOMAIN --format export --prefix STORD)   (the account key is not shown)"
eval "$(tdd domain info --domain "$STORAGE_DOMAIN" --format export --prefix STORD 2>/dev/null)"
common_run test -n "${STORD__URI:+set}${STORD__CONTAINER:+set}${STORD__ACCOUNT_NAME:+set}"
if [ -n "$LLM_SYSTEM" ]; then
    common_run tdd domain create --sys "$LLM_SYSTEM" --domain "$LLM_DOMAIN" --force
    SMOKE_DOMAINS="$SMOKE_DOMAINS $LLM_DOMAIN"
    common_note "eval \$(tdd domain info --domain $LLM_DOMAIN --format export --prefix LLM)   (the key is not shown)"
    eval "$(tdd domain info --domain "$LLM_DOMAIN" --format export --prefix LLM 2>/dev/null)"
    common_run test -n "${LLM__API_KEY:+set}"
fi

common_stage namespace "create the namespace $NAMESPACE and point the run's kubeconfig at it"
# tdkserver takes the namespace from the current context of the kubeconfig it is
# given, and this one is the run's own copy -- so nothing the developer's file
# says is touched, and nothing has to be put back afterwards.
common_run "${KUBECTL[@]}" create namespace "$NAMESPACE"
common_run "${KUBECTL[@]}" config set-context "$CONTEXT" --namespace "$NAMESPACE"

common_stage --continue worker-logs-setup "the apiserver's managed identity $AKS_ID and its Log Analytics access (continue on error)"
common_run_shown "--provider $PROVIDER has worker_logs" aks_provider &&
    common_run_shown "az account show" aks_az_identity &&
    common_run_shown "az account list; az aks list: the cluster of context $CONTEXT" aks_cluster &&
    common_run_shown "the cluster's Workload Identity and OIDC issuer" aks_workload_identity &&
    common_run_shown "az monitor log-analytics workspace show: the Container Insights workspace" aks_workspace &&
    common_run_shown "az identity show (or create) $AKS_ID" aks_managed_identity &&
    common_run_shown "az identity federated-credential show (create if missing): $AKS_FC" aks_federated_credential &&
    common_run_shown "az role assignment list (create if missing): Log Analytics Data Reader for $NAMESPACE's rows" aks_role_assignment &&
    WORKER_LOGS=1
[ -n "$WORKER_LOGS" ] || common_remark "worker logs not checked: ${WORKER_LOGS_WHY:-the setup failed} (see the log)"

common_stage init "tdkserver init --provider $PROVIDER --instance $INSTANCE (the editable config folder${WORKER_LOGS:+, with the apiserver identity})"
INIT_CONFIG=()
if [ -n "$WORKER_LOGS" ]; then
    INIT_CONFIG=(--config "tabsdata:pods.service.apiserver.service_account.annotations.\"azure.workload.identity/client-id\"=$AKS_CLIENT_ID"
        --config "tabsdata:pods.service.apiserver.worker_logs.workspace=$AKS_WORKSPACE")
fi
common_run tdd tdkserver init --provider "$PROVIDER" --instance "$INSTANCE" --kubeconfig "$RUN_KUBECONFIG" "${TDK_OPTS[@]}" "${INIT_CONFIG[@]}"
common_run test -d "$CONFIGS"

common_stage configure "fill the config files from the domains: database, storage, LLM key, uv index, function pod sizing"
# Named placeholders are shared across files; the storage file's ${{secret}}
# are positional. Values travel in the environment, never on a command line.
common_note "database: \${{literal:tdk_database_*}} and \${{secret:postgres_system_*}} from $DB_DOMAIN"
common_fill_placeholder "$CONFIGS"/*.yaml -- '${{literal:tdk_database_host}}' "$DB_POD_HOST"
common_fill_placeholder "$CONFIGS"/*.yaml -- '${{literal:tdk_database_port}}' "$DB__PORT"
common_fill_placeholder "$CONFIGS"/*.yaml -- '${{literal:tdk_database_name}}' "$DB__DATABASE"
common_fill_placeholder "$CONFIGS"/*.yaml -- '${{secret:postgres_system_user}}' "$DB__USER"
common_fill_placeholder "$CONFIGS"/*.yaml -- '${{secret:postgres_system_password}}' "$DB__PASSWORD"
# Nothing to fill for TLS, and nothing to fill it with: Azure signs a flexible
# server with a public root, so the bundle is baked into the image and aks's
# dbmanager template names a PATH to it. Both ssl_mode and ssl_root_cert are
# `system:` placeholders tdkserver resolves itself (verify-ca,
# /tabsdata/certs/ca-azure.pem), which `tdd _smoke placeholders-left` leaves alone.
# The gke flavour is the exception, not this one: Cloud SQL's per-instance CA
# has no bundle, so it asks for the certificate inline and the domain carries
# the PEM. azpostgres keeps only the URL Azure publishes the root at.
common_note "database TLS: tdkserver's own verify-ca against /tabsdata/certs/ca-azure.pem ($DB_SYSTEM asks for $DB__SSLMODE)"
common_note "storage: the ROOT/BUNDLES/IMAGES mounts under ${STORD__URI%/}/ with the azureblob system's account credentials"
common_run tdd _smoke fill-storage --file "$CONFIGS/apiserver.storage.yaml" --cloud azure
if [ -n "$LLM_SYSTEM" ]; then
    common_note "aiagent: the $LLM_SYSTEM key from $LLM_DOMAIN"
    common_fill_placeholder "$CONFIGS/aiagent.yaml" -- "\${{secret:$LLM_SYSTEM-key?}}" "$LLM__API_KEY"
fi
if [ -n "$UV_INDEX_URI" ]; then
    common_note "tabsdata.yaml: UV_INDEX -> $(common_display "$UV_INDEX_URI")"
    common_run tdd _smoke set-uv-index --file "$CONFIGS/tabsdata.yaml" --uri "$UV_INDEX_URI"
fi
common_note "tabsdata.yaml: function pods memory $FN_MEMORY, disk $FN_DISK (pods.function.resources)"
common_run tdd _smoke set-fn-resources --file "$CONFIGS/tabsdata.yaml" --memory "$FN_MEMORY" --disk "$FN_DISK"
common_run tdd _smoke placeholders-left --dir "$CONFIGS"
common_run tdd tdkserver config check --instance "$INSTANCE" --init --accept-terms y

common_stage create "tdkserver create (upload the config), then delete the plaintext input folder"
common_run tdd tdkserver create --instance "$INSTANCE" --port "$PORT" "${TDK_OPTS[@]}"
# the input folder holds the secrets in plain text; create uploaded them --
# `config get --with-secrets` fetches them back
common_run rm -rf "$HOME/.tabsdata/instances/$INSTANCE/init"

common_stage start-1 "tdkserver start (the first start builds environments and runs the db setup)"
common_run tdd tdkserver start --instance "$INSTANCE" "${TDK_OPTS[@]}"
common_run common_tdkserver_expect "$INSTANCE" running

common_stage pods-1 "every expected service pod is Running: $EXPECT_PODS"
# shellcheck disable=SC2086
common_run_retry 30 10 common_tdkserver_pods_running "$INSTANCE" $EXPECT_POD_LIST

common_stage forward-1 "kubectl port-forward service/net-apiserver $FORWARD_PORT:$PORT (background)"
common_kubeportforward_start "$RUN_KUBECONFIG" "$NAMESPACE" net-apiserver "$FORWARD_PORT" "$PORT"

common_stage login-1 "tdk login as admin on $SERVER (profile $PROFILE)"
common_run_retry 30 5 tdd tdk login --profile "$PROFILE" --server "$SERVER" --user admin --password tabsdata

common_stage stop-1 "tdkserver stop (the port-forward dies with the pods)"
# rule: end the port-forward before tabsdata stops, restarts, or takes a tdkserver
# config or env change -- it holds the pods' connections and dies with them
common_kubeportforward_stop
common_run tdd tdkserver stop --instance "$INSTANCE" "${TDK_OPTS[@]}"
common_run common_tdkserver_expect "$INSTANCE" stopped

common_stage venv-update "update the instance's fn and ag venvs with the DB drivers"
printf '%s\n' "$REQUIREMENTS" > "$WORK/requirements.txt"
common_note "requirements: $(printf '%s' "$REQUIREMENTS" | tr '\n' ' ')"
# Both venvs in one call: every call rebuilds all three venvs and sends all
# three images to the IMAGES mount, so two calls would do that twice.
common_run tdd tdkserver venv update --instance "$INSTANCE" --name fn,ag --requirements "$WORK/requirements.txt" "${TDK_OPTS[@]}"

common_stage start-2 "tdkserver start"
common_run tdd tdkserver start --instance "$INSTANCE" "${TDK_OPTS[@]}"
common_run common_tdkserver_expect "$INSTANCE" running

common_stage pods-2 "every expected service pod is Running: $EXPECT_PODS"
# shellcheck disable=SC2086
common_run_retry 30 10 common_tdkserver_pods_running "$INSTANCE" $EXPECT_POD_LIST

common_stage forward-2 "kubectl port-forward service/net-apiserver $FORWARD_PORT:$PORT (re-established after start)"
common_kubeportforward_start "$RUN_KUBECONFIG" "$NAMESPACE" net-apiserver "$FORWARD_PORT" "$PORT"

common_stage login-2 "tdk login as admin on $SERVER (profile $PROFILE)"
common_run_retry 30 5 tdd tdk login --profile "$PROFILE" --server "$SERVER" --user admin --password tabsdata

for suite in "${SUITE_LIST[@]}"; do
    project="${BASE}__xp_$(date -u +%Y%m%dT%H%M%S)_$(printf '%s' "$suite" | tr -c 'A-Za-z0-9\n' '_')"
    XP_PROJECTS="$XP_PROJECTS $project"
    common_stage --continue "xp-$(printf '%s' "$suite" | tr '/' '_')" "xp one-shot $suite as $project (continue on error)"
    # the forward is one stream through the cluster's tunnel and can drop between
    # suites; a suite started over a dead one fails lane by lane as "not logged in"
    common_kubeportforward_ensure || continue
    # shellcheck disable=SC2086
    common_run tdd xp one-shot --suite "$suite" --suite-run "$project" --project "$project" --profile "$PROFILE" ${KEEP:+--keep}
done

common_stage --continue worker-logs "run test/test as $LOGS_PROJECT, read its workers' live logs, then their copies from Log Analytics once their pods are gone, line for line (continue on error)"
if [ -z "$WORKER_LOGS" ]; then
    common_stage_skip "worker-logs-setup did not complete"
else
    XP_PROJECTS="$XP_PROJECTS $LOGS_PROJECT"
    # the Jobs live 180s after they finish, and rows reach the workspace 1-3
    # minutes after they are written
    common_kubeportforward_ensure &&
        common_run_retry 6 10 aks_apiserver_reads_workspace &&
        common_run tdd xp one-shot --suite test/test --suite-run "$LOGS_PROJECT" --project "$LOGS_PROJECT" --profile "$PROFILE" --keep &&
        LOGS_SETUP=1 &&
        common_run_retry 5 3 common_worker_logs_live "$RUN_KUBECONFIG" "$CONTEXT" "$NAMESPACE" "$PROFILE" "$LOGS_PROJECT" "$LOGS_DIR" &&
        common_run_retry 36 10 common_worker_pods_gone "$RUN_KUBECONFIG" "$CONTEXT" "$NAMESPACE" "$PROFILE" "$LOGS_PROJECT" &&
        common_run_retry 48 10 common_worker_logs_archived "$PROFILE" "$LOGS_PROJECT" log-analytics "$LOGS_DIR"
fi

if [ -n "$KEEP" ]; then
    common_stage cleanup "keeping the whole setup as it is (--keep; the port-forward is stopped)"
    common_kubeportforward_stop
    common_note "re-establish: kubectl --context $CONTEXT --namespace $NAMESPACE port-forward service/net-apiserver $FORWARD_PORT:$PORT &"
    common_note "then: export _TDD_VENV=$VENV; tdd tdk login --profile $PROFILE --server $SERVER --user admin --password ***"
    common_note "your kubeconfig was not touched; the run's copy is $RUN_KUBECONFIG ($CONTEXT, namespace $NAMESPACE)"
    common_tabsdata_setup_info common_note
    aks_left common_note
else
    common_stage cleanup "destroy the domains, delete the instance, the namespace $NAMESPACE and the venv"
    common_kubeportforward_stop
    # xp (no --keep) destroyed its own domains; ours go youngest first -- the
    # database and the container prefix disappear with them
    [ -z "$LLM_DOMAIN" ] || common_run tdd domain destroy --domain "$LLM_DOMAIN" --force
    common_run tdd domain destroy --domain "$STORAGE_DOMAIN" --force
    common_run tdd domain destroy --domain "$DB_DOMAIN" --force
    # delete works here: the cluster is external, so it survives the workload
    # and configmap removal (unlike kminus, where delete stops the cluster first)
    # the worker-logs run was kept to read its logs: its domains and suite run are ours too
    if [ -n "$LOGS_SETUP" ]; then
        common_run tdd xp destroy-domains --suite-run "$LOGS_PROJECT"
        common_run tdd xp destroy-instance --suite-run "$LOGS_PROJECT"
    fi
    common_run tdd tdkserver delete --instance "$INSTANCE" --trash true "${TDK_OPTS[@]}"
    common_run "${KUBECTL[@]}" delete namespace "$NAMESPACE" --wait=true --timeout=300s
    # only what worker-logs-setup made, the assignment first; what it found
    # stays. The rows expire with the table: Log Analytics deletes no single one.
    if [ -n "$AKS_RA_ADDED" ]; then
        common_run az role assignment delete --ids "$AKS_RA_ADDED"
    fi
    if [ -n "$AKS_ID_CREATED" ]; then
        common_run az identity delete --subscription "$AKS_SUBSCRIPTION" --resource-group "$AKS_GROUP" --name "$AKS_ID"
    elif [ -n "$AKS_FC_ADDED" ]; then
        common_run az identity federated-credential delete --subscription "$AKS_SUBSCRIPTION" --resource-group "$AKS_GROUP" \
            --identity-name "$AKS_ID" --name "$AKS_FC" --yes
    fi
    common_run tdd venv deactivate
    common_run tdd venv delete --name "$VENV"
fi
rm -rf "$WORK"
common_finish
