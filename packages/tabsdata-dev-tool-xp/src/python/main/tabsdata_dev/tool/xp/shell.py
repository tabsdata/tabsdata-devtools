#
# Copyright 2026 Tabsdata Inc.
#
"""Shelling out: ``tdk`` and ``domain`` through the dispatcher (``tdd tdk`` /
``tdd domain``), with --dry-run echoing instead of running.

tdk lives in the user's managed venv and is reached through the `tdk` launcher
(``proc.tool_argv("tdk", …)`` -> ``tdd-exe … tdk``), so xp needs neither tdk
on its PATH nor tabsdata in its own toolset -- it needs ``_TDD_VENV`` to name a
venv with tabsdata installed, which the launcher checks. `domain` is the
sibling tool in this toolset, reached the same way.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys

from tabsdata_dev.common.core import proc

from . import state

# Boilerplate that carries no diagnosis: pydantic closes every validation error
# with a docs URL, so it would otherwise always win as the "last" stderr line.
_ERR_NOISE_RE = re.compile(r"For further information visit https?://")


def display(argv: list[str]) -> list[str]:
    """`tdd-exe --dir X tdk …` shown as `tdd tdk …`: what a person would type."""
    if argv and argv[0].endswith("tdd-exe"):
        rest = argv[1:]
        if rest[:1] == ["--dir"]:
            rest = rest[2:]
        return ["tdd", *rest]
    return argv


def shell_line(argv: list[str]) -> str:
    return " ".join(shlex.quote(a) for a in display(argv))


def dry_echo(argv: list[str]) -> None:
    """Under --dry-run print exactly one bare, shell-quoted command that WOULD run
    -- on stdout, so the view output is a paste-ready command list; an info event
    carrying the argv in json."""
    line = shell_line(argv)
    if state.run.out.fmt == "json":
        state.run.out.info(line, xp="dry-run", argv=display(argv))
    else:
        print(line, flush=True)


def dry_flag() -> list[str]:
    return ["--dry-run"] if state.run.dry_run else []


def profile_flag() -> list[str]:
    """--profile for a fan-out child, so every lane talks to the same connection."""
    return ["--profile", state.run.profile] if state.run.profile else []


def tdk_argv(*args: str) -> list[str]:
    """`tdd tdk ARGS [--profile P]`: every tdk call goes through here, so none
    of them can miss the profile. tdk gives `--profile` to each command, not to
    the root group, so it goes after the command -- last, where it is always
    past the verb."""
    return proc.tool_argv("tdk", *args, *profile_flag())


def run_cmd(
    argv: list[str], check: bool, stdin_text: str | None = None, env: dict | None = None
) -> subprocess.CompletedProcess:
    """Run one child with its output captured and logged to run.log. UTF-8 is
    pinned so tdk's box drawing decodes the same on every OS."""
    r = subprocess.run(
        argv,
        input=stdin_text,
        stdin=subprocess.DEVNULL if stdin_text is None else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    # Only into an open run: a check made before the reporter opens (the login
    # probe) must not conjure a bare, unlabelled one that the real run would
    # then inherit -- every line would read `xp -` instead of the suite.
    if state.run.reporter is not None:
        state.run.reporter.log(
            f"$ {shell_line(argv)} -> exit {r.returncode}",
            (r.stdout or "") + (r.stderr or ""),
        )
    if check and r.returncode != 0:
        state.die(f"command failed: {shell_line(argv)}\n       {err_detail(r)}")
    return r


def err_lines(r: subprocess.CompletedProcess) -> list[str]:
    """The informative stderr lines of a failed command: tdk's box chrome
    stripped, blank and boilerplate lines dropped."""
    out = []
    for raw in (r.stderr or "").splitlines():
        s = raw.strip().strip("│╭╮╰╯─").strip()
        if s and re.search(r"[A-Za-z0-9]", s) and not _ERR_NOISE_RE.search(s):
            out.append(s)
    return out


def last_err(r: subprocess.CompletedProcess) -> str:
    lines = err_lines(r)
    if lines:
        return lines[-1]
    return (r.stdout or "").strip()[:200] or "(no error output)"


def err_detail(r: subprocess.CompletedProcess, max_lines: int = 12) -> str:
    lines = err_lines(r)
    if not lines:
        return last_err(r)
    tail = lines[-max_lines:]
    if len(lines) > max_lines:
        tail.insert(0, f"[{len(lines) - max_lines} earlier line(s) omitted]")
    return "\n       ".join(tail)


def tdk(
    args: list[str],
    want_json: bool = True,
    check: bool = True,
    stdin_text: str | None = None,
):
    """The single tdk shell-out, through `tdd tdk`. Read commands run with
    --format json and return the parsed object; mutating commands pass
    want_json=False and return the CompletedProcess."""
    argv = tdk_argv(*args, *(["--format", "json"] if want_json else []))
    if state.run.dry_run:
        # A read is skipped silently -- callers get an empty result and plan a
        # fresh setup; a mutating call is printed but never run.
        if not want_json:
            dry_echo(argv)
        return None if want_json else subprocess.CompletedProcess(argv, 0, "", "")
    r = run_cmd(argv, check=check, stdin_text=stdin_text)
    if want_json:
        if r.returncode != 0:
            return None
        try:
            return json.loads(r.stdout)
        except json.JSONDecodeError:
            return None
    return r


def domain_env() -> dict:
    """Environment for a `domain` child: the crypto key from the var named by
    --secret-env mapped into the fixed _TDD_CRYPTO_KEY (a no-op when
    that var is the default)."""
    env = dict(os.environ)
    key = os.environ.get(state.run.secret_env)
    if key is not None:
        env[state.DEFAULT_SECRET_ENV] = key
    return env


def domain(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    argv = proc.tool_argv("domain", *args)
    if state.run.dry_run:
        # `info`/`list` are reads (skipped silently); the provisioning verbs are
        # printed but never run.
        if args and args[0] not in ("info", "list"):
            dry_echo(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")
    return run_cmd(argv, check=check, env=domain_env())


def last_event(stdout: str) -> dict | None:
    """The final event of a `--format json` child: its ok or error."""
    for line in reversed((stdout or "").splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                doc = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(doc, dict) and doc.get("event"):
                return doc
    return None


def require_login() -> None:
    """Abort unless there is a live tdk session (`tdk status` exits 0 only when
    logged in; stdin is closed so it cannot hang on its 'Server URL:' prompt)."""
    if state.run.dry_run:
        return
    r = run_cmd(tdk_argv("status"), check=False)
    if r.returncode != 0:
        state.die(
            f"not logged in to Tabsdata -- run `{shell_line(tdk_argv('login'))}` first ({last_err(r)})"
        )


def domain_descriptor(full_name: str, prefix: str = "") -> dict | None:
    """The domain's connection settings (its descriptor ``meta`` bag), or None
    if the domain does not exist. With ``prefix`` every key is ``<prefix>__<KEY>``."""
    r = domain(["info", "--domain", full_name, "--format", "json"], check=False)
    if r.returncode != 0:
        return None
    event = last_event(r.stdout)
    if not event or event.get("event") != "ok":
        return None
    descriptors = event.get("descriptors") or []
    meta = (
        descriptors[0].get("meta", {})
        if descriptors and isinstance(descriptors[0], dict)
        else {}
    )
    if prefix:
        return {f"{prefix}__{k}": v for k, v in meta.items()}
    return dict(meta)


def collection_descriptor(inst, c) -> dict:
    """Every backing domain's (prefixed) descriptor merged into one values dict."""
    merged: dict = {}
    for prefix, dname in c.domains.items():
        full = inst.domain_full(dname)
        info = domain_descriptor(full, prefix)
        if info is None:
            state.die(
                f"domain {full} not found -- run `create-domains --instance {inst.name}`"
            )
        merged.update(info)
    return merged


def stored_domains() -> set[str]:
    """Every domain name in the store, from ONE `tdd domain list --format json`."""
    if state.run.dry_run:
        return set()
    r = domain(["list", "--format", "json"], check=False)
    if r.returncode != 0:
        return set()
    event = last_event(r.stdout)
    rows = (event or {}).get("domains") or []
    return {
        str(row.get("name"))
        for row in rows
        if isinstance(row, dict) and row.get("name")
    }


def project_exists(project: str) -> bool:
    data = tdk(["project", "list"]) or []
    return any(p.get("name") == project for p in data)


def collection_names(project: str) -> set[str]:
    data = tdk(["collection", "list", "--proj", project], check=False) or []
    return {c.get("name") for c in data}


def flush_stdout() -> None:
    sys.stdout.flush()
