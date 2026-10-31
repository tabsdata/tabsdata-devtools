#
# Copyright 2026 Tabsdata Inc.
#

"""The smoke scripts this package carries, and the tool that exports them.

They are shell, so most of what can be checked without a cluster is checked by
reading them -- which is enough for the contracts that have actually broken: a
required option quietly gaining a default, a value substituted into YAML in a
shape tdkserver refuses, a run writing to the developer's kubeconfig.
"""

import pathlib

from tabsdata_dev.common.core import render
from tabsdata_dev.tool import smoke


def _engine(resource_folder, function: str, *args, **kwargs):
    """Run one function of the smoke engine, _common.sh, with these arguments
    passed through untouched (engine.sh)."""
    import os
    import subprocess

    return subprocess.run(
        [
            "bash",
            resource_folder / "engine.sh",
            smoke.scripts_dir() / "_common.sh",
            function,
            *args,
        ],
        check=kwargs.pop("check", False),
        capture_output=True,
        text=True,
        env={**os.environ, "SMOKE_ENGINE": _smoke_engine()},
        **kwargs,
    )


def _smoke_engine() -> str:
    """The toolset's `_smoke` program, beside the python running the tests."""
    import shutil
    import sys

    found = shutil.which("_smoke", path=str(pathlib.Path(sys.executable).parent))
    assert found, "no _smoke beside this python: reinstall the tdd dir"
    return found


def test_the_package_carries_every_script_and_the_engine_they_share():
    names = {p.name for p in smoke.scripts()}
    assert names == {
        "_common.sh",
        "smoke-km.sh",
        "smoke-eks.sh",
        "smoke-gke.sh",
        "smoke-aks.sh",
    }, names
    # _common.sh is not a test but the stage engine every one of them sources:
    # exported without it, the other four cannot run, so it is listed first
    assert smoke.scripts()[0].name == smoke.SHARED


def test_export_writes_runnable_copies_and_will_not_silently_replace_them(tmp_path):
    """The reason to export is to edit, so overwriting is the one behaviour that
    loses work -- and a wheel carries no file mode, so an export that did not set
    one would hand over four scripts nobody can run."""
    out = render.Renderer("smoke", fmt="json")
    target = tmp_path / "somewhere" / "deeper"
    assert smoke.export(target, force=False, out=out) == 0
    written = sorted(p.name for p in target.glob("*.sh"))
    assert written == sorted(p.name for p in smoke.scripts())
    for script in target.glob("*.sh"):
        assert script.stat().st_mode & 0o111, script.name

    (target / "smoke-eks.sh").write_text("# mine now\n")
    assert smoke.export(target, force=False, out=out) == 1  # refused
    assert (target / "smoke-eks.sh").read_text() == "# mine now\n"
    assert smoke.export(target, force=True, out=out) == 0
    assert (target / "smoke-eks.sh").read_text() != "# mine now\n"


def test_every_smoke_script_leaves_a_foreign_venv_before_creating_one():
    """A developer runs these from the shell they work in, which is usually
    standing in a venv -- and `tdd venv create` refuses under one tdd did not
    activate. Each script leaves it first, with --force, which is the only form
    that leaves a venv tdd did not enter. km had this already but without
    --force, so the very case it guarded against still got through."""
    scripts = smoke.scripts_dir()
    found = sorted(scripts.glob("smoke-*.sh"))
    assert found, "no smoke scripts found"
    for path in found:
        text = path.read_text()
        assert "tdd venv deactivate --force" in text, path.name
        # and not the silent unforced form it replaced: with no --force it cannot
        # leave a venv tdd did not enter, which is the only case worth guarding
        assert "tdd venv deactivate >/dev/null" not in text, path.name
        # before the create, not after it
        assert text.index("tdd venv deactivate --force") < text.index(
            "tdd venv create --name"
        ), path.name


def test_every_cluster_smoke_runs_on_its_own_copy_of_the_kubeconfig():
    """`--kube-config` picks the FILE, `--kube-context` picks the cluster, and
    the run must leave both alone: a developer's current context belongs to
    whatever else they have open. But tdkserver reads the cluster and namespace
    from the kubeconfig's CURRENT context, and `venv update`, `config` and
    `delete` take no --context to say otherwise -- so the run copies the file,
    makes the copy current on its own context and namespace, and points
    tdkserver at that. Nothing is borrowed, so nothing has to be given back."""
    root = smoke.scripts_dir()
    for path in sorted(root.glob("smoke-*.sh")):
        text = path.read_text()
        if "KUBECTL=(" not in text:
            continue
        assert 'cp "$KUBECONFIG_OPT" "$RUN_KUBECONFIG"' in text, path.name
        assert (
            'KUBECTL=(kubectl --kubeconfig "$RUN_KUBECONFIG" --context "$CONTEXT")'
            in text
        ), path.name
        # what the developer passed in is only ever read
        for line in text.splitlines():
            if line.lstrip().startswith("#"):
                continue
            if "config use-context" in line or "config set-context" in line:
                assert "$KUBECONFIG_OPT" not in line, (path.name, line.strip())
        # and with nothing borrowed there is nothing to restore
        assert "PREV_CONTEXT" not in text and "PREV_NAMESPACE" not in text, path.name


def test_every_cluster_smoke_requires_the_options_it_cannot_guess():
    """A cluster run reaches a named cluster, and there is no sane default for
    which one -- so the four that name it are required and common_help paints
    them red. The namespace and the index are not among them: the run's own
    --name makes a namespace, and no index means whatever uv already uses."""
    root = smoke.scripts_dir()
    needed = {"--name", "--kube-config", "--kube-context", "--td-version"}
    for path in sorted(root.glob("smoke-*.sh")):
        text = path.read_text()
        if "KUBECTL=(" not in text:
            continue
        declared = text.split('REQUIRED_OPTIONS="', 1)[1].split('"', 1)[0].split()
        assert set(declared) == needed, (path.name, declared)
        # the page is painted by the same engine every tdd command uses
        assert 'common_help "$REQUIRED_OPTIONS"' in text, path.name


def test_every_cluster_smoke_fills_its_storage_as_its_own_cloud():
    """One fill for the three clouds (`tdd _smoke fill-storage`, its scalars
    pinned in test_configs), each script naming its own: the map is what knows
    a cloud's option keys. Every cluster script, found the way the context test
    finds them, so a new cloud's script is held to it the day it is written."""
    clouds = {"eks": "aws", "gke": "gcp", "aks": "azure"}
    cluster = [
        p
        for p in sorted(smoke.scripts_dir().glob("smoke-*.sh"))
        if "KUBECTL=(" in p.read_text()
    ]
    assert cluster, "no kubectl-using smoke scripts found"
    for path in cluster:
        cloud = clouds[path.stem.split("-")[1]]
        call = (
            'common_run tdd _smoke fill-storage --file "$CONFIGS/apiserver.storage.yaml"'
            f" --cloud {cloud}"
        )
        assert call in path.read_text(), path.name


def test_every_cluster_smoke_collects_the_cluster_s_account_of_a_failure():
    """`Init job 'ins-dbmanager' failed` names the job and stops; the reason is in
    the pod, and the next run's clean-previous deletes the namespace it is in. So
    the failure hook pulls pods, jobs, events and the failed pods' logs into the
    log while they still exist -- init containers included, since a tabsdata pod
    does its real work in them and plain `kubectl logs` shows none of it."""
    root = smoke.scripts_dir()
    common = (root / "_common.sh").read_text()
    assert "common_k8s_report()" in common
    # the three things that make it usable inside a failure report
    assert "--all-containers=true" in common and "--prefix" in common
    assert "--previous" in common
    assert "--request-timeout=" in common, "a dead cluster must not hang the report"
    for path in sorted(root.glob("smoke-*.sh")):
        text = path.read_text()
        if "KUBECTL=(" not in text:
            continue
        hook = text.split("common_on_stage_failed() {", 1)[1].split("\n}", 1)[0]
        assert "common_k8s_report" in hook, path.name


def test_the_gke_smoke_fills_the_database_ca_before_checking_placeholders():
    """Cloud SQL signs with a per-instance CA, so gke's dbmanager template is the
    only one asking for the certificate inline as a `secret:` -- eks, aks and
    fargate name a path tdkserver fills from a bundle baked into the image. The
    domain carries the PEM; the run has to put it in before it declares the
    config complete."""
    gke = smoke.scripts_dir() / "smoke-gke.sh"
    lines = gke.read_text().splitlines()

    def called(name: str) -> int:
        # the call, not a comment that discusses it
        return next(
            i
            for i, line in enumerate(lines)
            if name in line and not line.lstrip().startswith("#")
        )

    assert "tdk_database_ssl_root_cert_pem" in "\n".join(lines)
    assert called("common_fill_pem") < called("tdd _smoke placeholders-left")


def test_the_help_reads_long_form_first():
    """An option with both forms reads long then short, as everywhere else in
    tdd -- a hand-aligned page gets that wrong on its own. How a page is painted
    is test_screen's."""
    for path in smoke.scripts_dir().glob("smoke-*.sh"):
        text = path.read_text()
        assert "  -f, --force" not in text, path.name
        assert "  -h, --help" not in text, path.name
        assert "  --force, -f" in text and "  --help, -h" in text, path.name


def test_the_powershell_family_runs_its_own_scripts(monkeypatch):
    """A family is the shell the user is in: under PowerShell the tool lists,
    resolves and runs the .ps1 scripts -- those written so far -- through
    pwsh -File, and names its own choices for one it does not have."""
    import argparse

    import pytest
    from tabsdata_dev.common.core.errors import ToolError

    monkeypatch.setenv("_TDD_SHELL_FAMILY", "powershell")
    names = [p.name for p in smoke.scripts()]
    assert names[0] == "_common.ps1" and "smoke-km.ps1" in names, names
    assert all(n.endswith(".ps1") for n in names), names
    for spelling in ("km", "smoke-km", "smoke-km.ps1", "smoke-km.sh"):
        assert smoke.resolve_script(spelling).name == "smoke-km.ps1", spelling
    absent = sorted(
        set(smoke.script_names(smoke.FAMILIES["unix"])) - set(smoke.script_names())
    )
    for name in absent:
        with pytest.raises(ToolError, match="one of: "):
            smoke.resolve_script(name)

    calls = []

    class Done:
        returncode = 0

    monkeypatch.setattr(
        smoke.proc, "run", lambda argv, **_: calls.append(argv) or Done()
    )
    out = render.Renderer("smoke", fmt="json")
    args = argparse.Namespace(action="run", script="km", script_options=[])
    assert smoke.body(args, out, script_args=["--name", "x"]) == 0
    assert calls[0][:3] == ["pwsh", "-NoProfile", "-File"]
    assert calls[0][3].endswith("smoke-km.ps1") and calls[0][4:] == ["--name", "x"]


def _help_options(text: str) -> list[str]:
    """The options a script's help page lists, in order."""
    import re

    page = text.split("options:", 1)[1].split("\n\n", 1)[0]
    return re.findall(r"^  (--[a-z-]+)", page, flags=re.MULTILINE)


def _stages(text: str) -> list[str]:
    import re

    return re.findall(
        r"^\s*common_stage (?:--continue )?([a-z0-9-]+)", text, flags=re.MULTILINE
    )


def test_every_powershell_script_is_its_bash_twin():
    """The same command in both families: a .ps1 script has its .sh, takes the
    same options and runs the same stages, in order."""
    unix, powershell = smoke.FAMILIES["unix"], smoke.FAMILIES["powershell"]
    for ps1 in smoke.scripts(powershell):
        sh = ps1.with_suffix(unix.suffix)
        assert sh.is_file(), ps1.name
        if ps1.name == powershell.shared:
            continue
        ps1_text, sh_text = ps1.read_text(), sh.read_text()
        assert _help_options(ps1_text) == _help_options(sh_text), ps1.name
        assert _stages(ps1_text) == _stages(sh_text), ps1.name


def test_the_scripts_carry_no_inline_interpreter():
    """An algorithm is `tdd _smoke`'s, written once for both shell families: a
    python heredoc or a perl one-liner in a script is a copy the PowerShell
    twin would have to make again. perl was also a second interpreter for a
    script whose whole job is checking an install."""
    for path in [
        *smoke.scripts(smoke.FAMILIES["unix"]),
        *smoke.scripts(smoke.FAMILIES["powershell"]),
    ]:
        code = [
            ln
            for ln in path.read_text().splitlines()
            if not ln.lstrip().startswith("#")
        ]
        for word in ("perl", "python3", "PYEOF"):
            assert not [ln for ln in code if word in ln], (path.name, word)


def test_the_failure_report_names_only_what_the_run_actually_built(
    tmp_path,
    resource_folder,
):
    """The report under `left for you to look at` is read at the one moment the
    reader is chasing a failure, so everything in it has to be there. A run that
    dies in an early stage has built no instance and no venv: naming them, with
    cleanup commands for paths that were never written, sends the reader after
    ghosts. The instance and venv are on disk and get asked; the domains are the
    script's own record, appended as each one is created."""
    import os
    import subprocess

    common = smoke.scripts_dir() / "_common.sh"
    # A name no real run would take: the report asks the machine's own
    # process table whether the instance is running (`tdd _smoke
    # instance-pids`, by "instances/<name>/"), so a fixture sharing a name with a live smoke
    # run is told its instance is up, and the test fails on whatever the
    # developer happens to have open.
    home = tmp_path / "home"
    tdd = tmp_path / "tdd"
    venv = tdd / "managed-venvs" / "pyenv" / "sm_fixture_notarealrun"
    instance = home / ".tabsdata" / "instances" / "sm_fixture_notarealrun"

    def report(domains: str = "") -> list[str]:
        done = subprocess.run(
            [
                "bash",
                resource_folder / "setup_info.sh",
                common,
                tdd,
                tmp_path / "log",
                domains,
            ],
            check=False,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "HOME": str(home),
                "NO_COLOR": "1",
                "SMOKE_ENGINE": _smoke_engine(),
            },
        )
        assert done.returncode == 0, done.stderr
        assert not done.stderr, done.stderr
        return [ln.strip() for ln in done.stdout.splitlines() if ln.strip()]

    # nothing built yet: no instance, no venv, and no teardown for either
    lines = report()
    assert [ln for ln in lines if ln.startswith("nothing")], lines
    assert not [
        ln for ln in lines if ln.split()[0] in ("instance", "venv", "remove")
    ], lines

    # the venv alone: its own delete, and nothing about an instance
    venv.mkdir(parents=True)
    lines = report()
    assert "remove     tdd venv delete --name sm_fixture_notarealrun" in lines
    assert not [ln for ln in lines if ln.startswith(("instance", "nothing"))], lines

    # both, plus a domain the script says it created
    instance.mkdir(parents=True)
    lines = report(domains="sm_fixture_notarealrun__gcppostgres")
    assert [
        ln
        for ln in lines
        if ln.startswith("instance   sm_fixture_notarealrun -- not running")
    ], lines
    assert [
        ln for ln in lines if ln.startswith("venv       sm_fixture_notarealrun (pyenv)")
    ], lines
    assert [
        ln
        for ln in lines
        if ln.startswith("domain     sm_fixture_notarealrun__gcppostgres --")
    ], lines
    assert [
        ln for ln in lines if "tdkserver delete" in ln and "tdd venv delete" in ln
    ], lines

    # the cluster scripts' own lines are held to the same rule: a namespace that
    # was never created gets no delete command and no port-forward
    for path in sorted(smoke.scripts_dir().glob("smoke-*.sh")):
        text = path.read_text()
        if "common_k8s_report" not in text:
            continue  # km brings its own cluster
        block = text.split("common_on_stage_failed() {", 1)[1].split("\n}\n", 1)[0]
        guard = block.index("common_k8s_namespace_exists")
        assert guard < block.index('"namespace  $NAMESPACE'), path.name
        assert guard < block.index('"reach it   kubectl'), path.name

    # and every script records a domain as it creates it, never up front
    for path in sorted(smoke.scripts_dir().glob("smoke-*.sh")):
        text = path.read_text()
        assert 'SMOKE_DOMAINS=""' in text, path.name
        creates = [
            ln.strip()
            for ln in text.splitlines()
            if "tdd domain create --domain" in ln or "tdd domain create --sys" in ln
        ]
        appends = [
            ln for ln in text.splitlines() if 'SMOKE_DOMAINS="$SMOKE_DOMAINS' in ln
        ]
        assert len(appends) == len(creates), (path.name, creates, appends)


def test_the_port_forward_listens_locally_where_it_is_told_and_points_at_the_apiserver(
    tmp_path,
    resource_folder,
):
    """`--kube-port-forward` moves the LOCAL end of the forward only. That end is
    the one another run, a forward a --keep run left, or a local tdkserver can
    already hold; the apiserver's port in its own namespace clashes with nothing,
    and moving it along would smoke a port nobody deploys with. So the helper
    takes LOCAL and REMOTE, kubectl is told `LOCAL:REMOTE`, readiness is probed
    on LOCAL, and a LOCAL something else already answers on is refused by name
    before kubectl runs -- otherwise the probe would have called it up and the
    run logged in to whatever was there. A fake kubectl stands in for the
    cluster: it records its arguments and listens where the real one would."""
    import socket
    import subprocess

    env, record, local = _fake_kubectl(tmp_path, resource_folder)
    common = smoke.scripts_dir() / "_common.sh"

    def start(port: int, log) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                "bash",
                resource_folder / "forward_once.sh",
                common,
                log,
                str(port),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=90,
            env=env,
        )

    log = tmp_path / "log"
    done = start(local, log)
    assert done.returncode == 0, (done.stdout, done.stderr, log.read_text())
    # kubectl was told LOCAL:REMOTE, the two apart -- not the mirror
    assert record.read_text().split() == [
        "port-forward",
        "--kubeconfig",
        "/tmp/cfg",
        "--namespace",
        "sm-x",
        "service/net-apiserver",
        f"{local}:2457",
    ]
    text = log.read_text()
    # readiness was judged on LOCAL, and the line says which end is which
    assert (
        f"port-forward up: 127.0.0.1:{local} -> service/net-apiserver:2457 in sm-x"
        in text
    )
    assert "port-forward stopped" in text

    # something else on LOCAL: refused by name, and kubectl never ran
    record.unlink()
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        busy = taken.getsockname()[1]
        log2 = tmp_path / "log2"
        done = start(busy, log2)
    assert done.returncode != 0
    assert (
        f"127.0.0.1:{busy} is already taken; pick another with --kube-port-forward"
        in log2.read_text()
    )
    assert not record.exists(), record.read_text()


def test_every_cluster_smoke_keeps_the_forward_s_two_ends_apart():
    """The option is `--kube-port-forward`, not `--port`: it is the forward's local
    end, and the scripts keep the two ends apart. `tdkserver create --port` and the
    far side of every forward get PORT, the apiserver's; the near side, and so the
    server URL tdk logs in to, get FORWARD_PORT. A script feeding one to both
    would either smoke a port nobody deploys with or log in to a port nothing
    listens on. km is not held to this: its --port is the instance's, one thing."""
    root = smoke.scripts_dir()
    for path in sorted(root.glob("smoke-*.sh")):
        text = path.read_text()
        if "KUBECTL=(" not in text:
            continue
        assert '--kube-port-forward) FORWARD_PORT="$2"; shift 2 ;;' in text, path.name
        # One local port per script, so two runs on a laptop do not fight over
        # it: km 10000, eks 11000, aks 12000, gke 13000. The apiserver's own
        # port in the cluster stays 2457 in all of them.
        want = {"eks": "11000", "aks": "12000", "gke": "13000"}[path.stem.split("-")[1]]
        assert f'FORWARD_PORT="{want}"' in text, path.name
        assert 'PORT="2457"' in text, path.name
        assert 'SERVER="http://127.0.0.1:$FORWARD_PORT"' in text, path.name
        assert 'tdkserver create --instance "$INSTANCE" --port "$PORT"' in text, (
            path.name
        )
        starts = [
            ln.strip()
            for ln in text.splitlines()
            if ln.lstrip().startswith("common_kubeportforward_start ")
        ]
        assert starts and all(
            ln.endswith('net-apiserver "$FORWARD_PORT" "$PORT"') for ln in starts
        ), (path.name, starts)
        # what the reader is handed to re-establish it by hand says the same
        assert "$PORT:$PORT" not in text, path.name
        assert "service/net-apiserver $FORWARD_PORT:$PORT" in text, path.name
        # and a value that is not a port is refused before anything is built
        assert "--kube-port-forward must be a port number" in text, path.name


def test_every_cluster_smoke_sizes_its_function_pods_before_the_shape_check():
    """The two options, their halved defaults, and the rewrite as a stage command
    ahead of the placeholder and config checks -- so a sizing that missed fails
    at `configure`, in the stage that owns the config, with the other fills."""
    root = smoke.scripts_dir()
    for path in sorted(root.glob("smoke-*.sh")):
        text = path.read_text()
        if "KUBECTL=(" not in text:
            continue
        assert 'FN_MEMORY="8Gi"' in text and 'FN_DISK="32Gi"' in text, path.name
        assert '--td-fn-memory) FN_MEMORY="$2"; shift 2 ;;' in text, path.name
        assert '--td-fn-disk) FN_DISK="$2"; shift 2 ;;' in text, path.name
        # a typo fails at the option, not at the first pod that never schedules
        assert "--td-fn-memory must be a Kubernetes quantity" in text, path.name
        assert "--td-fn-disk must be a Kubernetes quantity" in text, path.name
        call = (
            'common_run tdd _smoke set-fn-resources --file "$CONFIGS/tabsdata.yaml"'
            ' --memory "$FN_MEMORY" --disk "$FN_DISK"'
        )
        assert call in text, path.name
        assert text.index("common_stage configure") < text.index(call), path.name
        assert text.index(call) < text.index(
            'common_run tdd _smoke placeholders-left --dir "$CONFIGS"'
        ), path.name
        assert text.index(call) < text.index("tdkserver config check --instance"), (
            path.name
        )


def _fake_kubectl(tmp_path, resource_folder):
    """A kubectl whose port-forward listens on the local port and records each
    launch and its own pid, so a test can kill it the way the tunnel would; its
    listener runs on this python. Returns (env, record, a free local port)."""
    import os
    import shutil
    import socket
    import sys

    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    record = tmp_path / "record"
    pidfile = tmp_path / "kubectl.pid"
    kubectl = fakebin / "kubectl"
    shutil.copy(resource_folder / "fake_kubectl.sh", kubectl)
    shutil.copy(resource_folder / "listen.py", fakebin / "listen.py")
    kubectl.chmod(0o755)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        local = probe.getsockname()[1]
    env = {
        **os.environ,
        "PATH": f"{fakebin}:{os.environ['PATH']}",
        "RECORD": str(record),
        "PIDFILE": str(pidfile),
        "FAKE_PYTHON": sys.executable,
        "NO_COLOR": "1",
        "SMOKE_ENGINE": _smoke_engine(),
    }
    return env, record, local


def test_the_forward_is_relaunched_when_kubectl_exits_and_checked_before_a_suite(
    tmp_path,
    resource_folder,
):
    """A port-forward is one stream through the cluster's tunnel, and the tunnel
    drops on its own (AKS replacing the node that carries its konnectivity agents
    did it on two consecutive days). kubectl does not reconnect, so the start runs
    it under a supervisor that relaunches it whenever it exits, and every xp stage
    opens with an ensure: the port answers, or the supervisor gets a moment, or
    the forward is started afresh. A kubectl that dies this young is paused for."""
    import subprocess

    env, record, local = _fake_kubectl(tmp_path, resource_folder)
    common = smoke.scripts_dir() / "_common.sh"
    log = tmp_path / "log"
    done = subprocess.run(
        [
            "bash",
            resource_folder / "forward_relaunch.sh",
            common,
            log,
            str(local),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    text = log.read_text()
    assert done.returncode == 0, (done.returncode, done.stdout, done.stderr, text)
    # three kubectl launches: the start, the supervisor's relaunch, the fresh start
    launches = record.read_text().splitlines()
    assert len(launches) == 3, launches
    assert all(ln.endswith(f"service/net-apiserver {local}:2457") for ln in launches)
    # and the log says which was which
    assert "kubectl exited" in text and "relaunching in 2s" in text
    assert "the supervisor relaunched kubectl" in text
    assert "port-forward supervisor is gone; starting the forward afresh" in text
    assert text.count("port-forward up:") == 3, text


def test_a_forward_that_had_been_up_is_relaunched_without_a_pause(
    tmp_path,
    resource_folder,
):
    """The eks smoke of 2026-10-04 lost a suite to the pause alone: three
    collection creates were refused in the 2s before the relaunch. A kubectl
    that had been up PORTFORWARD_STEADY seconds dropped a working tunnel, so it
    is relaunched at once (0 here, so the test need not wait)."""
    import subprocess

    env, record, local = _fake_kubectl(tmp_path, resource_folder)
    common = smoke.scripts_dir() / "_common.sh"
    log = tmp_path / "log"
    done = subprocess.run(
        [
            "bash",
            resource_folder / "forward_steady.sh",
            common,
            log,
            str(local),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
        env={**env, "PORTFORWARD_STEADY": "0"},
    )
    text = log.read_text()
    assert done.returncode == 0, (done.returncode, done.stdout, done.stderr, text)
    assert len(record.read_text().splitlines()) == 2
    assert "(the tunnel dropped?); relaunching now" in text
    assert "relaunching in 2s" not in text


def test_the_forward_ends_with_the_script_that_started_it(
    tmp_path,
    resource_folder,
    monkeypatch,
):
    """A run killed outright never reaches its EXIT trap: the supervisor sees
    the script gone and ends, kubectl with it, so no forward holds the port."""
    import subprocess
    import sys
    import time

    from tabsdata_dev.tool.smoke import forward

    env, _, local = _fake_kubectl(tmp_path, resource_folder)
    for name in ("PATH", "RECORD", "PIDFILE", "FAKE_PYTHON"):
        monkeypatch.setenv(name, env[name])
    script = subprocess.Popen(
        [sys.executable, str(resource_folder / "listen.py"), "0:0"]
    )
    target = forward.Forward("/tmp/cfg", "sm-x", "net-apiserver", local, 2457)
    run = forward.Run(
        tmp_path / "state",
        tmp_path / "stop",
        tmp_path / "log",
        script.pid,
        10,
    )
    try:
        assert forward.start(target, run, [].append)
        script.kill()
        script.wait()
        for _ in range(50):
            if not forward.answers(local):
                break
            time.sleep(0.2)
        assert not forward.answers(local), (tmp_path / "log").read_text()
    finally:
        forward.stop(target, run, [].append)


def test_every_cluster_smoke_checks_the_forward_before_each_suite_and_skips_it_otherwise():
    """Every xp stage opens with the ensure, and a forward that cannot be started
    afresh skips the suite instead of letting it fail lane by lane as "not logged
    in" -- the stage is --continue, so `|| continue` is what carries the skip."""
    root = smoke.scripts_dir()
    for path in sorted(root.glob("smoke-*.sh")):
        text = path.read_text()
        if "KUBECTL=(" not in text:
            continue
        loop = text.split('common_stage --continue "xp-', 1)[1].split("\ndone\n", 1)[0]
        assert "common_kubeportforward_ensure || continue" in loop, path.name
        assert loop.index("common_kubeportforward_ensure") < loop.index(
            "common_run tdd xp one-shot"
        ), path.name


def test_run_owns_script_and_hands_the_script_everything_else():
    """`run` is the launchers' arrangement: one option of its own, everything
    else the script's, in order. `--script` is taken from anywhere after the
    word because `tdd` appends a config preset at the END of the line. Help is
    the tool's until the script is named and the script's after -- the person
    asking has named what they want to read about."""
    split = smoke.split_run
    assert split(["run", "--script", "eks", "--name", "x", "--verbose"]) == (
        ["run", "--script", "eks"],
        ["--name", "x", "--verbose"],
    )
    assert split(["run", "--name", "x", "--script", "eks"]) == (
        ["run", "--script", "eks"],
        ["--name", "x"],
    )
    assert split(["run", "--script=gke", "--keep"]) == (
        ["run", "--script=gke"],
        ["--keep"],
    )
    assert split(["run", "--help"]) == (["run", "--help"], [])
    assert split(["run", "-h", "--script", "eks"]) == (
        ["run", "-h", "--script", "eks"],
        [],
    )
    assert split(["run", "--script", "eks", "--help"]) == (
        ["run", "--script", "eks"],
        ["--help"],
    )
    assert split(["run", "--script", "eks", "--", "--name", "x"]) == (
        ["run", "--script", "eks"],
        ["--name", "x"],
    )
    # the tool's own leading options stay with it, --format's value included
    assert split(["--format", "json", "run", "--script", "km", "--port", "1"]) == (
        ["--format", "json", "run", "--script", "km"],
        ["--port", "1"],
    )
    assert split(["--verbose", "run", "--script", "km"]) == (
        ["--verbose", "run", "--script", "km"],
        [],
    )
    # every other line passes through untouched
    for argv in (
        ["list"],
        ["export-scripts", "--dir", "d"],
        ["config", "--show"],
        [],
        ["--help"],
    ):
        assert split(argv) == (argv, [])


def test_a_script_is_named_in_any_spelling_and_the_choices_are_named_otherwise():
    import pytest
    from tabsdata_dev.common.core.errors import ToolError

    root = smoke.scripts_dir()
    for spelling in ("eks", "smoke-eks", "smoke-eks.sh"):
        assert smoke.resolve_script(spelling) == root / "smoke-eks.sh"
    assert smoke.script_names() == ["aks", "eks", "gke", "km"]
    for bad in ("nope", "_common", "_common.sh", "", "../smoke-eks"):
        with pytest.raises(ToolError) as caught:
            smoke.resolve_script(bad)
        assert "aks, eks, gke, km" in str(caught.value), bad
    # what `list` says each one is: the script's own first line, not a table here
    assert smoke.summary(root / "smoke-eks.sh") == "Tabsdata EKS smoke test"
    assert (
        smoke.summary(root / smoke.SHARED) == "the plumbing every smoke script shares"
    )
    for path in smoke.scripts():
        if path.name != smoke.SHARED:
            assert smoke.summary(path).startswith("Tabsdata "), path.name


def test_run_executes_the_carried_copy_through_bash_without_tdds_private_variable(
    monkeypatch,
):
    """Through bash because the wheel keeps no exec bit. TDD_DIR travels on so
    the script's --tdd-dir defaults to the dir the tool runs from; _TDD_TOOL does
    not, since the sourced `tdd` function warns about a shell carrying one. A
    non-zero exit is one error event and 1, the launchers' way; an unknown script
    never reaches bash."""
    import argparse

    import pytest
    from tabsdata_dev.common.core.errors import ToolError

    calls: list[tuple[list[str], dict]] = []
    statuses = [0, 3]

    class Done:
        def __init__(self, rc: int):
            self.returncode = rc

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs.get("env") or {}))
        return Done(statuses.pop(0))

    monkeypatch.setattr(smoke.proc, "run", fake_run)
    monkeypatch.setenv("_TDD_TOOL", "smoke")
    monkeypatch.setenv("TDD_DIR", "/somewhere/tdd")
    out = render.Renderer("smoke", fmt="json")
    args = argparse.Namespace(action="run", script="eks", script_options=[])
    assert (
        smoke.body(args, out, script_args=["--name", "x", "--td-version", "2.1.0"]) == 0
    )
    argv, env = calls[0]
    assert argv == [
        "bash",
        str(smoke.scripts_dir() / "smoke-eks.sh"),
        "--name",
        "x",
        "--td-version",
        "2.1.0",
    ]
    assert "_TDD_TOOL" not in env and env["TDD_DIR"] == "/somewhere/tdd"
    assert smoke.body(args, out, script_args=[]) == 1
    with pytest.raises(ToolError):
        smoke.body(
            argparse.Namespace(action="run", script="nope", script_options=[]),
            out,
            script_args=[],
        )
    assert len(calls) == 2
    # and what run needs is what the tool declares: its family's shell,
    # required; a previous run's tdkserver, which instance-stop may find
    package = smoke.scripts_dir().parent / "packages" / "tabsdata-dev-tool-smoke"
    expected = {
        "bin-reqs.txt": ["[optional]", "kubectl", "tdkserver"],
        "bin-reqs.unix.txt": ["[required]", "bash"],
        "bin-reqs.powershell.txt": ["[required]", "pwsh"],
    }
    if package.is_dir():  # the checkout layout; a wheel carries the catalog instead
        for name, lines in expected.items():
            declared = [
                ln.split("#", 1)[0].strip()
                for ln in (package / name).read_text().splitlines()
                if ln.split("#", 1)[0].strip()
            ]
            assert declared == lines, (name, declared)


def test_list_names_the_scripts_with_how_to_run_each_and_not_the_engine():
    """`list` is what a person can run. `_common.sh` is carried and exported --
    four scripts without it do not run -- but it is not a script to run, so it
    is not on the list (the user: "it should not list script starting with _")."""
    import argparse
    import io
    import json

    buf = io.StringIO()
    out = render.Renderer("smoke", fmt="json", out=buf, err=buf)
    assert smoke.body(argparse.Namespace(action="list"), out) == 0
    events = [
        json.loads(ln) for ln in buf.getvalue().splitlines() if ln.startswith("{")
    ]
    infos = [e["message"] for e in events if e["event"] == "info"]
    assert [m.split()[0] for m in infos] == [
        "smoke-aks.sh",
        "smoke-eks.sh",
        "smoke-gke.sh",
        "smoke-km.sh",
    ], infos
    assert not [m for m in infos if m.startswith("_")]
    for m in infos:
        assert "Tabsdata " in m and "(tdd smoke run --script " in m, m
    done = next(e for e in events if e["event"] == "ok")
    assert (
        done["scripts"] == ["aks", "eks", "gke", "km"]
        and done["engine"] == "_common.sh"
    )


def test_uv_index_markers_resolve_and_an_unknown_one_is_refused(resource_folder):
    """`--uv-index` takes @dev and @prod as well as a URL, so a run can say
    which index it means instead of carrying a CloudFront hostname nobody can
    check by eye. An unknown marker is refused at parse time: passed on, uv
    would take it for a URL and fail several stages later, in a message about a
    failed install that says nothing about the option that caused it."""
    cases = {
        "@dev": "https://d3mm0r95u5i3hf.cloudfront.net/simple/",
        "@prod": "https://pypi.tabsdata.com/simple/",
        "https://mine.example/simple/": "https://mine.example/simple/",
        "": "",
        # namespace NAME on the dev index, what tdd pypi push --at NAME publishes
        "@dev:tucu": "https://d3mm0r95u5i3hf.cloudfront.net/tucu/",
        "@dev:": "https://d3mm0r95u5i3hf.cloudfront.net/simple/",
    }
    for given, want in cases.items():
        done = _engine(resource_folder, "common_resolve_uv_index", given)
        assert done.returncode == 0, (given, done.stderr)
        assert done.stdout == want, (given, done.stdout)

    done = _engine(resource_folder, "common_resolve_uv_index", "@staging")
    assert done.returncode == 1
    assert "unknown --uv-index marker: @staging" in done.stderr
    assert "@dev, @dev:NAME, @prod, or a URL" in done.stderr
    for bad in ("@dev:files", "@dev:Tucu", "@dev:a/b", "@prod:tucu"):
        assert _engine(resource_folder, "common_resolve_uv_index", bad).returncode == 1


def test_every_script_resolves_the_uv_index_before_it_uses_it():
    """The marker must never reach uv, the tabsdata.yaml or tdkserver: each
    script resolves once, right after parsing, so everything downstream -- the
    banner included -- sees the URL. Each also says in its help what the two
    markers stand for."""
    for script in smoke.scripts_dir().glob("smoke-*.sh"):
        text = script.read_text()
        if "--uv-index" not in text:
            continue
        lines = text.splitlines()
        resolved = next(
            i for i, line in enumerate(lines) if "common_resolve_uv_index" in line
        )
        uses = [
            i
            for i, line in enumerate(lines)
            if "$UV_INDEX_URI" in line and "common_resolve_uv_index" not in line
        ]
        assert uses, script.name
        assert resolved < min(uses), (script.name, resolved, min(uses))
        assert "@dev for the development index" in text, script.name
        assert "@dev:NAME" in text, script.name
        assert "https://d3mm0r95u5i3hf.cloudfront.net/simple/" in text, script.name
        assert "@prod" in text and "https://pypi.tabsdata.com/simple/" in text, (
            script.name
        )


def test_each_script_holds_its_own_local_ports():
    """The ports a run holds on the machine it is launched from are the one
    thing two runs can collide on, and they do run side by side. One block per
    script: km 10000, eks 11000, aks 12000, gke 13000. The apiserver's port
    inside the cluster is not per script -- it clashes with nothing there, and
    moving it would smoke a port nobody deploys with."""
    import re

    want = {"km": "10000", "eks": "11000", "aks": "12000", "gke": "13000"}
    seen = {}
    for path in sorted(smoke.scripts_dir().glob("smoke-*.sh")):
        which = path.stem.split("-", 1)[1]
        text = path.read_text()
        # km names its base port `PORT`; the cluster scripts keep `PORT` for the
        # apiserver's in-cluster port and forward from `FORWARD_PORT`.
        var = "PORT" if which == "km" else "FORWARD_PORT"
        found = re.search(rf'^{var}="(\d+)"', text, re.MULTILINE)
        assert found, (path.name, var)
        seen[which] = found.group(1)
        # the page names its own default and the whole scheme, so the
        # answer to "which port will this take" is on the page in front
        # of whoever is reading it
        assert "km 10000, eks 11000, aks 12000, gke 13000" in text, path.name
        assert "never fight over it" in text, path.name
    assert seen == want
    assert len(set(seen.values())) == len(seen), seen


def test_km_puts_the_index_back_for_the_pods_to_inherit():
    """`tdkserver quickstart --uv-index URL` takes the URL, writes it into the
    instance's tabsdata.yaml and then hands the pods nothing: the pymanager pod
    reports `UV_INDEX = <unset>` and resolves against PyPI alone, so a version
    only on that index cannot be installed and quickstart dies in
    `ins-pymanager` (2.0.0, 2.0.1, 2.1.0). kminus runs its pods as local
    processes, so they inherit the script's environment -- setting the pair
    there is what reaches them, and it has to come after the unset that just
    cleared them.

    Only km: the cluster scripts' pods run in a real cluster and inherit
    nothing from the machine the script was launched on."""
    text = (smoke.scripts_dir() / "smoke-km.sh").read_text()
    lines = text.splitlines()

    unset = next(i for i, ln in enumerate(lines) if "tdd env unset --py-idx" in ln)
    crypto = next(i for i, ln in enumerate(lines) if "tdd env set --crypto" in ln)
    put_back = next(
        i for i, ln in enumerate(lines) if 'tdd env set --py-idx "$UV_INDEX_URI"' in ln
    )
    # after the unset that cleared them, and after set-crypto, so the stage
    # sits where the run's own environment has settled
    assert unset < crypto < put_back, (unset, crypto, put_back)

    # only when there is an index to put back, in the stage list and in the body
    assert (
        '[ -n "$UV_INDEX_URI" ] && STAGE_NAMES[${#STAGE_NAMES[@]}]="set-pypi"' in text
    )
    guard = next(
        i
        for i, ln in enumerate(lines)
        if ln.strip() == 'if [ -n "$UV_INDEX_URI" ]; then'
    )
    assert guard < put_back
    assert "common_stage set-pypi" in text

    # --py-idx is the pair tdkserver meant to set: UV_INDEX and the strategy
    env_sh = smoke.scripts_dir().parent / "unix" / "env.sh"
    if env_sh.is_file():  # same wheel only in a checkout
        assert "UV_INDEX_STRATEGY" in env_sh.read_text()

    # and it says so on screen, the way the psycopg2 workaround does: the stage
    # passes and a yellow remark says what was done and why
    remark = next(ln for ln in lines if "common_remark" in ln and "tdkserver" in ln)
    assert "workaround:" in remark and "does not reach the pods" in remark
    # and the reason is written down where the next reader will be
    assert "UV_INDEX = <unset>" in text and "ins-pymanager" in text
    for version in ("2.0.0", "2.0.1", "2.1.0"):
        assert version in text, version


def test_every_tdk_and_xp_call_runs_on_the_run_s_own_profile():
    """A tdk login is per account unless a profile names it, so a smoke run in
    one shell used to log another shell's work out. Every `tdd tdk` and every
    `tdd xp` that reaches tdk carries --profile, which defaults to the run's
    own sm_NAME -- like every other name the run makes -- and can be given."""
    import re

    for path in sorted(smoke.scripts_dir().glob("smoke-*.sh")):
        text = path.read_text()
        code = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
        assert '--profile) PROFILE="$2"; shift 2 ;;' in text, path.name
        assert 'PROFILE="${PROFILE:-$BASE}"' in text, path.name
        assert "--profile NAME" in text.split("\nHELP\n", 1)[0], path.name
        tdk = [ln for ln in code if re.search(r"\btdd tdk\b(?!server)", ln)]
        assert tdk, path.name
        for ln in tdk:
            # after the verb: tdk has no --profile on its root group, only on
            # each command, and `tdk --profile P login` is refused
            assert re.search(r'tdd tdk [a-z]+ --profile "?\$PROFILE"? ', ln), (
                path.name,
                ln,
            )
        xp = [ln for ln in code if "tdd xp one-shot" in ln and "common_run" in ln]
        assert xp, path.name
        for ln in xp:
            assert '--profile "$PROFILE"' in ln, (path.name, ln)
