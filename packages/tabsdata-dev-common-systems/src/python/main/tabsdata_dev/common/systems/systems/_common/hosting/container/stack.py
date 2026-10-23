#
# Copyright 2026 Tabsdata Inc.
#

"""``ContainerStackHosting`` -- several containers brought up together as one
stack through ``docker compose``.

The stack runs against an explicit project name so concurrent stacks stay
isolated. ``plan_system`` picks the host ports up front (so the full descriptor
is written before ``up``) and ``provision_system`` brings the stack up and
waits for readiness, tearing it down on failure. A system supplies the compose
file and image list and the ``plan_endpoints`` / ``compose_env`` /
``wait_ready`` / ``system_health`` hooks.
"""

from __future__ import annotations

import contextlib

from tabsdata_dev.common.systems import constants
from tabsdata_dev.common.systems.errors import TdxError
from tabsdata_dev.common.systems.shell import (
    compose_container_ids,
    docker_compose,
    require_docker,
)
from tabsdata_dev.common.systems.systems._common.hosting.container._base import (
    ContainerHosting,
)


class ContainerStackHosting(ContainerHosting):
    compose_file: str = ""
    compose_images: tuple[tuple[str, str], ...] = ()

    def docker_images(self) -> list[tuple[str, str]]:
        return list(self.compose_images)

    def options(self) -> tuple:
        return ()  # declarative create options; overridden by backends that have any

    def _project(self, name: str) -> str:
        # compose rejects upper-case project names
        return f"{constants.DOCKER_NAME_PREFIX}{name}".lower()

    # ---- subclass hooks ------------------------------------------------

    def plan_endpoints(self) -> dict[str, str]:
        """Pick host ports / mint credentials and return the endpoint meta (no
        side effects — runs in plan_system)."""
        raise NotImplementedError

    def compose_env(self, meta: dict[str, str]) -> dict[str, str]:
        """Env vars the compose file interpolates (the planned ports, secrets)."""
        return {}

    def wait_ready(self, meta: dict[str, str], timeout: int) -> None:
        """Block until the stack is ready (poll a status endpoint), raise on
        timeout. Default: no wait."""

    def system_health(self, meta: dict[str, str]) -> tuple[bool, str]:
        project = meta.get("PROJECT", "")
        running = bool(compose_container_ids(project, self.compose_file))
        return (
            running,
            f"{self.label} stack {project} {'running' if running else 'down'}",
        )

    # ---- system lifecycle (compose) ------------------------------------

    def plan_system(
        self, name: str, overrides: dict[str, str] | None = None
    ) -> dict[str, str]:
        meta = {"PROJECT": self._project(name)}
        meta.update(self.plan_endpoints())
        return meta

    def provision_system(
        self, meta: dict[str, str], *, force: bool = False
    ) -> dict[str, str]:
        require_docker()
        project = meta["PROJECT"]
        if compose_container_ids(project, self.compose_file):
            if force:
                docker_compose(project, self.compose_file, "down", "-v")
                print(f">>> --force: removed existing stack {project}")
            else:
                raise TdxError(f"compose stack already exists: {project} (use --force)")
        env = self.compose_env(meta)
        print(f">>> pulling docker images for {self.label} …", flush=True)
        docker_compose(project, self.compose_file, "pull", env=env)
        print(f">>> starting {self.label} stack {project}")
        docker_compose(project, self.compose_file, "up", "-d", env=env)
        try:
            print(f">>> waiting for {self.label} to become ready …")
            self.wait_ready(meta, self.ready_timeout)
        except BaseException:
            print(f">>> provision failed — removing stack {project}")
            with contextlib.suppress(Exception):  # teardown is best-effort
                docker_compose(project, self.compose_file, "down", "-v")
            raise
        return {}

    def destroy_system(self, meta: dict[str, str]) -> None:
        docker_compose(meta["PROJECT"], self.compose_file, "down", "-v")

    def system_status(self, meta: dict[str, str]) -> tuple[bool, str]:
        return self.system_health(meta)

    def restart_system(self, meta: dict[str, str]) -> str:
        docker_compose(meta["PROJECT"], self.compose_file, "restart")
        return "restarted"
