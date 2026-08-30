#
# Copyright 2026 Tabsdata Inc.
#

"""The docker CLI, wrapped: container lifecycle, exec, compose.

Shelling out to ``docker`` (not an SDK) keeps this standard-library only and
identical to what a person would type. Every failure is a ``ToolError`` carrying
docker's own message.
"""

from __future__ import annotations

import os
import subprocess

from .errors import ToolError


def require_docker() -> None:
    if (
        subprocess.run(
            ["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        ).returncode
        != 0
    ):
        raise ToolError("docker not found in PATH or daemon not running")


def container_exists(name: str) -> bool:
    return (
        subprocess.run(
            ["docker", "container", "inspect", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    )


def container_state(name: str) -> str | None:
    """`running`/`exited`/`created`/etc., or None if the container is absent."""
    cp = subprocess.run(
        ["docker", "container", "inspect", "-f", "{{.State.Status}}", name],
        capture_output=True,
        encoding="utf-8",
    )
    if cp.returncode != 0:
        return None
    return cp.stdout.strip() or None


def container_id(name: str) -> str | None:
    """Full docker id of container `name`, or None if absent. Raises ToolError if
    docker itself is unavailable (the caller can't tell staleness from that)."""
    try:
        cp = subprocess.run(
            ["docker", "container", "inspect", "-f", "{{.Id}}", name],
            capture_output=True,
            encoding="utf-8",
        )
    except FileNotFoundError as exc:
        raise ToolError("docker is not available") from exc
    if cp.returncode != 0:
        if "no such" in (cp.stderr or "").lower():
            return None
        raise ToolError(f"docker inspect failed: {cp.stderr.strip()}")
    return cp.stdout.strip() or None


def list_containers(name_prefix: str) -> list[dict]:
    """Every container, running or not, whose name starts with `name_prefix`:
    ``{"id", "name", "state", "image"}``. docker's ``name`` filter is a regex
    matched anywhere in the name, so it is anchored here and the prefix checked
    again in Python -- ``tdx2`` must not catch ``my_tdx2_thing``."""
    cp = subprocess.run(
        [
            "docker",
            "ps",
            "-a",
            "--filter",
            f"name=^{name_prefix}",
            "--format",
            "{{.ID}}\t{{.Names}}\t{{.State}}\t{{.Image}}",
        ],
        capture_output=True,
        encoding="utf-8",
    )
    if cp.returncode != 0:
        raise ToolError(f"docker ps failed: {cp.stderr.strip() or cp.stdout.strip()}")
    rows: list[dict] = []
    for line in cp.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        cid, names, state, image = parts[:4]
        for name in names.split(","):
            if name.startswith(name_prefix):
                rows.append({"id": cid, "name": name, "state": state, "image": image})
                break
    return rows


def docker_pull(image: str, platform: str = "") -> None:
    """Pull `image`, streaming docker's own download progress to stdout/stderr."""
    args = ["docker", "pull"]
    if platform:
        args += ["--platform", platform]
    args.append(image)
    if subprocess.run(args).returncode != 0:
        raise ToolError(f"docker pull failed for image {image}")


def docker_run(args: list[str]) -> str:
    cp = subprocess.run(["docker", "run"] + args, capture_output=True, encoding="utf-8")
    if cp.returncode != 0:
        raise ToolError(f"docker run failed: {cp.stderr.strip() or cp.stdout.strip()}")
    cid = cp.stdout.strip()
    if not cid:
        raise ToolError("docker run produced no container id")
    return cid


def docker_rm(name: str, force: bool = False) -> None:
    args = ["docker", "rm"]
    if force:
        args.append("-f")
    args.append(name)
    cp = subprocess.run(args, capture_output=True, encoding="utf-8")
    if cp.returncode != 0:
        detail = cp.stderr.strip() or cp.stdout.strip()
        raise ToolError(f"could not remove container {name}: {detail}")


def docker_start(name: str) -> None:
    cp = subprocess.run(
        ["docker", "start", name], capture_output=True, encoding="utf-8"
    )
    if cp.returncode != 0:
        detail = cp.stderr.strip() or cp.stdout.strip()
        raise ToolError(f"could not start container {name}: {detail}")


def docker_stop(name: str) -> None:
    cp = subprocess.run(["docker", "stop", name], capture_output=True, encoding="utf-8")
    if cp.returncode != 0:
        detail = cp.stderr.strip() or cp.stdout.strip()
        raise ToolError(f"could not stop container {name}: {detail}")


def docker_restart(name: str) -> None:
    cp = subprocess.run(
        ["docker", "restart", name], capture_output=True, encoding="utf-8"
    )
    if cp.returncode != 0:
        detail = cp.stderr.strip() or cp.stdout.strip()
        raise ToolError(f"could not restart container {name}: {detail}")


def docker_exec(
    container: str,
    *cmd: str,
    input: str | None = None,
    user: str | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Run a command in `container`, capturing stdout/stderr (and feeding
    `input` on stdin). Used by readiness probes / post-start hooks that need the
    command's output, not just its exit code."""
    args = ["docker", "exec", "-i"]
    if user is not None:
        args += ["-u", user]
    if env:
        for k, v in env.items():
            args += ["-e", f"{k}={v}"]
    args += [container, *cmd]
    return subprocess.run(args, input=input, capture_output=True, encoding="utf-8")


def docker_exec_check(container: str, *cmd: str) -> bool:
    """Run a check command in `container`; return True iff exit code 0."""
    return (
        subprocess.run(
            ["docker", "exec", container] + list(cmd),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    )


def docker_compose(
    project: str,
    compose_file: str,
    *args: str,
    capture: bool = False,
    env: dict[str, str] | None = None,
) -> str:
    """Run ``docker compose -p <project> -f <file> <args...>``. Streams output by
    default; ``capture=True`` returns stdout. ``env`` adds variables the compose
    file interpolates (e.g. the planned host ports)."""
    cmd = ["docker", "compose", "-p", project, "-f", compose_file, *args]
    run_env = {**os.environ, **env} if env else None
    verb = args[0] if args else ""
    if not capture:
        if subprocess.run(cmd, env=run_env).returncode != 0:
            raise ToolError(f"docker compose {verb} failed for project {project}")
        return ""
    cp = subprocess.run(cmd, capture_output=True, encoding="utf-8", env=run_env)
    if cp.returncode != 0:
        detail = (cp.stderr or cp.stdout or "").strip()
        raise ToolError(f"docker compose {verb} failed for project {project}: {detail}")
    return cp.stdout.strip()


def compose_container_ids(project: str, compose_file: str) -> list[str]:
    """Ids of every container of the compose project (running or stopped) — an
    existence check before ``up``."""
    out = docker_compose(project, compose_file, "ps", "-a", "-q", capture=True)
    return [line for line in out.splitlines() if line.strip()]
