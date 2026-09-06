#
# Copyright 2026 Tabsdata Inc.
#

"""Single source of truth for CLI vocabulary and environment variables.

Command names, option flags, roles and sentinels are constants (never string
literals at call sites) so the dispatcher's argv peeking and each command's
declared options can never drift apart. ``ENV_VARS`` drives the ``environment:``
section printed by top-level help.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from tabsdata_dev.common.core import batch as core_batch

# --- tools -----------------------------------------------------------------
# The two commands, and the hidden sibling of `domain` that lives in the
# salesforce toolset (see TOOLSET_* and DOMAIN_TOOL_BY_TOOLSET).
SYS_TOOL = "system"
DOM_TOOL = "domain"
DOM_SF_TOOL = "domain-sf"

# --- toolsets --------------------------------------------------------------
# Every system verb and most domain verbs run in the `systems` toolset (the
# driver set). The salesforce data plane runs in `salesforce`: cumulusci-plus
# pins sqlalchemy<2, which the driver set's dialects contradict. A backend
# declares the toolset each plane needs; `domain` re-dispatches to the sibling
# tool registered for it when it is not the one running.
TOOLSET_SYSTEMS = "systems"
TOOLSET_SALESFORCE = "salesforce"
DOMAIN_TOOL_BY_TOOLSET = {TOOLSET_SYSTEMS: DOM_TOOL, TOOLSET_SALESFORCE: DOM_SF_TOOL}

# --- descriptor roles ------------------------------------------------------
ROLE_SYSTEM: Literal["system"] = "system"
ROLE_DOMAIN: Literal["domain"] = "domain"

# --- verbs -----------------------------------------------------------------
V_TYPES = "types"
V_LIST = "list"
V_INFO = "info"
V_CREATE = "create"
V_DESTROY = "destroy"
V_STATUS = "status"
V_PURGE = "purge"
V_FETCH_BIN = "fetch-bin"
V_RESTART = "restart"
V_MODELS = "models"
V_CREATE_MODEL = "create-model"
V_CREATE_DATA = "create-data"
V_MODIFY_DATA = "modify-data"
V_MANIFEST = "manifest"
V_UPGRADE = "upgrade"
V_SECRETS = "secrets"
V_CRYPTO_KEY = "crypto-key"
# Every command has it, from the shared layer (common.core.config).
V_CONFIG = "config"
V_CONNECT = "connect"
V_CLEAN_DOCKER = "clean-docker"
V_TEMPLATE = "template"

# --- option flags ----------------------------------------------------------
OPT_TYPE = "--type"
OPT_SYS = "--sys"
OPT_DOMAIN = "--domain"
OPT_SYS_DIR = "--sys-dir"
OPT_DOMAIN_DIR = "--domain-dir"
OPT_FORCE = "--force"
OPT_YES = "--yes"
OPT_LATCH = "--latch"
OPT_MODEL = "--model"
OPT_SIZE = "--size"
OPT_ENTITY = "--entity"
OPT_SETS = "--sets"
OPT_OPS = "--ops"
OPT_SEED = "--seed"
OPT_PREFIX = "--prefix"
OPT_NAME_IN_SYSTEM = "--name-in-system"
OPT_PORT = "--port"
OPT_PORTS = "--ports"
OPT_FORMAT = "--format"  # the guidelines' json|view, plus a renderer's own shapes
OPT_VERBOSE = "--verbose"
OPT_OUT = "--out"  # manifest: destination file
OPT_SET = "--set"
OPT_VAULT = "--vault"
OPT_ITEM = "--item"
OPT_FIELD = "--field"
OPT_MANIFEST = "--manifest"
OPT_SYNC = "--sync"
OPT_EXTERNAL_PREFIX = "--external-prefix"
OPT_REPORT = "--report"
OPT_FAIL_FAST = "--fail-fast"
OPT_SYS_PREFIX = "--sys-prefix"
OPT_SYS_HOSTNAME = "--sys-hostname"
OPT_DOMAIN_PREFIX = "--domain-prefix"
OPT_DRY_RUN = "--dry-run"
OPT_ENV_PREFIX = "--env-prefix"
OPT_REMOTE_SYS = "--remote-sys"
OPT_REMOTE_SECRET_ENV = "--remote-secret-env"
OPT_SSH_PORT = "--ssh-port"
OPT_IDENTITY = "--identity"
HELP_FLAGS = ("-h", "--help")

# --- batch execution -------------------------------------------------------
TARGET_ALL = "ALL"  # --sys/--domain ALL selects every type (create) / stored one
# Candidate free ports the dispatcher pre-allocates per system when starting many
# in parallel, so no two racing creates pick the same free port (a system uses as
# many as it needs -- most one, a couple for multi-port stacks -- and ignores the
# rest).
# Host ports: the i-th system type of the registry owns PORT_BASE + i*PORTS_PER_SYSTEM and
# the 99 after it; 20000-29999 as a whole is the systems' (core.ports.PORT_RANGE
# starts above it), below every OS's ephemeral range.
PORT_BASE = 20000
PORTS_PER_SYSTEM = 100
PORTS_CEILING = 30000

# --- sentinels / value sets ------------------------------------------------
SEED_AUTO = "AUTO"
ENTITY_ALL = "ALL"
# --- rendering ---------------------------------------------------------------
# `--format` is one flag: the guidelines' json|view envelope, and -- for the
# commands that render something -- the shape of what they render. `main` only
# ever consumes json|view itself, so a renderer's own value reaches its parser
# and leaves the envelope on view.
FMT_VIEW = "view"
FMT_JSON = "json"
FMT_1P = "1p"  # a 1Password item, ready for `op item create --template=`
BASE_FORMATS = (FMT_JSON, FMT_VIEW)
# info / secrets / crypto-key: shell lines to eval, or the 1Password item.
RENDER_FORMATS = ("export", "unset", FMT_1P)
# template renders a type rather than a descriptor: no shell form to eval.
TEMPLATE_FORMATS = (FMT_1P,)

# Every container the docker-backed systems create -- `docker run` ones
# (`_common/sql.py`) and compose projects (`_common/containers.py`) -- is named
# `tdx2_...`; `clean-docker` sweeps by this prefix, descriptors or not.
DOCKER_CONTAINER_PREFIX = "tdx2"

# --- environment variables -------------------------------------------------
# tdd's own variables carry a leading underscore when they are private to the
# tool chain; the crypto key is one -- users set it with `tdd env set --crypto`.
ENV_CRYPTO_KEY = "_TDD_CRYPTO_KEY"
# Where `crypto-key` reads the personal key from, unless told otherwise: the
# 1Password Employee vault every user has, item DevSecrets, and the field that
# item has always had -- the 1Password schema did not follow the variable's rename.
# Literals: which vault a key comes from is a choice made on the command line,
# never one an exported variable can change underfoot.
DEFAULT_EMPLOYEE_VAULT = "Employee"
DEFAULT_CRYPTO_ITEM = "DevSecrets"
DEFAULT_CRYPTO_FIELD = "TD_BACKENDS_CRYPTO_KEY"
ENV_BUILD_USER = "TD_BUILD_USER"
ENV_BUILD_NUMBER = "TD_BUILD_NUMBER"
ENV_MYSQL_IMAGE_VERSION = "MYSQL_IMAGE_VERSION"
DEFAULT_MYSQL_IMAGE_VERSION = "8.4"

# The mutating verbs keep a detailed log per run (docker pulls, readiness waits,
# DDL) beside the guidelines' failure logs, named tdd-<tool>-<verb>-<name>-<stamp>.log.
LOG_DIR = "/tmp"
LOG_MAX_AGE_DAYS = 1  # each run deletes its tool's logs in LOG_DIR older than this


@dataclass(frozen=True)
class EnvVar:
    name: str
    default: str  # human-readable default
    help: str


ENV_VARS: tuple[EnvVar, ...] = (
    EnvVar(
        ENV_CRYPTO_KEY, "(required, >=12 chars)", "secret that encrypts descriptors"
    ),
    EnvVar(
        ENV_BUILD_USER,
        "<OS login>",
        "build-identity user in the d_<user>_<build>_ prefix",
    ),
    EnvVar(
        ENV_BUILD_NUMBER, "0", "build-identity number in the d_<user>_<build>_ prefix"
    ),
    EnvVar(
        ENV_MYSQL_IMAGE_VERSION, DEFAULT_MYSQL_IMAGE_VERSION, "MySQL docker image tag"
    ),
    EnvVar(
        core_batch.ENV_PARALLELISM,
        str(core_batch.DEFAULT_PARALLELISM),
        "max concurrent targets in a batch (--sys/--domain list/ALL) run",
    ),
)
