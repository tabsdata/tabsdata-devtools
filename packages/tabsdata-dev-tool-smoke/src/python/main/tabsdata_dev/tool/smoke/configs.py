#
# Copyright 2026 Tabsdata Inc.
#

"""The edits a smoke run makes to the configs tdkserver generates, once for
both shell families.

Every edit is literal on both sides: a placeholder holds `${{`, `?` and `:`,
and a value can be a password, a PEM or JSON, so neither is ever read as a
pattern or a backreference. Values that are credentials reach these functions
from the environment, never from a command line. Files are read and written
with their line endings as they are.
"""

from __future__ import annotations

import json
import os
import pathlib
import re

from tabsdata_dev.common.core import errors

#: The placeholders tabsdata leaves for the user: `${{literal:..}}`, and
#: `${{secret:..}}` / `${{secret}}` without the `?` that makes one optional.
#: `system:` and `secretAuto:` are tabsdata's own to fill.
REQUIRED_PLACEHOLDER = re.compile(r"\$\{\{(literal|secret)(:[^}?]*)?\}\}")

#: The bare placeholder apiserver.storage.yaml carries per mount key.
STORAGE_PLACEHOLDER = "${{secret}}"

#: The mounts of apiserver.storage.yaml, each a folder under the storage URI.
STORAGE_MOUNTS = {"ROOT": "data", "BUNDLES": "bundles", "IMAGES": "images"}

GCS_ENDPOINT = "https://storage.googleapis.com"

CLOUDS = ("aws", "azure", "gcp")


def _read(path: pathlib.Path) -> str:
    with path.open(encoding="utf-8", newline="") as fh:
        return fh.read()


def _write(path: pathlib.Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def _ending(line: str) -> str:
    return line[len(line.rstrip("\r\n")) :]


def set_uv_index(path: pathlib.Path, uri: str) -> None:
    """Point a tabsdata.yaml's UV_INDEX at URI, the line keeping its indent."""
    text = re.sub(
        r"(?m)^(\s*UV_INDEX:)[^\r\n]*",
        lambda m: f"{m.group(1)} {uri}",
        _read(path),
    )
    _write(path, text)


def set_fn_resources(path: pathlib.Path, memory: str, disk: str) -> None:
    """Size the FUNCTION pods in a tabsdata.yaml: the memory: and disk: under
    pods.function.resources, and only those.

    The file carries a resources block per service as well, so the block is
    found by structure -- the `function:` key, its `resources:` one level in,
    the two lines one level further -- and each value is rewritten on its own
    line with the indentation kept, so tdkserver's shape check against the
    template (StructureMismatch) sees the template's shape. Exactly one memory
    and one disk line must be rewritten: a config that only looks sized is the
    failure to catch here, not at the first function pod that will not
    schedule."""
    want = {"memory": memory, "disk": disk}
    lines = _read(path).splitlines(keepends=True)

    def indent(line: str) -> int:
        return len(line) - len(line.lstrip(" "))

    def inside(i: int, depth: int) -> bool:
        # still within the block opened at `depth`: deeper, or blank
        return i < len(lines) and (not lines[i].strip() or indent(lines[i]) > depth)

    done: dict[str, int] = {}
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
                    name = key.group(2)
                    lines[i] = f"{key.group(1)}{name}: {want[name]}{_ending(lines[i])}"
                    done[name] = done.get(name, 0) + 1
                i += 1
    if done != {"memory": 1, "disk": 1}:
        raise errors.ToolError(
            f"{path}: expected one memory and one disk line under "
            f"function.resources, rewrote {done or 'none'}"
        )
    _write(path, "".join(lines))


def fill_placeholder(paths: list[pathlib.Path], placeholder: str, value: str) -> int:
    """Replace every occurrence of PLACEHOLDER in the files with VALUE; the
    number of files that held it."""
    hits = 0
    for path in paths:
        text = _read(path)
        if placeholder in text:
            _write(path, text.replace(placeholder, value))
            hits += 1
    return hits


def fill_pem(paths: list[pathlib.Path], placeholder: str, value: str) -> int:
    """Replace a whole `key: PLACEHOLDER` line with a YAML block scalar holding
    VALUE; the number of PEM lines written.

    What a multi-line certificate needs: substituted inline, a PEM's newlines
    would continue the plain scalar and YAML would fold them into spaces --
    the file still parses, and then no certificate ever loads. The block is
    indented two past the key's own indent, so it works wherever the key sits.
    An empty value or a placeholder that is not there is refused: both leave a
    config that only looks filled."""
    value = value.strip()
    if not value:
        raise errors.ToolError(
            f"nothing to fill {placeholder} with: the value is empty"
        )
    hits = 0
    for path in paths:
        lines = _read(path).splitlines(keepends=True)
        out = []
        for line in lines:
            if placeholder not in line:
                out.append(line)
                continue
            hits += 1
            end = _ending(line) or "\n"
            key = line.split(":", 1)[0]
            pad = " " * (len(key) - len(key.lstrip()) + 2)
            out.append(f"{key}: |{end}")
            out.extend(f"{pad}{one}{end}" for one in value.splitlines())
        if out != lines:
            _write(path, "".join(out))
    if not hits:
        names = " ".join(str(p) for p in paths)
        raise errors.ToolError(f"{placeholder} is not in any of: {names}")
    return len(value.splitlines())


def placeholders_left(folder: pathlib.Path) -> list[str]:
    """`FILE:LINE:TEXT` for every required placeholder left in FOLDER/*.yaml.
    An unfilled placeholder line holds no value, so it is shown as it is."""
    left = []
    for path in sorted(folder.glob("*.yaml")):
        for n, line in enumerate(_read(path).splitlines(), start=1):
            if REQUIRED_PLACEHOLDER.search(line):
                left.append(f"{path}:{n}:{line}")
    return left


def _scalar(value: str) -> str:
    """VALUE as a YAML double-quoted scalar. JSON's string escaping is a subset
    of YAML's, so json.dumps produces exactly one, and it round-trips to the
    same string. Left bare, a value that happens to be JSON -- a GCP service
    account key is -- reads back as a flow MAPPING, and tdkserver compares the
    filled file's shape against the template's scalar placeholder and refuses
    the whole config (ResolverError::StructureMismatch)."""
    return json.dumps(value)


def _gcs_service_account(env: dict[str, str]) -> str:
    # inline JSON, or a path to it (see the gcs backend)
    key = env.get("STORD__SERVICE_ACCOUNT_KEY", "")
    if key and not key.lstrip().startswith("{"):
        key = pathlib.Path(key).expanduser().read_text(encoding="utf-8")
    return key.strip()


def storage_keys(cloud: str, env: dict[str, str]) -> dict[str, str]:
    """The credential keys a mount of CLOUD may ask for, and their values.

    aws: the s3 system's region and credentials (STORS__). gcp: the bucket is
    reached either natively with the service-account key or over the S3
    protocol with the interop HMAC pair -- the gcs system carries both, and
    which one a mount asks for is tabsdata's to decide, so every spelling of
    either is known. azure: the storage account's shared key, under
    object_store's azure_storage_* names or the short ones tabsdata maps onto
    them."""
    if cloud == "aws":
        return {
            "aws_region": env.get("STORS__REGION", ""),
            "aws_access_key_id": env.get("STORS__ACCESS_KEY", ""),
            "aws_secret_access_key": env.get("STORS__SECRET_KEY", ""),
        }
    if cloud == "gcp":
        account = _gcs_service_account(env)
        return {
            "google_service_account_key": account,
            "gcp_service_account_key": account,
            "service_account_key": account,
            "google_service_account": account,
            "aws_access_key_id": env.get("STORD__HMAC_ACCESS_KEY", ""),
            "aws_secret_access_key": env.get("STORD__HMAC_SECRET_KEY", ""),
            "aws_endpoint": GCS_ENDPOINT,
            "aws_endpoint_url": GCS_ENDPOINT,
            "aws_region": "auto",
        }
    if cloud == "azure":
        account = env.get("STORD__ACCOUNT_NAME", "")
        key = env.get("STORD__ACCOUNT_KEY", "")
        return {
            "azure_storage_account_name": account,
            "account_name": account,
            "azure_storage_account_key": key,
            "account_key": key,
        }
    raise errors.ToolError(f"unknown cloud {cloud!r}; one of {', '.join(CLOUDS)}")


def fill_storage(
    path: pathlib.Path, cloud: str, env: dict[str, str] | None = None
) -> dict[str, list[str]]:
    """The per-mount `${{secret}}` of apiserver.storage.yaml: each mount's uri
    under the storage domain's URI (STORD__URI), and CLOUD's credentials on
    every mount, as `storage_keys` names them.

    Returns what was `filled`, what had no `empty` value and what was
    `unknown`. A key with no value or one no map knows is left alone, so
    `placeholders_left` then fails the stage naming it -- a one-line fix here
    rather than a broken instance. aws is the exception for an empty value: its
    keys come from the s3 system, which may hold none, and an empty one has
    always been written as it is."""
    env = dict(os.environ if env is None else env)
    uri = env.get("STORD__URI", "").rstrip("/")
    if not uri:
        raise errors.ToolError("no storage URI: STORD__URI is not set")
    mounts = {mount: f"{uri}/{folder}/" for mount, folder in STORAGE_MOUNTS.items()}
    keys = storage_keys(cloud, env)
    fill_empty = cloud == "aws"
    found: dict[str, list[str]] = {"filled": [], "empty": [], "unknown": []}
    out, mount = [], None
    for line in _read(path).splitlines(keepends=True):
        m = re.match(r"\s*- id: (\w+)", line)
        if m:
            mount = m.group(1)
        if STORAGE_PLACEHOLDER in line:
            key = line.split(":", 1)[0].strip()
            if key == "uri" and mount in mounts:
                line = line.replace(STORAGE_PLACEHOLDER, _scalar(mounts[mount]))
                found["filled"].append(f"{mount}.uri")
            elif key in keys and (keys[key] or fill_empty):
                line = line.replace(STORAGE_PLACEHOLDER, _scalar(keys[key]))
                found["filled"].append(key)
            elif key in keys:
                found["empty"].append(key)
            else:
                found["unknown"].append(key)
        out.append(line)
    _write(path, "".join(out))
    return {kind: sorted(set(names)) for kind, names in found.items()}


def event_field(lines: list[str], field: str) -> list[str]:
    """The list FIELD of the ok event in a command's JSON Lines output."""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        event = json.loads(line)
        if event.get("event") == "ok":
            value = event.get(field, [])
            return [str(v) for v in (value if isinstance(value, list) else [value])]
    raise errors.ToolError("no ok event in the output read")
