#
# Copyright 2026 Tabsdata Inc.
#

"""Smoke tests for the shared family: registry, models, constants -- nothing that
needs a driver, a docker daemon or a crypto key."""

import json
import pathlib

import pytest

from tabsdata_dev.common.systems import constants, datagen, dispatch, systems
from tabsdata_dev.common.systems.errors import TdxError


def test_registry_has_every_backend_and_declares_toolsets():
    slugs = systems.all_slugs()
    assert {"mysql", "postgres", "fs", "dev", "salesforce"} <= set(slugs)
    for slug in slugs:
        cls = systems.get_class(slug)
        assert cls.sys_toolset in (
            constants.TOOLSET_SYSTEMS,
            constants.TOOLSET_SALESFORCE,
        )
        assert cls.dom_toolset in (
            constants.TOOLSET_SYSTEMS,
            constants.TOOLSET_SALESFORCE,
        )
    assert systems.get_class("salesforce").dom_toolset == constants.TOOLSET_SALESFORCE


def test_models_ship_with_the_package():
    models = datagen.list_models()
    assert {"world", "sakila", "finance"} <= set(models)
    assert "id" in " ".join(
        datagen.entities_of("world")
    ).lower() or datagen.entities_of("world")


def test_every_verb_has_a_command_module():
    for tool in (constants.SYS_TOOL, constants.DOM_TOOL):
        verbs = dispatch._discover(tool)
        assert constants.V_CREATE in verbs and constants.V_DESTROY in verbs
    assert constants.V_MODIFY_DATA in dispatch._discover(constants.DOM_TOOL)


def test_domain_sf_speaks_the_domain_family():
    assert dispatch._family(constants.DOM_SF_TOOL) == constants.DOM_TOOL
    assert dispatch._discover(constants.DOM_SF_TOOL) == dispatch._discover(
        constants.DOM_TOOL
    )


def test_top_help_lists_verbs_in_both_shapes():
    text, fields = dispatch.top_help(constants.SYS_TOOL)
    assert "create" in text and any(c["name"] == "create" for c in fields["commands"])


def test_crypto_key_is_a_system_verb_that_needs_no_store():
    text, fields = dispatch.top_help(constants.SYS_TOOL)
    assert "crypto-key" in text
    assert constants.V_CRYPTO_KEY in dispatch._COMMON[constants.SYS_TOOL]
    assert constants.V_CRYPTO_KEY not in dispatch._STORE_READING_VERBS


def test_clean_docker_lists_then_refuses_without_yes_and_sweeps_with_it(
    monkeypatch, capsys
):
    """`clean-docker` over a fake daemon: without --yes and no terminal it lists
    the tdd_* containers and refuses; with --yes it stops the running ones and
    removes all, and only the tdd-prefixed names are ever touched."""
    from tabsdata_dev.common.systems import main, shell

    boxes = [
        {"id": "1", "name": "tdd_mysql_a1", "state": "running", "image": "mysql:8"},
        {"id": "2", "name": "tdd_pg-db-1", "state": "exited", "image": "postgres:16"},
    ]
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(shell, "require_docker", lambda: None)
    monkeypatch.setattr(
        shell,
        "list_containers",
        lambda prefix: [b for b in boxes if b["name"].startswith(prefix)],
    )
    monkeypatch.setattr(shell, "docker_stop", lambda name: calls.append(("stop", name)))
    monkeypatch.setattr(
        shell, "docker_rm", lambda name, force=False: calls.append(("rm", name))
    )

    rc = main.run(constants.SYS_TOOL, [constants.V_CLEAN_DOCKER, "--format", "json"])
    events = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("{")
    ]
    assert rc == 1 and calls == []
    err = [e for e in events if e["event"] == "error"][0]
    assert "2 container(s)" in err["message"] and "--yes" in err["message"]

    rc = main.run(
        constants.SYS_TOOL, [constants.V_CLEAN_DOCKER, "-y", "--format", "json"]
    )
    events = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("{")
    ]
    ok = [e for e in events if e["event"] == "ok"][0]
    assert rc == 0
    assert calls == [
        ("stop", "tdd_mysql_a1"),
        ("rm", "tdd_mysql_a1"),
        ("rm", "tdd_pg-db-1"),
    ]
    assert ok["removed"] == ["tdd_mysql_a1", "tdd_pg-db-1"] and ok["failed"] == []


def test_every_system_type_owns_a_disjoint_port_slot_documented_in_docs_ports_md():
    import pathlib

    from tabsdata_dev.common.systems.systems._common.ports import system_port_range

    order = systems.slot_order()
    assert sorted(order) == systems.all_slugs()
    slots = [system_port_range(s) for s in order]
    assert all(hi - lo + 1 == constants.PORTS_PER_SYSTEM for lo, hi in slots)
    assert slots[0][0] == constants.PORT_BASE and slots[-1][1] < constants.PORTS_CEILING
    assert all(a[1] < b[0] for a, b in zip(slots, slots[1:]))  # in order, disjoint
    # the table in docs/ports.md is the contract: a new or moved system must update it
    doc = (
        pathlib.Path(__file__).resolve().parents[5] / "docs" / "ports.md"
    ).read_text()
    for slug, (lo, hi) in zip(order, slots):
        assert f"| `{slug}` | {lo}-{hi} |" in doc, (
            f"docs/ports.md lacks the row for {slug}"
        )


def test_port_range_mixin_walks_its_slot_without_repeating_or_leaving_it():
    import socket

    from tabsdata_dev.common.core.ports import find_free_port
    from tabsdata_dev.common.systems.systems._common.ports import (
        PortRangeMixin,
        system_port_range,
    )

    class Fake(PortRangeMixin):
        slug = "mysql"

    lo, hi = system_port_range("mysql")
    # the slot may be in use for real (a mysql container of this machine sits on
    # its first ports): occupy the first port that is free right now instead
    first = find_free_port((lo, hi), from_start=True)
    busy = socket.socket()
    busy.bind(("", first))
    busy.listen(1)
    try:
        f = Fake()
        got = [f.next_free_port() for _ in range(3)]
        assert first not in got and len(set(got)) == 3
        assert all(first < p <= hi for p in got)  # in the slot, after the busy one
        g = Fake()
        g.use_ports([lo + 50, lo + 51])  # pins are taken as given, then the slot
        assert [g.next_free_port() for _ in range(3)] == [lo + 50, lo + 51, got[0]]
    finally:
        busy.close()


def test_crypto_key_takes_a_literal_vault_default_and_the_shell_agrees_on_the_minimum():
    import pathlib

    from tabsdata_dev.common.systems import crypto

    repo = pathlib.Path(__file__).resolve().parents[5]
    env_sh = (repo / "packages/tabsdata-dev-shell/scripts/unix/env.sh").read_text()
    # `tdd env set --crypto --value` checks the length the crypto module enforces
    assert f"_TDD_CRYPTO_MIN={crypto.MIN_SECRET_LEN}" in env_sh
    # neither side lets a variable of the environment choose the vault
    assert not hasattr(constants, "ENV_EMPLOYEE_VAULT")
    assert constants.DEFAULT_EMPLOYEE_VAULT == "Employee"
    assert f'_TDD_VAULT_CRYPTO="1p:{constants.DEFAULT_EMPLOYEE_VAULT}"' in env_sh
    assert not any(ev.name.startswith("ONE_PASSWORD") for ev in constants.ENV_VARS)
    src = (
        repo
        / "packages/tabsdata-dev-common-systems/src/python/main/tabsdata_dev"
        / "common/systems/dispatch.py"
    ).read_text()
    assert "ONE_PASSWORD" not in src


POSTGRES_FAMILY = (
    "postgres",
    "postgrescdc",
    "awspostgres",
    "gcppostgres",
    "azpostgres",
)
# The block every one of the five records, whatever is behind it.
INFO_BLOCK = (
    "INTERNAL_HOST",
    "EXTERNAL_HOST",
    "PORT",
    "DATABASE",
    "USER",
    "PASSWORD",
    "VERSION",
    "INTERNAL_SQLALCHEMY_URI",
    "EXTERNAL_SQLALCHEMY_URI",
    "INTERNAL_URI",
    "EXTERNAL_URI",
)
# What each adds past it, and nothing else.
FAMILY_EXTRAS = {
    "postgres": {"DOCKER_CONTAINER_NAME", "IMAGE"},
    "postgrescdc": {"DOCKER_CONTAINER_NAME", "IMAGE"},
    "awspostgres": {"SSLMODE", "SERVER_CA_CERT_PEM", "AWS_ACCOUNT_ID", "AWS_REGION"},
    "gcppostgres": {
        "SSLMODE",
        "SERVER_CA_CERT_PEM",
        "GCP_PROJECT",
        "GCP_REGION",
        "GCP_INSTANCE_ID",
    },
    "azpostgres": {"SSLMODE", "SERVER_CA_CERT_PEM", "AZ_SERVER_NAME", "AZ_REGION"},
}
MANAGED = ("awspostgres", "gcppostgres", "azpostgres")

_CONN = {
    "EXTERNAL_HOST": "ext.example",
    "INTERNAL_HOST": "10.0.0.1",
    "PORT": "5432",
    "USER": "postgres",
    "PASSWORD": "p@ss %20 word",
    "SSLMODE": "require",
}


def _plan(slug, **extra):
    return systems.get(slug).plan_system(slug, {**_CONN, **extra})


def test_the_five_postgres_types_record_one_info_block_and_their_own_group():
    """The point of the family: a script that reads a postgres descriptor reads
    the same keys whichever of the five it came from, and the only difference is
    the provider group each adds."""
    for slug in POSTGRES_FAMILY:
        meta = _plan(slug)
        assert set(INFO_BLOCK) <= set(meta), slug
        assert set(meta) - set(INFO_BLOCK) == FAMILY_EXTRAS[slug], slug
    # docker has no certificate and no mode to choose
    for slug in ("postgres", "postgrescdc"):
        assert not {"SSLMODE", "SERVER_CA_CERT_PEM"} & set(_plan(slug))
    # and every one of them can hold a model and its data
    for slug in POSTGRES_FAMILY:
        backend = systems.get(slug)
        assert backend.supports_models and backend.supports_data
        assert backend.supports_changes
        assert "world" in backend.available_models(), slug


def test_both_planes_get_a_uri_pair_and_a_container_answers_on_one_address():
    """A managed instance answers on a public address and a private one, and
    which is usable is the reader's property, not the instance's. A container has
    one address and records it under both names, so all five read alike."""
    gcp = _plan("gcppostgres")
    assert gcp["EXTERNAL_SQLALCHEMY_URI"].startswith(
        "postgresql+psycopg2://postgres:p%40ss%20%2520%20word@ext.example:5432/postgres"
    )
    assert gcp["INTERNAL_URI"] == (
        "postgresql+psycopg2://10.0.0.1:5432/postgres?sslmode=require"
    )
    # the credentials ride on one of each pair only
    assert "p%40ss" not in gcp["EXTERNAL_URI"] + gcp["INTERNAL_URI"]
    # every recorded URI carries the mode the system was created with, and none
    # carries the root cert -- that rides on tdx's own admin connections
    for key in INFO_BLOCK[-4:]:
        assert "sslmode=require" in gcp[key] and "sslrootcert" not in gcp[key]

    pg = _plan("postgres")
    assert pg["INTERNAL_HOST"] == pg["EXTERNAL_HOST"] == "localhost"
    assert pg["INTERNAL_SQLALCHEMY_URI"] == pg["EXTERNAL_SQLALCHEMY_URI"]
    assert "sslmode" not in pg["EXTERNAL_URI"]

    # an instance with no address on a network says so, rather than offering a
    # `postgresql://:5432` somebody could try to connect to
    alone = systems.get("azpostgres").plan_system("a", {**_CONN, "INTERNAL_HOST": ""})
    assert alone["INTERNAL_HOST"] == "" and alone["INTERNAL_SQLALCHEMY_URI"] == ""
    assert alone["INTERNAL_URI"] == "" and alone["EXTERNAL_URI"]


def test_a_domain_carries_the_block_with_its_own_database_and_owner():
    """A domain descriptor is enough on its own -- and for the managed three the
    reader handed one is usually not where tdx ran, so both planes come too."""
    for slug in POSTGRES_FAMILY:
        backend = systems.get(slug)
        sys_meta = {**_plan(slug), "VERSION": "18.4"}
        dom = backend.domain_meta(sys_meta, "d1", "secret")
        assert set(INFO_BLOCK) <= set(dom), slug
        # the block now describes the domain's own database and owner role
        assert dom["DATABASE"] == "d1" and dom["USER"] == "d1"
        assert dom["PASSWORD"] == "secret" and dom["VERSION"] == "18.4"
        # ... with the master kept as the back-ref destroy runs from, and the
        # maintenance database it must connect to (never the domain's own: a
        # database cannot be dropped from a session connected to it)
        assert dom["SYS_ADMIN_USER"] == "postgres"
        assert dom["SYS_DATABASE"] == "postgres"
        assert backend._admin(backend._sys_admin_meta(dom)).db == "postgres"
        for plane in ("INTERNAL", "EXTERNAL"):
            assert dom[f"{plane}_URI"].endswith(
                "/d1" if slug in ("postgres", "postgrescdc") else "/d1?sslmode=require"
            ), slug
        # the provider group comes through: not derivable from a host that may
        # be a bare IP, and a domain command never loads the system descriptor
        assert FAMILY_EXTRAS[slug] - {"IMAGE"} <= set(dom) | {
            "DOCKER_CONTAINER_NAME"
        }, slug
    gcp = systems.get("gcppostgres")
    dom = gcp.domain_meta(
        _plan("gcppostgres", GCP_PROJECT="td-dev", GCP_INSTANCE_ID="k8sdb"),
        "d1",
        "secret",
    )
    assert dom["GCP_PROJECT"] == "td-dev" and dom["GCP_INSTANCE_ID"] == "k8sdb"
    # a URI recorded on a domain claims the mode its system was created with,
    # never the class default (verify-ca here)
    assert dom["SSLMODE"] == "require"
    assert "sslmode=require" in dom["EXTERNAL_SQLALCHEMY_URI"]


def test_the_managed_three_differ_only_where_their_provider_does():
    """Same base, same block; each filters the service roles its own provider
    grants the master. The role filter is the load-bearing part: `purge` drops
    what a listing offers."""
    from tabsdata_dev.common.systems.systems._common.managed_postgres import (
        ManagedPostgres,
    )

    for slug in MANAGED:
        backend = systems.get(slug)
        assert isinstance(backend, ManagedPostgres)
        assert not backend.is_container and backend.supports_purge
        assert backend.docker_images() == []
        assert backend.ddl_from_slug == "postgres"  # a model is the plain one's
        # every env-sourced option reads the backend's own prefix
        env_opts = [o for o in backend.options() if o.default_doc.startswith("env $")]
        assert env_opts and all(
            o.default_doc.startswith(f"env ${backend.env_prefix}__") for o in env_opts
        )
        # only the plane tdx connects on holds a create up
        required = {o.name for o in backend.options() if o.required}
        assert "EXTERNAL_HOST" in required and "INTERNAL_HOST" not in required
        # nor does the provider group: the instance is reached at its host
        provider = {o.name for o in backend.provider_options()}
        assert provider and not provider & required

    aws, gcp, az = (systems.get(s) for s in MANAGED)
    assert "rdsadmin" in aws.system_schemas and "rds_" in aws.role_prefixes
    assert "cloudsqladmin" in gcp.system_schemas and "cloudsql" in gcp.role_prefixes
    assert "azure_sys" in az.system_schemas and "azure_" in az.role_prefixes
    for backend, own, other in (
        (aws, "rds_", "cloudsql"),
        (gcp, "cloudsql", "rds_"),
        (az, "azure_", "cloudsql"),
    ):
        sql = backend.list_schemas_sql()
        assert f"starts_with(r.rolname, '{own}')" in sql
        assert "starts_with(r.rolname, 'pg_')" in sql
        assert other not in sql  # none borrows another's provider names
    # a Cloud SQL leaf has no IP SAN, so verify-full cannot work against one;
    # an RDS or Azure leaf names its host, so the strict mode is the useful one
    assert gcp.ssl_mode == "verify-ca"
    assert aws.ssl_mode == az.ssl_mode == "verify-full"


def test_the_managed_three_store_the_ca_itself_and_give_a_connection_a_file(tmp_path):
    """The descriptor keeps the certificate, not a path into somebody's home
    directory: a path is read at create, the domain inherits the PEM, and every
    connection that needs one gets a file materialized from it."""
    pem = "-----BEGIN CERTIFICATE-----\nMIIBfake\n-----END CERTIFICATE-----\n"
    src = tmp_path / "server-ca.pem"
    src.write_text(pem)
    for slug in ("gcppostgres", "azpostgres"):  # aws downloads a bundle instead
        backend = systems.get(slug)
        # a path is read at create; the PEM is what is stored
        meta = _plan(slug, SERVER_CA_CERT_PATH=str(src))
        assert meta["SERVER_CA_CERT_PEM"] == pem
        # ... and the path is gone: it describes one box, so a descriptor
        # carrying it would offer every other reader a file that is not theirs
        assert "SERVER_CA_CERT_PATH" not in meta
        # the PEM handed over directly reaches the same place
        assert _plan(slug, SERVER_CA_CERT_PEM=pem)["SERVER_CA_CERT_PEM"] == pem

        # the domain inherits it, so it needs no back-ref to the system ...
        dom = backend.domain_meta(meta, "d1", "secret")
        assert dom["SERVER_CA_CERT_PEM"] == pem
        # ... and it never leaks into the URIs a connector is handed
        assert "sslrootcert" not in "".join(
            v for k, v in dom.items() if k.endswith("URI")
        )

        # an admin connection gets a real file, for as long as it is connecting
        admin = backend._admin(dom)
        assert admin.ca_pem == pem and not admin.sslrootcert
        with backend._ca_file(admin) as connectable:
            written = pathlib.Path(connectable.sslrootcert)
            assert written.read_text() == pem
        assert not written.exists() and not written.parent.exists()

        for bad in (
            {"SERVER_CA_CERT_PEM": "not a pem"},
            {"SERVER_CA_CERT_PATH": str(tmp_path / "nope.pem")},
        ):
            with pytest.raises(TdxError):
                _plan(slug, **bad)
        with pytest.raises(TdxError, match="not both"):
            _plan(slug, SERVER_CA_CERT_PEM=pem, SERVER_CA_CERT_PATH=str(src))

    # POSIX quoting, so `eval "$(... --as export)"` reproduces a multiline PEM
    import shlex

    assert shlex.split(f"K={shlex.quote(pem)}")[0] == f"K={pem}"


def test_the_data_plane_gets_the_root_cert_a_verifying_mode_needs(tmp_path):
    """The loader goes through `run_sql_text`, which takes a URI and nothing
    else, while a verifying sslmode needs libpq handed a path -- so the certificate
    is written for the length of the load, and only then."""
    pem = "-----BEGIN CERTIFICATE-----\nMIIBfake\n-----END CERTIFICATE-----\n"
    gcp = systems.get("gcppostgres")
    verifying = _plan("gcppostgres", SSLMODE="verify-ca", SERVER_CA_CERT_PEM=pem)
    dom = gcp.domain_meta(verifying, "d1", "secret")
    with gcp.data_plane_uri(dom) as uri:
        # the external plane -- tdx runs the loader itself, from where tdx is
        assert "ext.example:5432/d1" in uri and "10.0.0.1" not in uri
        written = pathlib.Path(uri.replace("%2F", "/").split("sslrootcert=")[1])
        assert written.read_text() == pem
        # Every parameter exactly once. The recorded URI already carries the
        # mode, so adding it again here makes libpq read the pair as a list and
        # refuse the connection: invalid sslmode value: "('verify-ca',
        # 'verify-ca')" -- a failure that only shows up against a real server
        # with a verifying mode, which is why it is pinned here.
        from urllib.parse import parse_qs, urlsplit

        params = parse_qs(urlsplit(uri).query)
        assert params["sslmode"] == ["verify-ca"], params
        assert len(params["sslrootcert"]) == 1
    assert not written.exists()

    # nothing to write when nothing verifies, and the URI is handed over as it is
    plain = gcp.domain_meta(_plan("gcppostgres"), "d1", "secret")
    with gcp.data_plane_uri(plain) as uri:
        assert uri == plain["EXTERNAL_SQLALCHEMY_URI"] and "sslrootcert" not in uri

    # a container has nothing to set up either
    pg = systems.get("postgres")
    pdom = pg.domain_meta(_plan("postgres"), "d1", "secret")
    with pg.data_plane_uri(pdom) as uri:
        assert uri == pdom["EXTERNAL_SQLALCHEMY_URI"]


def test_a_verifying_sslmode_without_a_root_is_refused_with_the_way_to_get_one():
    """libpq reports a missing root as a bare 'certificate verify failed' long
    after create, and it is not guessable from that -- so create refuses first,
    and each provider names where its certificate comes from."""
    with pytest.raises(TdxError) as gcp_missing:
        _plan("gcppostgres", SSLMODE="verify-ca")
    assert "gcloud sql instances describe INSTANCE" in str(gcp_missing.value)
    assert "--project" not in str(gcp_missing.value)  # gcloud's own default is better
    with pytest.raises(TdxError) as named:
        _plan(
            "gcppostgres",
            SSLMODE="verify-ca",
            GCP_INSTANCE_ID="k8sdb",
            GCP_PROJECT="td-dev",
        )
    assert "describe k8sdb --project td-dev" in str(named.value)

    with pytest.raises(TdxError) as az_missing:
        _plan("azpostgres", SSLMODE="verify-full", AZ_SERVER_NAME="k8sdb")
    assert "k8sdb" in str(az_missing.value) and "learn.microsoft.com" in str(
        az_missing.value
    )

    for slug in ("gcppostgres", "azpostgres"):
        with pytest.raises(TdxError) as no_root:
            _plan(slug, SSLMODE="verify-ca")
        assert "--sslmode require" in str(no_root.value)
        with pytest.raises(TdxError, match="unknown sslmode"):
            _plan(slug, SSLMODE="verify-most")
        # require encrypts without verifying: no certificate to supply
        assert _plan(slug, SSLMODE="require")


def test_every_type_makes_a_1password_item_that_reads_back_as_its_own_env_vars():
    """The round-trip is the whole point: an item's title becomes the `<PREFIX>`
    and each field id the `<KEY>` of the variables `secrets` produces, and those
    are what a type's env-sourced options read. Normalised by the very function
    the reader uses, so the two halves cannot drift apart."""
    from tabsdata_dev.common.core.secrets_1p import _norm as reader_norm
    from tabsdata_dev.common.systems import onepassword, options as opts

    for slug in systems.all_slugs():
        backend = systems.get(slug)
        item = onepassword.item(backend)
        # what `secrets_1p.fetch` would name every field of this item
        produced = {
            f"{reader_norm(item['title'])}__{reader_norm(f['id'])}"
            for f in item["fields"]
            if f["id"] != onepassword.EXPIRES_FIELD
        }
        # a container type declares no env prefix at all (nothing of its create
        # comes from the environment); the item falls back to the slug
        prefix = getattr(backend, "env_prefix", "") or slug.upper()
        skipped = set(getattr(backend, "onepassword_skip", ()))
        for opt in backend.options():
            if opt.source != opts.ENV:
                continue
            if opt.name in skipped:  # deliberately not vault material
                assert f"{prefix}__{opt.name}" not in produced
                continue
            # exactly the variable options.resolve() reads for this option
            assert f"{prefix}__{opt.name}" in produced, (
                f"{slug}: no 1p field yields ${prefix}__{opt.name}"
            )


def test_1p_item_conceals_secrets_and_takes_its_category_from_its_fields():
    from tabsdata_dev.common.systems import onepassword, options

    # The category follows the fields: a type whose options are 1Password's own
    # host/port/username/password shape gets the DATABASE item (and its
    # database_type menu, filled from the dialect -- the human would have to
    # guess 1Password's vocabulary). No type has that shape today: the five
    # postgres types name two hosts, and `external_host` is not `hostname`.
    assert not [
        s
        for s in systems.all_slugs()
        if onepassword.category_for(systems.get(s)) == onepassword.CATEGORY_DATABASE
    ]
    fake = systems.get("awspostgres")

    class _NativeShape(type(fake)):  # the shape the DATABASE branch is for
        def options(self):
            return tuple(o for o in super().options() if o.name != "EXTERNAL_HOST") + (
                options.Option("HOSTNAME", "hostname", options.ENV, "env $X__HOSTNAME"),
                options.Option("USERNAME", "username", options.ENV, "env $X__USERNAME"),
            )

    native = onepassword.item(_NativeShape())
    assert native["category"] == onepassword.CATEGORY_DATABASE
    assert native["fields"][0] == {
        "id": "database_type",
        "label": "type",
        "type": "MENU",
        "value": "postgresql",
    }
    assert not any(f["id"] == onepassword.EXPIRES_FIELD for f in native["fields"])

    # everything else is a credential, with the expires field those carry --
    # which the reader skips, so it never becomes a variable
    s3 = onepassword.item(systems.get("s3"))
    assert s3["category"] == onepassword.CATEGORY_API
    assert s3["fields"][-1]["type"] == "DATE"

    for slug in systems.all_slugs():
        backend = systems.get(slug)
        by_id = {f["id"]: f for f in onepassword.item(backend)["fields"]}
        for opt in onepassword.vault_options(backend):
            want = "CONCEALED" if opt.secret else "STRING"
            assert by_id[opt.name.lower()]["type"] == want, f"{slug}.{opt.name}"


def test_info_renders_a_descriptor_as_a_1password_item_holding_its_values():
    """`info --format 1p` is the same item with what the system actually has in it;
    `--prefix` names the title, since the title is what the prefix comes from."""
    from tabsdata_dev.common.systems import descriptor

    info = descriptor.SystemInfo(
        system="s3",
        name="s3",
        started="now",
        meta={"BUCKET": "b", "REGION": "r", "ACCESS_KEY": "ak", "SECRET_KEY": "sk"},
    )
    item = json.loads(descriptor.info_render(info, constants.FMT_1P))
    values = {f["id"]: f["value"] for f in item["fields"]}
    assert values["bucket"] == "b" and values["access_key"] == "ak"
    # an option with no value in the descriptor stays a placeholder to fill in
    assert values["sys_path"] == "?"
    assert json.loads(descriptor.info_render(info, constants.FMT_1P, "S3Dev"))["title"]


def test_1p_template_covers_every_type_and_says_so_when_none_is_named(capsys):
    from tabsdata_dev.common.systems import main

    rc = main.run(
        constants.SYS_TOOL,
        [constants.V_1P_TEMPLATE, constants.OPT_TYPE, "ALL"],
    )
    out = capsys.readouterr().out
    assert rc == 0
    items = json.loads(out[out.index("[") : out.rindex("]") + 1])
    assert len(items) == len(systems.all_slugs())

    # a template is about a type, and there is no current one to assume
    rc = main.run(constants.SYS_TOOL, [constants.V_1P_TEMPLATE])
    said = capsys.readouterr()
    assert rc == 1 and constants.OPT_TYPE in said.out + said.err

    # the item is the only shape it speaks, so there is no --format to ask for
    rc = main.run(
        constants.SYS_TOOL,
        [constants.V_1P_TEMPLATE, constants.OPT_TYPE, "s3", "--format", "1p"],
    )
    said = capsys.readouterr()
    assert rc == 1 and "--format" in said.out + said.err


def test_the_managed_items_carry_the_certificate_but_not_the_path_to_it():
    """The whole point of the item for these types: a Cloud SQL or Azure instance
    is signed by a root libpq will not find on its own, so the certificate has to
    travel with the credentials -- and RDS's is a download, so it does not."""
    from tabsdata_dev.common.systems import onepassword

    gcp = systems.get("gcppostgres")
    item = onepassword.item(gcp)
    ids = [f["id"] for f in item["fields"]]
    # 1Password's DATABASE item has exactly one built-in `hostname`, and these
    # instances answer on two named planes, so it is a credential item instead
    assert item["category"] == onepassword.CATEGORY_API
    assert {"external_host", "internal_host", "database", "user"} <= set(ids)
    assert "hostname" not in ids and "username" not in ids
    assert "server_ca_cert_pem" in ids
    # which instance this is, in Google's terms -- not how it is reached
    assert {"gcp_project", "gcp_region", "gcp_instance_id"} <= set(ids)
    # the path to a local copy is one machine's, and create refuses being told
    # the same thing twice -- an item carrying both would break every create
    assert "server_ca_cert_path" not in ids

    # RDS fetches a current bundle every run, so neither belongs in a vault
    aws_ids = [f["id"] for f in onepassword.item(systems.get("awspostgres"))["fields"]]
    assert not [i for i in aws_ids if i.startswith("server_ca_cert")]
    assert {"aws_account_id", "aws_region"} <= set(aws_ids)

    az_ids = [f["id"] for f in onepassword.item(systems.get("azpostgres"))["fields"]]
    assert {"az_server_name", "az_region", "server_ca_cert_pem"} <= set(az_ids)

    # a computed default is written out, never left as a placeholder: read back
    # from the vault, "?" would be refused as an sslmode -- and `database` is
    # `postgres` on every instance nobody renamed
    by_id = {f["id"]: f["value"] for f in item["fields"]}
    assert by_id["sslmode"] == gcp.ssl_mode == "verify-ca"
    assert by_id["database"] == "postgres"
    assert by_id["server_ca_cert_pem"] == "?"

    # and what the vault yields is what create reads
    from tabsdata_dev.common.core.secrets_1p import _norm

    produced = {f"{_norm(item['title'])}__{_norm(i)}" for i in ids}
    assert {
        "GCPPOSTGRES__SERVER_CA_CERT_PEM",
        "GCPPOSTGRES__SSLMODE",
        "GCPPOSTGRES__EXTERNAL_HOST",
        "GCPPOSTGRES__INTERNAL_HOST",
        "GCPPOSTGRES__GCP_PROJECT",
    } <= produced


def test_1p_set_deletes_before_creating_so_a_title_cannot_duplicate(
    tmp_path, monkeypatch, capsys
):
    """`op item create` files a second item under a title that already exists
    rather than replacing the first, and a vault with two `S3` items reads back
    a coin toss -- so a set is a delete followed by a create."""
    from tabsdata_dev.common.core import secrets_1p
    from tabsdata_dev.common.systems import main

    calls: list[list[str]] = []
    sent: dict[str, str] = {}

    def fake_run(argv, **kw):
        calls.append(list(argv))

        class CP:
            returncode = 0
            stdout = ""
            stderr = ""

        cp = CP()
        if argv[0] == "which":
            return cp
        if "get" in argv:
            cp.returncode = 0 if sent.get("exists") else 1
        if "create" in argv:
            # the item is piped in, not written anywhere and not in argv
            sent["stdin"] = kw.get("input", "")
            cp.stdout = '{"id": "abc123"}'
        return cp

    monkeypatch.setattr(secrets_1p.subprocess, "run", fake_run)
    item = {"title": "S3", "category": "API_CREDENTIAL", "fields": [{"id": "bucket"}]}
    entry = tmp_path / "s3.json"
    entry.write_text(json.dumps(item))

    # the item is already filed: delete, then create
    sent["exists"] = True
    rc = main.run(
        constants.SYS_TOOL,
        [
            constants.V_1P_SET,
            constants.OPT_VAULT,
            "dev_xp",
            constants.OPT_ENTRY,
            str(entry),
        ],
    )
    assert rc == 0
    ops = [c[c.index("item") + 1] for c in calls if "item" in c]
    assert ops == ["get", "delete", "create"]
    assert all(c[c.index("--vault") + 1] == "dev_xp" for c in calls if "--vault" in c)
    # what op is handed is the item itself, on stdin: not in argv (which every
    # user on the machine can read) and not written to a file at all
    assert json.loads(sent["stdin"]) == item
    assert not any("--template" in c or "secret" in " ".join(c) for c in calls)
    out = capsys.readouterr().out
    assert "replaced 'S3'" in out and "Recently Deleted" in out

    # nothing filed under that title yet: no delete to do
    calls.clear()
    sent["exists"] = False
    assert (
        main.run(
            constants.SYS_TOOL,
            [
                constants.V_1P_SET,
                constants.OPT_VAULT,
                "dev_xp",
                constants.OPT_ENTRY,
                str(entry),
            ],
        )
        == 0
    )
    assert [c[c.index("item") + 1] for c in calls if "item" in c] == ["get", "create"]
    assert "created 'S3'" in capsys.readouterr().out


def test_1p_set_refuses_anything_that_is_not_an_item_before_it_deletes(tmp_path):
    """The check is here rather than left to op: a refusal after the delete has
    already run is a refusal that has destroyed something."""
    from tabsdata_dev.common.systems import dispatch

    bad = tmp_path / "bad.json"
    bad.write_text('{"title": "S3"}')  # no category, no fields
    with pytest.raises(TdxError, match="category, fields"):
        dispatch._read_entry(str(bad))
    bad.write_text("[]")
    with pytest.raises(TdxError, match="one 1Password item"):
        dispatch._read_entry(str(bad))
    with pytest.raises(TdxError, match="cannot read"):
        dispatch._read_entry(str(tmp_path / "nope.json"))


def test_1p_set_uploads_only_what_a_create_may_carry(tmp_path):
    """A whole `op item get --format=json` can be handed straight back to
    1p-set: read an item, edit a value, file it again. What is dropped is the
    identity of the item it was read *from* -- id, version, vault, timestamps --
    and each field's op:// reference, which 1Password mints from where the field
    ends up, so a copied one points somewhere else."""
    from tabsdata_dev.common.systems import dispatch

    got = {
        "id": "abcd1234",
        "title": "GCPPOSTGRES",
        "version": 3,
        "vault": {"id": "v1", "name": "dev_xp"},
        "category": "DATABASE",
        "last_edited_by": "USER1",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-02-01T00:00:00Z",
        "additional_information": "postgres",
        "fields": [
            {
                "id": "username",
                "type": "STRING",
                "purpose": "USERNAME",
                "label": "username",
                "value": "postgres",
                "reference": "op://dev_xp/GCPPOSTGRES/username",
            }
        ],
    }
    entry = tmp_path / "item.json"
    entry.write_text(json.dumps(got))
    out = dispatch._read_entry(str(entry))

    assert list(out) == ["title", "category", "fields"]
    assert out["title"] == "GCPPOSTGRES" and out["category"] == "DATABASE"
    # the field keeps everything that describes it, and loses only the reference
    assert out["fields"] == [
        {
            "id": "username",
            "type": "STRING",
            "purpose": "USERNAME",
            "label": "username",
            "value": "postgres",
        }
    ]
    # and a template this tool generated passes through untouched
    from tabsdata_dev.common.systems import onepassword, systems as _s

    item = onepassword.item(_s.get("gcppostgres"))
    assert onepassword.for_upload(item) == item
