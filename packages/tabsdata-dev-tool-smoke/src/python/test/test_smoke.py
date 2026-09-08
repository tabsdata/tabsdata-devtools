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
