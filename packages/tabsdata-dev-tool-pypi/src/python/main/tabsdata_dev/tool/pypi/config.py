#
# Copyright 2026 Tabsdata Inc.
#

"""Load config/lanes.yaml.

The YAML answers *where* things live. It says nothing about what is allowed:
the safety invariants are POLICY below, in code, so weakening one takes a code
change and a review rather than a one-line config edit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path

import yaml
from tabsdata_dev.common.core.errors import ToolError

DEFAULT_CONFIG = Path("config/lanes.yaml")
DEFAULT_RAW = Path("raw-wheels")
DEFAULT_TREE = Path("pypi-wheels")

# Paths the git check guards. A lanes.yaml edit changes where prod points, so it
# belongs in the release record just as much as the trees do.
RELEASE_PATHS = ["pypi-wheels", "config"]


@dataclass(frozen=True)
class Policy:
    require_archived: bool  # every referenced wheel must be in the archive
    require_pushed: bool  # tree committed, HEAD reachable from release_ref
    require_yes: bool  # never proceed on an interactive confirmation alone


#: A lane in lanes.yaml with no entry here is a hard error, so a new lane cannot
#: be created with prod-like reach and staging-like safety.
POLICY: dict[str, Policy] = {
    "staging": Policy(require_archived=False, require_pushed=False, require_yes=False),
    "prod": Policy(require_archived=True, require_pushed=True, require_yes=True),
}

#: The archive bucket, addressed on the command line as a lane like the other two:
#: `push --lane raw` archives a version, `fetch --lane raw` brings it back. It has
#: no distribution and no policy of its own -- it is write-once by construction.
RAW = "raw"
LANES = (RAW, *POLICY)

#: Where a serving lane's own pages live, <base_path>/simple/, and so the
#: namespace `push --at` defaults to. Any other NAME is a developer's copy of the
#: tree beside it, at <base_path>/NAME/ with its own files/ inside, so a push
#: there touches nobody else's objects and a rebuilt wheel under an unchanged
#: filename cannot replace another namespace's bytes.
DEFAULT_AT = "simple"

#: The first path segments of the lane's own tree. Every other directory at the
#: lane's root is some namespace's, which a push or fetch of the lane leaves alone.
TREE_DIRS = ("files", DEFAULT_AT)

#: A namespace is one URL path segment; `files` is the lane's own wheel directory.
_AT_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,62}")
_AT_RESERVED = ("files",)


def check_at(name: str) -> str:
    """`name` when it can be a namespace (`--at`), else the refusal."""
    if name in _AT_RESERVED or not _AT_NAME.fullmatch(name):
        raise ToolError(
            f"--at {name!r}: a namespace is lower-case letters, digits, '-' and "
            f"'_', starting with a letter or digit, and not {', '.join(_AT_RESERVED)}"
        )
    return name


#: Concurrent S3 transfers (HEADs, puts, deletes, downloads) unless --parallel
#: says otherwise. The work is bandwidth-bound and boto3 clients are thread-safe.
DEFAULT_PARALLEL = 32


@dataclass(frozen=True)
class Lane:
    name: str
    bucket: str
    base_path: str
    distribution: str
    vanilla_domain: str
    domain: str
    policy: Policy
    at: str = DEFAULT_AT

    def with_at(self, name: str) -> Lane:
        """This lane as namespace `name` (`push --at`)."""
        return replace(self, at=check_at(name))

    @property
    def namespaced(self) -> bool:
        return self.at != DEFAULT_AT

    def key(self, rel: str) -> str:
        """Tree-relative path -> S3 key."""
        return f"{self.prefix}{rel}"

    @property
    def prefix(self) -> str:
        base = f"{self.base_path}/" if self.base_path else ""
        return f"{base}{self.at}/" if self.namespaced else base

    def owns(self, key: str) -> bool:
        """Whether an object under `prefix` is this lane's rather than a
        namespace's: everything under a namespace's own prefix, and for the lane
        itself its root files and its TREE_DIRS."""
        rel = key[len(self.prefix) :]
        return self.namespaced or "/" not in rel or rel.split("/", 1)[0] in TREE_DIRS

    @property
    def s3(self) -> str:
        return f"s3://{self.bucket}/{self.prefix}"

    @property
    def urls(self) -> list[str]:
        """Where consumers read this lane: the distribution's own name always, the
        custom domain when the lane has one ("-" or empty means it does not)."""
        out = [f"https://{self.vanilla_domain}/{self.at}/"]
        if self.domain and self.domain != "-":
            out.append(f"https://{self.domain}/{self.at}/")
        return out

    def where(self, indent: str = "  ") -> str:
        """The s3:// and https:// locations, one per line, for a header."""
        pad = " " * len(indent)
        return "\n".join([f"{indent}{self.s3}", *(f"{pad}{u}" for u in self.urls)])


@dataclass(frozen=True)
class Archive:
    bucket: str
    base_path: str

    def key(self, release: str, filename: str) -> str:
        return "/".join(p for p in (self.base_path, release, filename) if p)

    @property
    def prefix(self) -> str:
        return f"{self.base_path}/" if self.base_path else ""

    @property
    def s3(self) -> str:
        return f"s3://{self.bucket}/{self.prefix}"


@dataclass(frozen=True)
class Config:
    account: str
    region: str
    release_ref: str
    archive: Archive
    lanes: dict[str, Lane]

    def lane(self, name: str) -> Lane:
        if name not in self.lanes:
            raise ToolError(f"unknown lane {name!r}; have {sorted(self.lanes)}")
        return self.lanes[name]


def load(path: Path | None = None) -> Config:
    path = Path(path or DEFAULT_CONFIG)
    if not path.exists():
        raise ToolError(
            f"{path} not found.\n  tdd pypi expects to run from the pypi/ directory."
        )
    raw = yaml.safe_load(path.read_text())

    lanes: dict[str, Lane] = {}
    for name, spec in (raw.get("lanes") or {}).items():
        if name not in POLICY:
            raise ToolError(
                f"{path}: lane {name!r} has no policy in POLICY (config.py).\n"
                "  Add one explicitly — a lane without a policy is not safe to push to."
            )
        try:
            lanes[name] = Lane(name=name, policy=POLICY[name], **spec)
        except TypeError as exc:
            raise ToolError(f"{path}: lane {name!r}: {exc}") from exc

    missing = sorted(set(POLICY) - set(lanes))
    if missing:
        raise ToolError(f"{path}: missing lane(s): {', '.join(missing)}")

    return Config(
        account=str(raw["account"]),
        region=raw["region"],
        release_ref=raw["git"]["release_ref"],
        archive=Archive(**raw["archive"]),
        lanes=lanes,
    )
