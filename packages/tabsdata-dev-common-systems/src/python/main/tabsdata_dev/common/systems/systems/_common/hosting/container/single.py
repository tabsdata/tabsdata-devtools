#
# Copyright 2026 Tabsdata Inc.
#

"""``SingleContainerHosting`` -- one container from a single ``docker run``.

Pick a host port and a password, pull the image for the host's architecture,
run it, wait until the server inside is ready, and later report on, restart or
remove it. A system supplies the image, the internal port, the server flags and
environment and the readiness probe. A system that keeps data names the path to
mount a named volume at (``volume_path``): the volume is called after the
container, starts empty on every create and goes with the container on destroy.
"""

from __future__ import annotations

import platform
import time
from typing import ClassVar

from tabsdata_dev.common.systems import constants, options
from tabsdata_dev.common.systems.errors import TdxError
from tabsdata_dev.common.systems.shell import (
    container_exists,
    container_failure,
    container_id,
    container_state,
    docker_exec_check,
    docker_pull,
    docker_restart,
    docker_rm,
    docker_run,
    docker_stop,
    docker_volume_rm,
    gen_password,
    require_docker,
)
from tabsdata_dev.common.systems.systems._common.hosting.container._base import (
    ContainerHosting,
)
from tabsdata_dev.common.systems.systems._common.hosting.endpoint import (
    DEFAULT_HOSTNAME,
)


class SingleContainerHosting(ContainerHosting):
    # ---- container hooks (subclass overrides) ----
    image: str = ""
    internal_port: int = 0
    cmd_args: ClassVar[list[str]] = []  # server flags appended after the image
    # docker-run flags before the image (db2: --privileged)
    extra_run_flags: ClassVar[list[str]] = []
    # where the server keeps its data, on a named volume; "" keeps it in the
    # container's own layer
    volume_path: str = ""

    image_platform = (
        "linux/arm64" if platform.machine() in ("arm64", "aarch64") else "linux/amd64"
    )

    def options(self) -> tuple[options.Option, ...]:
        return (
            options.Option("PORT", "port", options.PORT, "a free host port"),
            options.Option(
                "PASSWORD",
                "password",
                options.RANDOM,
                "a generated password",
                secret=True,
            ),
        )

    # ---- images / naming ------------------------------------------------

    def docker_images(self) -> list[tuple[str, str]]:
        return [(self.image, self.image_platform)]

    def container_name(self, sys_name: str) -> str:
        return f"{constants.DOCKER_NAME_PREFIX}{sys_name}"

    # ---- container hooks with defaults ----------------------------------

    def generate_password(self) -> str:
        """The system (admin) password. Overridden where the image mandates a
        fixed one (e.g. StarRocks allin1 requires the empty root password)."""
        return gen_password()

    def post_provision(self, container: str, password: str) -> None:
        """Run once the container is ready (e.g. create a shared database, tune a
        server config). Default: nothing."""

    def env_vars(self, password: str) -> dict[str, str]:
        """docker ``-e`` environment for the server container."""
        raise NotImplementedError

    def ready_exec_cmd(self, password: str) -> list[str]:
        """``docker exec`` argv that returns 0 once the server accepts
        connections (used by the default :meth:`check_ready`)."""
        raise NotImplementedError

    # ---- system lifecycle ----------------------------------------------

    def plan_system(
        self, name: str, overrides: dict[str, str] | None = None
    ) -> dict[str, str]:
        o = overrides or {}
        return {
            "DOCKER_CONTAINER_NAME": self.container_name(name),
            "IMAGE": self.image,
            "HOST": self.hostname,
            "PORT": o.get("PORT") or str(self.next_free_port()),
            "USER": self.root_user,
            "PASSWORD": o.get("PASSWORD") or self.generate_password(),
        }

    def provision_system(
        self, meta: dict[str, str], *, force: bool = False
    ) -> dict[str, str]:
        require_docker()
        container = meta["DOCKER_CONTAINER_NAME"]
        password = meta["PASSWORD"]
        port = int(meta["PORT"])
        if container_exists(container):
            if force:
                docker_rm(container, force=True)
                print(f">>> --force: removed existing container {container}")
            else:
                raise TdxError(f"container already exists: {container} (use --force)")
        if self.volume_path:
            docker_volume_rm(container)
        print(f">>> pulling docker image {self.image} …", flush=True)
        docker_pull(self.image, self.image_platform)
        print(f">>> starting container {container} from image {self.image}")
        docker_run(self._docker_args(container, port, password))
        print(f">>> waiting for {self.label} to become ready …")
        self._wait_ready(container, password, self.ready_timeout)
        self.post_provision(container, password)
        cid = container_id(container)
        return {"DOCKER_CONTAINER_ID": cid} if cid else {}

    def _docker_args(self, container: str, host_port: int, password: str) -> list[str]:
        args = [
            "-d",
            "-p",
            f"{host_port}:{self.internal_port}",
            "--name",
            container,
            "--platform",
            self.image_platform,
        ]
        args.extend(self.extra_run_flags)
        if self.volume_path:
            args += ["-v", f"{container}:{self.volume_path}"]
        for key, value in self.env_vars(password).items():
            args += ["-e", f"{key}={value}"]
        args.append(self.image)
        args.extend(self.cmd_args)
        return args

    def check_ready(self, container: str, password: str) -> bool:
        return docker_exec_check(container, *self.ready_exec_cmd(password))

    def _wait_ready(self, container: str, password: str, timeout: int) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.check_ready(container, password):
                return
            time.sleep(2)
        # The container is up and refusing connections, so it is running the
        # server and the server is saying why on its own stdout -- which is the
        # one thing this message cannot say.
        raise TdxError(
            f"{self.label} did not become ready within {timeout}s "
            f"(container {container} is up but not accepting connections)",
            container_failure(container),
        )

    def destroy_system(self, meta: dict[str, str]) -> None:
        cname = meta["DOCKER_CONTAINER_NAME"]
        st = container_state(cname)
        if st is None:
            raise TdxError(f"container does not exist: {cname}")
        if st == "running":
            docker_stop(cname)
        docker_rm(cname)
        if self.volume_path:
            docker_volume_rm(cname)

    def system_status(self, meta: dict[str, str]) -> tuple[bool, str]:
        cname = meta["DOCKER_CONTAINER_NAME"]
        st = container_state(cname)
        if st is None:
            return False, f"container {cname} does not exist"
        if st != "running":
            return False, f"container {cname} is {st}"
        if self.check_ready(cname, meta.get("PASSWORD", "")):
            host = meta.get("HOST", DEFAULT_HOSTNAME)
            return True, f"{self.label} on {host}:{meta.get('PORT', '')}"
        return False, f"{self.label} container is up but not yet accepting connections"

    def restart_system(self, meta: dict[str, str]) -> str:
        cname = meta["DOCKER_CONTAINER_NAME"]
        if container_state(cname) is None:
            raise TdxError(f"container does not exist: {cname}")
        docker_restart(cname)
        return "restarted"
