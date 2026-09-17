#
# Copyright 2026 Tabsdata Inc.
#

"""The smoke scripts this package carries, and the tool that exports them.

They are shell, so most of what can be checked without a cluster is checked by
reading them -- which is enough for the contracts that have actually broken: a
required option quietly gaining a default, a value substituted into YAML in a
shape tdkserver refuses, a run writing to the developer's kubeconfig.
"""

from tabsdata_dev.common.core import render
from tabsdata_dev.tool import smoke


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


def test_common_fill_pem_writes_a_yaml_block_scalar():
    """A certificate is many lines, and common_fill_placeholder substitutes text.
    Dropped in raw, a PEM's newlines continue the plain scalar and YAML folds them
    into spaces: the file still parses, and then no certificate ever loads. So the
    whole `key: ${{...}}` line becomes a block scalar indented past its key."""
    import os
    import pathlib as _pathlib
    import subprocess
    import tempfile

    common = smoke.scripts_dir() / "_common.sh"
    pem = "-----BEGIN CERTIFICATE-----\nAAAA\nBBBB\n-----END CERTIFICATE-----"
    placeholder = "${{secret:ca}}"

    def fill(body: str, ph: str, value: str):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _pathlib.Path(tmp) / "db.yaml"
            cfg.write_text(body)
            done = subprocess.run(
                [
                    "bash",
                    "-c",
                    '. "%s"; common_fill_pem "%s" -- \'%s\' "$PEM"' % (common, cfg, ph),
                ],
                capture_output=True,
                text=True,
                env={**os.environ, "PEM": value},
            )
            return done, cfg.read_text()

    body = "postgres:\n    ssl_root_cert_pem: %s\n    port: 5432\n" % placeholder
    done, written = fill(body, placeholder, pem)
    assert done.returncode == 0, done.stderr
    assert written == (
        "postgres:\n"
        "    ssl_root_cert_pem: |\n"
        "      -----BEGIN CERTIFICATE-----\n"
        "      AAAA\n"
        "      BBBB\n"
        "      -----END CERTIFICATE-----\n"
        "    port: 5432\n"
    )
    # a config that only looks filled is the failure worth catching early, so
    # neither an empty value nor an absent placeholder passes quietly
    assert fill(body, placeholder, "")[0].returncode != 0
    assert fill(body, "${{secret:nope}}", pem)[0].returncode != 0


def test_fill_storage_substitutes_yaml_scalars_in_every_cluster_smoke():
    """tdkserver compares the filled config's shape against its template's and
    refuses a value whose shape changed (ResolverError::StructureMismatch). The
    GCS service-account key is itself JSON, so dropped in bare it reads back as a
    flow MAPPING where the template holds a scalar -- a run reached `create`
    before failing on it. Every value goes in as a YAML double-quoted scalar.

    Every cluster script, found the way the context test finds them, rather than
    a list of names here: the trap is the storage fill's, so a new cloud's script
    inherits it the day it is written and not the day someone remembers this."""
    scripts = smoke.scripts_dir()
    cluster = [
        p for p in sorted(scripts.glob("smoke-*.sh")) if "KUBECTL=(" in p.read_text()
    ]
    assert cluster, "no kubectl-using smoke scripts found"
    marker = 'line.replace("${{secret}}", '
    for path in cluster:
        text = path.read_text()
        assert "def scalar(value):" in text, path.name
        assert "import json" in text, path.name
        pieces = text.split(marker)
        assert len(pieces) > 1, path.name
        for tail in pieces[1:]:
            assert tail.startswith("scalar("), (path.name, tail[:40])


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
    assert called("common_fill_pem") < called("common_placeholders_left")


def test_the_help_reads_long_form_first_and_paints_only_terms():
    """Two things a hand-aligned page gets wrong on its own. An option with both
    forms reads long then short, as everywhere else in tdd. And the closing prose
    block -- "The drivers added ...", whose indented line lists three packages --
    is a paragraph, not a term list: painting its first package cyan said it was
    an option."""
    for path in smoke.scripts_dir().glob("smoke-*.sh"):
        text = path.read_text()
        assert "  -f, --force" not in text, path.name
        assert "  -h, --help" not in text, path.name
        assert "  --force, -f" in text and "  --help, -h" in text, path.name

    common = (smoke.scripts_dir() / "_common.sh").read_text()
    engine = common.split("common_help() {", 1)[1].split("\n}\n", 1)[0]
    # a term is only a term inside a section, and a column-1 line ends one
    assert "section = 0" in engine and "section && match(" in engine
    # The awk program is single-quoted by the shell, so an apostrophe anywhere in
    # it -- a comment saying "the paragraph's" was the one that did -- closes the
    # quote early and the rest becomes shell. Extract it the way the shell would
    # and check the tail survived.
    body = engine.split("awk -v required=", 1)[1]
    # up to the NEXT quote, which is where the shell ends it -- not the last one,
    # or a stray apostrophe in the middle would be swallowed and this would pass
    program = body.split("'")[1]
    assert "{ print painted($0) }" in program, "the awk program is cut short"


def test_substitution_is_literal_on_both_sides_and_uses_no_perl(tmp_path):
    """The placeholder holds `${{`, `?` and `:`; the value can be a password, a
    PEM or JSON. Neither may be read as a pattern or as a backreference, which is
    what ruled sed out. perl did that correctly and is still gone: these scripts
    already run python3 for the other two fills, so it was a second interpreter
    buying nothing -- one more thing to have installed, for a script whose whole
    job is checking an install."""
    import subprocess

    engine = smoke.scripts_dir() / "_common.sh"
    cfg = tmp_path / "a.yaml"
    cfg.write_text(
        "key: ${{secret:pw?}}\nother: ${{literal:host}}\n"
        "  UV_INDEX: https://old.example/simple/\n"
    )
    nasty = r"p&ss\1\\word$1/x{}[]*.^"
    subprocess.run(
        [
            "bash",
            "-c",
            f'. "{engine}"\n'
            f"common_fill_placeholder {cfg} -- '${{{{secret:pw?}}}}' \"$1\"\n"
            f"common_fill_placeholder {cfg} -- '${{{{literal:host}}}}' 10.0.0.1\n"
            f'common_set_uv_index {cfg} "https://cdn.example/simple/"',
            "bash",
            nasty,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    written = cfg.read_text().splitlines()
    assert written[0] == f"key: {nasty}", written[0]
    assert written[1] == "other: 10.0.0.1"
    # the rewrite keeps the line's indentation and takes the URL verbatim
    assert written[2] == "  UV_INDEX: https://cdn.example/simple/"

    for path in [engine, *smoke.scripts_dir().glob("smoke-*.sh")]:
        code = [
            ln
            for ln in path.read_text().splitlines()
            if not ln.lstrip().startswith("#")
        ]
        assert not [ln for ln in code if "perl" in ln], path.name


def test_the_failure_report_names_only_what_the_run_actually_built(tmp_path):
    """The report under `left for you to look at` is read at the one moment the
    reader is chasing a failure, so everything in it has to be there. A run that
    dies in an early stage has built no instance and no venv: naming them, with
    cleanup commands for paths that were never written, sends the reader after
    ghosts. The instance and venv are on disk and get asked; the domains are the
    script's own record, appended as each one is created."""
    import os
    import subprocess

    common = smoke.scripts_dir() / "_common.sh"
    home = tmp_path / "home"
    tdd = tmp_path / "tdd"
    venv = tdd / "managed-venvs" / "pyenv" / "sm_foo"
    instance = home / ".tabsdata" / "instances" / "sm_foo"

    def report(domains: str = "") -> list[str]:
        script = (
            '. "%s"\n'
            'TDD_DIR_OPT="%s"; INSTANCE=sm_foo; VENV=sm_foo; VENV_TYPE=pyenv\n'
            'SERVER=127.0.0.1:2457; NAMES_PREFIX=sm_foo; SMOKE_DOMAINS="%s"\n'
            'common_init "%s" 0\n'
            "common_tabsdata_setup_info common_indented\n"
        ) % (common, tdd, domains, tmp_path / "log")
        done = subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            text=True,
            env={**os.environ, "HOME": str(home), "NO_COLOR": "1"},
        )
        assert done.returncode == 0, done.stderr
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
    assert "remove     tdd venv delete --name sm_foo" in lines
    assert not [
        ln for ln in lines if ln.startswith("instance") or ln.startswith("nothing")
    ], lines

    # both, plus a domain the script says it created
    instance.mkdir(parents=True)
    lines = report(domains="sm_foo__gcppostgres")
    assert [ln for ln in lines if ln.startswith("instance   sm_foo -- not running")], (
        lines
    )
    assert [ln for ln in lines if ln.startswith("venv       sm_foo (pyenv)")], lines
    assert [ln for ln in lines if ln.startswith("domain     sm_foo__gcppostgres --")], (
        lines
    )
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
    import os
    import socket
    import subprocess
    import textwrap

    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    record = tmp_path / "record"
    kubectl = fakebin / "kubectl"
    kubectl.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            printf '%s\\n' "$*" > "$RECORD"
            # the last argument is LOCAL:REMOTE; listen on LOCAL, as the real forward would
            exec python3 -c 'import socket, sys, time
            s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", int(sys.argv[1].split(":")[0]))); s.listen(); time.sleep(120)' "${@: -1}"
            """
        )
    )
    kubectl.chmod(0o755)
    common = smoke.scripts_dir() / "_common.sh"
    env = {
        **os.environ,
        "PATH": f"{fakebin}:{os.environ['PATH']}",
        "RECORD": str(record),
        "NO_COLOR": "1",
    }

    def start(local: int, log) -> subprocess.CompletedProcess:
        script = (
            '. "%s"\n'
            'common_init "%s" 0\n'
            'common_stage forward-1 "the forward"\n'
            "common_kubeportforward_start /tmp/cfg sm-x net-apiserver %d 2457; rc=$?\n"
            "common_kubeportforward_stop\n"
            "exit $rc\n"
        ) % (common, log, local)
        return subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True, timeout=90, env=env
        )

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        local = probe.getsockname()[1]
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
        assert 'FORWARD_PORT="2457"' in text, path.name
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


def test_common_set_fn_resources_sizes_the_function_pods_and_only_them(tmp_path):
    """`--td-fn-memory`/`--td-fn-disk` rewrite pods.function.resources in a
    tabsdata.yaml that carries a `resources:` block under every service as well.
    The helper walks the indentation to the function block's own, rewrites the two
    lines in place -- tdkserver compares the filled file's shape to the template's
    -- and fails unless exactly one memory and one disk line changed, because a
    sizing that silently missed would pass that shape check and surface as a pod
    that never schedules."""
    import os
    import subprocess

    common = smoke.scripts_dir() / "_common.sh"
    template = (
        "pods:\n"
        "  global:\n"
        "    env:\n"
        "      UV_INDEX: https://pypi.org/simple/\n"
        "  service:\n"
        "    priority: tabsdata-service\n"
        "    resources:\n"
        '      cpu: "2"\n'
        "      memory: 1Gi\n"
        "      disk: 16Gi\n"
        "    overrides:\n"
        "      srv-apiserver:\n"
        "        resources:\n"
        '          cpu: "2"\n'
        "          memory: 8Gi\n"
        "          disk: 64Gi\n"
        "\n"
        "  function:\n"
        "    priority: tabsdata-function\n"
        "    resources:\n"
        '      cpu: "1"\n'
        "      memory: 16Gi\n"
        "      disk: 64Gi\n"
        "    placement:\n"
        "      selectors: {}\n"
        "      tolerations:\n"
        "        - key: workload\n"
        "          value: batch\n"
        "          effect: NoSchedule\n"
    )

    def run(body: str, memory: str, disk: str):
        cfg = tmp_path / "tabsdata.yaml"
        cfg.write_text(body)
        done = subprocess.run(
            [
                "bash",
                "-c",
                '. "%s"; common_set_fn_resources "%s" "$M" "$D"' % (common, cfg),
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "M": memory, "D": disk},
        )
        return done, cfg.read_text()

    done, written = run(template, "8Gi", "32Gi")
    assert done.returncode == 0, done.stderr
    assert "function pods: memory 8Gi, disk 32Gi" in done.stdout
    # the function block moved, and nothing else did: the service blocks keep
    # their 1Gi/16Gi and 8Gi/64Gi, the cpu and the placement are untouched
    assert written == template.replace(
        "      memory: 16Gi\n      disk: 64Gi\n",
        "      memory: 8Gi\n      disk: 32Gi\n",
    )
    assert written.count("memory: 8Gi") == 2  # ours plus the apiserver override

    # no function block: refused, and the file is left as it was
    headless = template.split("  function:\n", 1)[0]
    done, written = run(headless, "8Gi", "32Gi")
    assert done.returncode != 0
    assert "expected one memory and one disk line" in done.stderr
    assert written == headless

    # two function blocks would be two rewrites: refused too
    function_block = "  function:\n" + template.split("  function:\n", 1)[1]
    done, _ = run(template + function_block, "8Gi", "32Gi")
    assert done.returncode != 0, "a second function block must not pass as one"


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
        call = 'common_run common_set_fn_resources "$CONFIGS/tabsdata.yaml" "$FN_MEMORY" "$FN_DISK"'
        assert call in text, path.name
        assert text.index("common_stage configure") < text.index(call), path.name
        assert text.index(call) < text.index(
            'common_run common_placeholders_left "$CONFIGS"'
        ), path.name
        assert text.index(call) < text.index("tdkserver config check --instance"), (
            path.name
        )


def test_the_forward_is_relaunched_when_kubectl_exits_and_checked_before_a_suite(
    tmp_path,
):
    """A port-forward is one stream through the cluster's tunnel, and the tunnel
    drops on its own (AKS replacing the node that carries its konnectivity agents
    did it on two consecutive days). kubectl does not reconnect, so the start runs
    it under a supervisor that relaunches it whenever it exits, and every xp stage
    opens with an ensure: the port answers, or the supervisor gets a moment, or
    the forward is started afresh. The fake kubectl records each launch and its
    own pid, so the test can kill it the way the tunnel would."""
    import os
    import socket
    import subprocess
    import textwrap

    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    record = tmp_path / "record"
    pidfile = tmp_path / "kubectl.pid"
    kubectl = fakebin / "kubectl"
    kubectl.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            printf '%s\\n' "$*" >> "$RECORD"
            echo $$ > "$PIDFILE"
            exec python3 -c 'import socket, sys, time
            s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", int(sys.argv[1].split(":")[0]))); s.listen(); time.sleep(300)' "${@: -1}"
            """
        )
    )
    kubectl.chmod(0o755)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        local = probe.getsockname()[1]
    common = smoke.scripts_dir() / "_common.sh"
    log = tmp_path / "log"
    script = textwrap.dedent(
        f"""\
        . "{common}"
        common_init "{log}" 0
        common_stage forward-2 "the forward"
        common_kubeportforward_start /tmp/cfg sm-x net-apiserver {local} 2457 || exit 10
        answers() {{ (exec 3<>"/dev/tcp/127.0.0.1/{local}") 2>/dev/null; }}

        # the tunnel drops: kubectl dies; the supervisor must bring it back
        kill "$(cat "$PIDFILE")"
        for i in 1 2 3 4 5 6 7 8 9 10; do answers || break; sleep 0.5; done
        answers && exit 11                       # it must have gone down first
        common_stage xp-1 "a suite"
        common_kubeportforward_ensure || exit 12
        [ "$(cat "$PIDFILE")" != "" ] || exit 13

        # the supervisor itself is gone, and so is its kubectl: ensure starts afresh
        kill -9 "$PORTFORWARD_PID"; kill "$(cat "$PIDFILE")" 2>/dev/null
        for i in 1 2 3 4 5 6 7 8 9 10; do answers || break; sleep 0.5; done
        common_stage xp-2 "another suite"
        common_kubeportforward_ensure || exit 14
        answers || exit 15

        common_kubeportforward_stop
        answers && exit 16                       # nothing left listening
        kill -0 "$(cat "$PIDFILE")" 2>/dev/null && exit 17   # nor a kubectl
        exit 0
        """
    )
    done = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        timeout=120,
        env={
            **os.environ,
            "PATH": f"{fakebin}:{os.environ['PATH']}",
            "RECORD": str(record),
            "PIDFILE": str(pidfile),
            "NO_COLOR": "1",
        },
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
