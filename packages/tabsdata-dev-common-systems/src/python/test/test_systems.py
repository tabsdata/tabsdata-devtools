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
    for verb in (constants.V_DELETE_DATA, constants.V_DELETE_MODEL):
        assert verb in dispatch._discover(constants.DOM_TOOL)
        assert verb in dispatch.LATCH_VERBS and verb in dispatch._MODEL_VERBS


def test_domain_sf_speaks_the_domain_family():
    assert dispatch._family(constants.DOM_SF_TOOL) == constants.DOM_TOOL
    assert dispatch._discover(constants.DOM_SF_TOOL) == dispatch._discover(
        constants.DOM_TOOL
    )


def test_top_help_lists_verbs_in_both_shapes():
    text, fields = dispatch.top_help(constants.SYS_TOOL)
    assert "create" in text and any(c["name"] == "create" for c in fields["commands"])


def test_fetching_from_1password_is_not_a_system_verb():
    """`crypto-key` and `secrets` moved to `tdd _1p fetch` (2026-09-28): they
    touch no store and no backend, and cost `tdd env` the systems env."""
    text, fields = dispatch.top_help(constants.SYS_TOOL)
    verbs = {c["name"] for c in fields["commands"]}
    assert not {"crypto-key", "secrets"} & verbs
    assert "crypto-key" not in text
    assert not {"crypto-key", "secrets"} & set(dispatch._COMMON[constants.SYS_TOOL])


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


def test_the_crypto_key_is_one_variable_and_one_minimum_everywhere():
    import pathlib

    from tabsdata_dev.common.core import secrets as core_secrets
    from tabsdata_dev.common.systems import crypto

    repo = pathlib.Path(__file__).resolve().parents[5]
    env_sh = (repo / "packages/tabsdata-dev-shell/scripts/unix/env.sh").read_text()
    # what `_1p fetch` reads and checks is what the crypto module opens with
    assert constants.ENV_CRYPTO_KEY == crypto.ENV_VAR == core_secrets.CRYPTO_KEY_ENV
    assert crypto.MIN_SECRET_LEN == core_secrets.CRYPTO_KEY_MIN_LEN
    # `tdd env set --crypto --value` checks the length the crypto module enforces
    assert f"_TDD_CRYPTO_MIN={crypto.MIN_SECRET_LEN}" in env_sh
    # no variable of the environment chooses the vault
    assert not hasattr(constants, "ENV_EMPLOYEE_VAULT")
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
    "awspostgres": {
        "SSLMODE",
        "SERVER_CA_CERT_PEM",
        "AWS_SERVER_CA_CERT_PEM_URL",
        "AWS_ACCOUNT_ID",
        "AWS_REGION",
        "AWS_DB_INSTANCE",
    },
    "gcppostgres": {
        "SSLMODE",
        "SERVER_CA_CERT_PEM",
        "GCP_PROJECT",
        "GCP_REGION",
        "GCP_INSTANCE_ID",
    },
    "azpostgres": {
        "SSLMODE",
        "SERVER_CA_CERT_PEM",
        "AZ_SERVER_CA_CERT_PEM_URL",
        "AZ_SERVER_NAME",
        "AZ_REGION",
    },
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
    # One posture for the three: verify the chain, skip the name. A Cloud SQL
    # leaf has no IP SAN at all, and while an RDS or Azure leaf does name its
    # host, an instance reached at any other address would fail verify-full for
    # a reason that has nothing to do with trust.
    assert aws.ssl_mode == gcp.ssl_mode == az.ssl_mode == "verify-ca"
    # Where the root comes from is the difference: Cloud SQL signs each instance
    # with a CA of its own, so the certificate is stored; the other two publish
    # theirs, so a URL is stored and the root is fetched from it.
    assert not gcp.ca_url_key
    assert aws.ca_url_key == "AWS_SERVER_CA_CERT_PEM_URL"
    assert az.ca_url_key == "AZ_SERVER_CA_CERT_PEM_URL"
    for backend in (aws, az):
        assert backend.ca_url_default.startswith("https://")
        # and the URL is in the descriptor, so `info` says what this system trusts
        assert backend.ca_url_key in _plan(backend.slug)


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


def test_config_describes_every_verb_the_tool_has():
    """`config --show` and the file it writes are only as good as the options
    they know about, and ten of `system`'s seventeen verbs were invisible to
    them: a verb handled in `dispatch` builds its parser inline, so there was
    nothing for `config` to read without running the verb.

    Each of those now has a builder the handler and `config` share, which is
    what keeps the two from drifting -- the alternative, a second list of
    options kept by hand, is the thing this repo already refuses elsewhere.
    """
    from tabsdata_dev.common.systems import dispatch, main as family

    for tool in (constants.SYS_TOOL, constants.DOM_TOOL):
        doc = family.config_doc(tool)
        _, fields = dispatch.top_help(tool)
        verbs = {c["name"] for c in fields["commands"]} - {"config"}
        # `types` takes nothing but --format/--verbose, which the shared table
        # above already holds; everything else describes itself
        assert verbs - set(doc.actions) == {constants.V_TYPES}, tool
        # and no verb repeats what the shared table says
        for verb, options in doc.actions.items():
            if verb:
                assert not {"format", "verbose"} & set(options), f"{tool} {verb}"

    # the defaults are the real ones, not placeholders -- this is the point of
    # reading the parser rather than keeping a list
    system = family.config_doc(constants.SYS_TOOL)
    assert "1p-set" not in system.actions  # `tdd _1p set` since 2026-09-28


def test_a_domain_owner_is_given_the_schema_its_tables_go_in():
    """Creating a database owned by a role does not let that role put a table in
    it. Since PostgreSQL 15 `public` belongs to `pg_database_owner` -- implicitly
    the database's owner, which is why a stock server appears to need nothing --
    but Azure Flexible Server ships a template where it belongs to
    `azure_pg_admin` and everyone else gets USAGE alone. So every one of the five
    says it outright, on a connection to the new database rather than the
    maintenance one, which is the part `create_domain_sql` cannot express.
    """
    for slug in POSTGRES_FAMILY:
        backend = systems.get(slug)
        assert backend.own_public_schema_sql("d1") == [
            'ALTER SCHEMA public OWNER TO "d1"'
        ], slug

        ran: list[tuple[str, list[str]]] = []
        backend._run_admin = lambda admin, sql: ran.append((admin.db, sql))  # noqa: SLF001
        try:
            backend._do_create(backend._admin(_plan(slug)), "d1", "d1", "pw")  # noqa: SLF001
        finally:
            del backend._run_admin
        # the domain SQL on the maintenance database, then the schema on the new
        # one -- a database that does not exist yet cannot be connected to --
        # and, for CDC, the domain's replication slot, also from inside it
        slot = [("d1", ["SELECT pg_create_logical_replication_slot('d1', 'wal2json')"])]
        assert len(ran) == 2 + (slug == "postgrescdc"), slug
        assert ran[0][0] != "d1" and 'CREATE DATABASE "d1"' in " ".join(ran[0][1])
        assert ran[1] == ("d1", ['ALTER SCHEMA public OWNER TO "d1"']), slug
        assert ran[2:] == (slot if slug == "postgrescdc" else []), slug


def test_a_published_root_is_fetched_once_and_reaches_every_connection(monkeypatch):
    """RDS and Azure sign with roots their provider publishes and rotates, so the
    descriptor keeps the URL and never a copy: a copy is the one thing that goes
    stale without anyone touching it. It is fetched once per run and written to a
    temporary file for the length of each connection -- the admin ones and the
    loader's alike, since a domain's model, data and change sets go over exactly
    the TLS its system was created with."""
    from urllib.parse import parse_qs, urlsplit

    from tabsdata_dev.common.systems.systems._common import managed_postgres as mp

    pem = "-----BEGIN CERTIFICATE-----\nMIIBpublished\n-----END CERTIFICATE-----\n"

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return pem.encode()

    fetched: list[str] = []

    def fake_urlopen(url, timeout=0):
        fetched.append(url)
        return _Response()

    monkeypatch.setattr(mp.urllib.request, "urlopen", fake_urlopen)
    mp._CA_DOWNLOADS.clear()

    for slug in ("awspostgres", "azpostgres"):
        backend = systems.get(slug)
        url = backend.ca_url_default
        meta = _plan(slug, SSLMODE="verify-ca", **{backend.ca_url_key: url})
        # what is kept is where the root comes from, not the root
        assert meta[backend.ca_url_key] == url and not meta["SERVER_CA_CERT_PEM"]

        # the domain inherits both, so it needs no back-ref to the system
        dom = backend.domain_meta(meta, "d1", "secret")
        assert dom[backend.ca_url_key] == url and dom["SSLMODE"] == "verify-ca"

        # an admin connection gets a real file, for as long as it is connecting
        admin = backend._admin(dom)
        assert admin.ca_pem == pem and admin.sslmode == "verify-ca"
        with backend._ca_file(admin) as connectable:
            written = pathlib.Path(connectable.sslrootcert)
            assert written.read_text() == pem
        assert not written.exists()

        # and so does the loader, on the mode the system was created with
        with backend.data_plane_uri(dom) as uri:
            params = parse_qs(urlsplit(uri).query)
            assert params["sslmode"] == ["verify-ca"], params
            written = pathlib.Path(params["sslrootcert"][0])
            assert written.read_text() == pem
        assert not written.exists()
        # never in a recorded URI: that path belongs to one machine and one run
        assert "sslrootcert" not in "".join(
            v for k, v in dom.items() if k.endswith("URI")
        )

    # once per URL for the whole run, however many connections wanted it
    assert sorted(fetched) == sorted(
        {systems.get(s).ca_url_default for s in ("awspostgres", "azpostgres")}
    )

    # a certificate handed in directly still wins, and asks for no download
    fetched.clear()
    direct = _plan("awspostgres", SSLMODE="verify-ca", SERVER_CA_CERT_PEM=pem)
    assert direct["SERVER_CA_CERT_PEM"] == pem and not fetched


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

    # The two that publish a root refuse only when told not to use it: with the
    # URL they default to, a verifying mode has somewhere to get one.
    with pytest.raises(TdxError) as az_missing:
        _plan(
            "azpostgres",
            SSLMODE="verify-full",
            AZ_SERVER_NAME="k8sdb",
            AZ_SERVER_CA_CERT_PEM_URL="",
        )
    assert "k8sdb" in str(az_missing.value) and "learn.microsoft.com" in str(
        az_missing.value
    )
    with pytest.raises(TdxError) as aws_missing:
        _plan("awspostgres", SSLMODE="verify-ca", AWS_SERVER_CA_CERT_PEM_URL="")
    assert "truststore.pki.rds.amazonaws.com" in str(aws_missing.value)

    with pytest.raises(TdxError) as no_root:
        _plan("gcppostgres", SSLMODE="verify-ca")
    assert "--sslmode require" in str(no_root.value)
    for slug in MANAGED:
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

    # The two that publish a root carry the URL instead: a copy of the bundle
    # would freeze in the vault while the provider rotates on its own clock.
    aws_ids = [f["id"] for f in onepassword.item(systems.get("awspostgres"))["fields"]]
    assert not [i for i in aws_ids if i.startswith("server_ca_cert")]
    assert "aws_server_ca_cert_pem_url" in aws_ids
    assert {"aws_account_id", "aws_region", "aws_db_instance"} <= set(aws_ids)

    az_ids = [f["id"] for f in onepassword.item(systems.get("azpostgres"))["fields"]]
    assert not [i for i in az_ids if i.startswith("server_ca_cert")]
    assert {"az_server_ca_cert_pem_url", "az_server_name", "az_region"} <= set(az_ids)

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


def test_a_generated_template_is_what_1p_set_may_file_untouched():
    """`tdd _1p set` reduces an item to what a create may carry; a template
    this tool generates is already exactly that."""
    from tabsdata_dev.common.core import secrets_1p
    from tabsdata_dev.common.systems import onepassword, systems as _s

    item = onepassword.item(_s.get("gcppostgres"))
    assert secrets_1p.for_upload(item) == item


def test_db_failure_collects_what_the_server_said():
    """psycopg2 hands back everything the server sent -- SQLSTATE plus the DETAIL,
    HINT and the schema/table/constraint it names -- and none of it reaches the
    one line the terminal prints. This is the block the log gets instead."""
    from tabsdata_dev.common.systems.diagnostics import db_failure

    class Diag:
        severity = "ERROR"
        message_primary = 'duplicate key value violates unique constraint "t_pkey"'
        message_detail = "Key (id)=(1) already exists."
        message_hint = None
        schema_name = "public"
        table_name = "t"
        constraint_name = "t_pkey"

    class Orig(Exception):
        pgcode = "23505"
        diag = Diag()

    class Wrapped(Exception):
        orig = Orig("duplicate key value violates unique constraint")

    text = db_failure(
        Wrapped(),
        statement="INSERT INTO t VALUES (1)",
        url="postgresql+psycopg2://u:s3cret@h:5432/d?sslmode=verify-ca",
        label="a duplicate key",
    )
    assert "sqlstate: 23505" in text
    assert "detail: Key (id)=(1) already exists." in text
    assert "constraint: t_pkey" in text
    assert "statement: INSERT INTO t VALUES (1)" in text
    assert "while: a duplicate key" in text
    # the target belongs in the log; the credential does not
    assert "s3cret" not in text
    assert "sslmode=verify-ca" in text


def test_db_failure_never_raises_on_a_driver_it_does_not_know():
    """It runs while a command is already failing: an exception here would
    replace the failure it was trying to explain."""
    from tabsdata_dev.common.systems.diagnostics import db_failure, redact_url

    class Awkward(Exception):
        @property
        def diag(self):
            raise RuntimeError("no diagnostics for you")

    assert db_failure(Awkward("plain")).strip()
    assert redact_url("not-a-url") == "not-a-url"
    assert "***" in redact_url("postgresql://u:p@h/d")


def test_a_managed_domain_can_grant_the_cross_project_marker_onward():
    """tabsdata's dbmanager connects as the domain's own user, not as an
    administrator, and its schemas' `across_projects` policies are granted TO one
    cluster-global role. Only a holder of ADMIN on that role may grant it onward,
    so `db upgrade` refuses with "a database administrator has to run ..." -- and
    on a managed instance we are that administrator. The marker is created once
    per server and handed to each domain WITH ADMIN OPTION."""
    from tabsdata_dev.common.systems.systems._common.managed_postgres import (
        ACROSS_PROJECTS_ROLE,
    )

    for slug in ("awspostgres", "azpostgres", "gcppostgres"):
        backend = systems.get(slug)
        sql = backend.create_domain_sql("d1", "d1", "pw")
        ensure = [s for s in sql if "CREATE ROLE" in s and ACROSS_PROJECTS_ROLE in s]
        assert ensure, slug
        # once per server, so a second domain must not trip over the first
        assert "IF NOT EXISTS" in ensure[0], slug
        assert f'GRANT "{ACROSS_PROJECTS_ROLE}" TO "d1" WITH ADMIN OPTION' in sql, slug
        # a driver placeholder would eat a literal % in any of them
        assert not [s for s in sql if "%" in s], slug


def test_destroying_a_domain_leaves_the_shared_marker_alone():
    """Destroy drops the per-schema roles tabsdata created under the domain, and
    it finds them by ADMIN membership. The domain holds ADMIN on the server-wide
    marker too, and dropping that would take every other domain's row-level
    security with it -- so the roles are matched by the domain's own name, which
    is what actually says a role belongs to it."""
    from tabsdata_dev.common.systems.systems._common.managed_postgres import (
        ACROSS_PROJECTS_ROLE,
    )

    for slug in ("awspostgres", "azpostgres", "gcppostgres"):
        sql = systems.get(slug).delete_domain_sql("d1")
        drops = [s for s in sql if "DROP ROLE" in s]
        assert drops, slug
        assert "starts_with(g.rolname, 'd1')" in drops[0], slug
        assert ACROSS_PROJECTS_ROLE not in " ".join(sql), slug
        assert not [s for s in sql if "%" in s], slug


def test_db2cdc_claims_every_cd_table_before_registering_and_names_the_owner(
    tmp_path, monkeypatch
):
    """A CD table is the domain's own (ASN.TD_<tag of the schema>__<TABLE>), so
    what can hold one is a leftover: this domain's earlier install, or a
    registration left under this schema's name. asnclp's own refusal comes one
    table in, after the schema is installed, and names a table and no cause.
    The claim runs first, for all tables: a holder whose source table is gone
    is an orphan and is reclaimed; a live one is refused by its schema and by
    the store's name for it, with the command that frees it."""
    import pytest

    from tabsdata_dev.common.systems import descriptor, store
    from tabsdata_dev.common.systems.errors import TdxError
    from tabsdata_dev.common.systems.systems.db2cdc.backend import Db2Cdc

    monkeypatch.setenv("_TDD_CRYPTO_KEY", "a-test-secret-long-enough")
    dom = tmp_path / "domain"
    dom.mkdir()
    monkeypatch.setattr(store, "domain_dir", lambda dir_opt=None: dom)
    descriptor.write_domain(
        dom / "old_kept",
        "db2cdc",
        "old_kept",
        sys_name="cdc",
        external_name="XP_OLD",
        meta={"DB": "XP_OLD", "SYS_DOCKER_CONTAINER_NAME": "tdd_db2cdc"},
    )
    (dom / "stray").write_text("not a descriptor\n")

    b = Db2Cdc()
    P = b.staging_prefix("XP_NEW")  # this domain's CD table prefix
    calls: list[tuple] = []
    owners: dict[str, str] = {}  # CD table -> schema holding it (IBMSNAP_REGISTER)
    existing: set[str] = set()  # SCHEMA.TABLE in syscat: source and CD tables

    def scalar(container, sql):
        s = " ".join(sql.split())
        if "min(cd_table)" in s:  # the CD table a registration records
            sch = s.split("source_owner = '")[1].split("'")[0]
            tab = s.split("source_table = '")[1].split("'")[0]
            return next(
                (
                    cd
                    for cd, o in owners.items()
                    if o == sch and cd.endswith("__" + tab)
                ),
                "",
            )
        if "ibmsnap_register where cd_owner" in s:
            cd = s.split("cd_table = '")[1].split("'")[0]
            return owners.get(cd, "")
        if "syscat.tables where tabschema" in s:
            sch = s.split("tabschema = '")[1].split("'")[0]
            tab = s.split("tabname = '")[1].split("'")[0]
            return "1" if f"{sch}.{tab}" in existing else "0"
        raise AssertionError(s)

    monkeypatch.setattr(b, "_clp_scalar", scalar)
    monkeypatch.setattr(
        b, "_container_and_schema", lambda meta: ("tdd_db2cdc", "XP_NEW")
    )
    monkeypatch.setattr(
        b, "_list_schema_tables", lambda c, s: ["DEPARTMENTS", "EMPLOYEES"]
    )
    monkeypatch.setattr(
        b, "_register_table", lambda c, s, t: calls.append(("register", s, t))
    )
    monkeypatch.setattr(
        b, "_send_capstop", lambda c, s, t: calls.append(("capstop", s, t))
    )
    stuck: set[str] = set()  # CD tables whose drop fails

    def clp(container, sql, ignore_failure=False):
        s = " ".join(sql.split())
        calls.append(("sql", s))
        if s.startswith("drop table ASN."):
            cd = s.split("drop table ASN.")[1]
            if cd not in stuck:
                existing.discard(f"ASN.{cd}")

    monkeypatch.setattr(b, "_clp", clp)

    # nothing holds the names: both tables register
    b.after_install_schema({}, "employees")
    assert calls == [
        ("register", "XP_NEW", "DEPARTMENTS"),
        ("register", "XP_NEW", "EMPLOYEES"),
    ]

    # a live domain holds them: refused by name before anything is registered
    calls.clear()
    owners.update({P + "DEPARTMENTS": "XP_OLD", P + "EMPLOYEES": "XP_OLD"})
    existing.update({"XP_OLD.DEPARTMENTS", "XP_OLD.EMPLOYEES"})
    with pytest.raises(TdxError) as caught:
        b.after_install_schema({}, "employees")
    msg = str(caught.value)
    assert f"ASN.{P}DEPARTMENTS" in msg and f"ASN.{P}EMPLOYEES" in msg
    assert "schema XP_OLD -- domain 'old_kept'" in msg and "tdd_db2cdc" in msg
    assert "tdd domain destroy --domain old_kept" in msg
    assert calls == []

    # the owner's source tables are gone: orphans, reclaimed, then registration goes on
    existing.clear()
    b.after_install_schema({}, "employees")
    kinds = [c[0] for c in calls]
    assert kinds.count("capstop") == 2 and kinds.count("register") == 2
    assert kinds.index("register") > max(
        i for i, k in enumerate(kinds) if k == "capstop"
    )
    sqls = [c[1] for c in calls if c[0] == "sql"]
    assert any(
        "delete from ASN.ibmsnap_register where source_owner = 'XP_OLD' and source_table = 'DEPARTMENTS'"
        in s
        for s in sqls
    )
    assert any(f"drop trigger ASN.LM_{P}EMPLOYEES" in s for s in sqls)
    assert any(f"drop table ASN.{P}DEPARTMENTS" in s for s in sqls)
    assert not any("data capture none" in s for s in sqls), "no source table to alter"

    # a live owner this store has no descriptor for: refused, and says so
    calls.clear()
    owners.pop(P + "EMPLOYEES")
    owners[P + "DEPARTMENTS"] = "XP_GHOST"
    existing.add("XP_GHOST.DEPARTMENTS")
    with pytest.raises(TdxError) as caught:
        b.after_install_schema({}, "employees")
    assert "schema XP_GHOST -- no domain in this store has that schema" in str(
        caught.value
    )
    assert "by hand" in str(caught.value) and calls == []

    # a CD table no registration holds -- a removal whose drop failed took the
    # rows and left the table, which is what asnclp refuses on: reclaimed
    calls.clear()
    owners.clear()
    existing.clear()
    existing.add("ASN." + P + "EMPLOYEES")
    b.after_install_schema({}, "employees")
    sqls = [c[1] for c in calls if c[0] == "sql"]
    assert f"drop trigger ASN.LM_{P}EMPLOYEES" in sqls
    assert f"drop table ASN.{P}EMPLOYEES" in sqls
    assert "ASN." + P + "EMPLOYEES" not in existing
    assert [c for c in calls if c[0] == "register"] == [
        ("register", "XP_NEW", "DEPARTMENTS"),
        ("register", "XP_NEW", "EMPLOYEES"),
    ]
    assert not [c for c in calls if c[0] == "capstop"], "no registration to stop"

    # and a drop that does not take is an error by name, never a silent orphan
    calls.clear()
    existing.add("ASN." + P + "EMPLOYEES")
    stuck.add(P + "EMPLOYEES")
    with pytest.raises(TdxError, match=f"ASN.{P}EMPLOYEES could not be dropped"):
        b.after_install_schema({}, "employees")
    assert not [c for c in calls if c[0] == "register"]

    # the model installed again over this domain's own registrations (a
    # recreate under the same name): asnclp refuses a table already registered
    # (ASN1703E reason 4), so each is removed and registered afresh
    calls.clear()
    stuck.clear()
    existing.clear()
    owners.update({P + "DEPARTMENTS": "XP_NEW", P + "EMPLOYEES": "XP_NEW"})
    b.after_install_schema({}, "employees")
    kinds = [c[0] for c in calls]
    assert kinds.count("capstop") == 2 and kinds.count("register") == 2
    assert kinds.index("register") > max(
        i for i, k in enumerate(kinds) if k == "capstop"
    )
    assert f"drop table ASN.{P}EMPLOYEES" in [c[1] for c in calls if c[0] == "sql"]


def test_db2cdc_deregisters_before_a_forced_recreate_drops_the_tables(monkeypatch):
    """`create --force` drops the schema, `create-model --force` its tables;
    the registrations are in ASN and outlive both, so each forced path
    deregisters first -- while the tables still exist, since CAPSTOP names
    them -- and only then hands over to the drop."""
    from tabsdata_dev.common.systems.systems._common.sql import SqlContainerBackend
    from tabsdata_dev.common.systems.systems.db2cdc.backend import Db2Cdc

    b = Db2Cdc()
    order: list[str] = []
    monkeypatch.setattr(b, "_deregister_schema", lambda meta: order.append("dereg"))
    monkeypatch.setattr(
        SqlContainerBackend,
        "provision_domain",
        lambda self, s, e, d, force=False: order.append(f"provision force={force}"),
    )
    monkeypatch.setattr(
        SqlContainerBackend,
        "install_schema",
        lambda self, m, model, force=False: order.append(f"install force={force}"),
    )
    b.provision_domain({}, "d", {}, force=True)
    b.install_schema({}, "employees", force=True)
    assert order == ["dereg", "provision force=True", "dereg", "install force=True"]
    order.clear()
    b.provision_domain({}, "d", {})
    b.install_schema({}, "employees")
    assert order == ["provision force=False", "install force=False"]


@pytest.fixture
def small_store(tmp_path, monkeypatch):
    """A tdd dir holding two container-free systems, dev1 and fs1, and a batch
    runner that records what it would have started instead of starting it."""
    from tabsdata_dev.common.core import batch as core_batch
    from tabsdata_dev.common.systems import main

    monkeypatch.chdir(tmp_path)  # an fs root is relative to the cwd
    monkeypatch.setenv("TDD_DIR", str(tmp_path / "tdd"))
    monkeypatch.setenv("_TDD_CRYPTO_KEY", "a-key-for-the-test-only")
    monkeypatch.delenv("_TDD_TOOL", raising=False)
    for slug, name in (("dev", "dev1"), ("fs", "fs1")):
        rc = main.run(
            constants.SYS_TOOL,
            [constants.V_CREATE, "--type", slug, "--sys", name, "--format", "json"],
        )
        assert rc == 0, (slug, name)
    started: list[list[str]] = []

    def execute(label, tasks, spawn, out, **kwargs):
        started.extend(step for task in tasks for step in task.steps)
        return 0

    monkeypatch.setattr(core_batch, "execute", execute)
    return started


def _run_json(capsys, tool, *argv):
    from tabsdata_dev.common.systems import main

    capsys.readouterr()
    rc = main.run(tool, [*argv, "--format", "json"])
    events = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("{")
    ]
    return rc, events


def test_a_batch_refuses_an_option_no_child_takes_before_starting_any(
    small_store, capsys
):
    """`destroy --sys a,b --yes` started every child, and each one failed on
    `--yes` -- the parent only peeks at its selector and forwards the rest.
    The parent now parses each child's argv with that child's own parser
    first, so the batch is one error and nothing runs."""
    rc, events = _run_json(
        capsys, constants.SYS_TOOL, constants.V_STATUS, "--sys", "dev1,fs1", "--yes"
    )
    assert rc == 1 and small_store == []
    error = [e for e in events if e["event"] == "error"][0]
    assert "unrecognized arguments: --yes" in error["message"]

    rc, _ = _run_json(
        capsys,
        constants.SYS_TOOL,
        constants.V_CREATE,
        "--type",
        "dev,fs",
        "--sys-prefix",
        "zz",
        "--bogus",
    )
    assert rc == 1 and small_store == []


def test_a_valid_batch_starts_and_a_missing_target_is_left_to_its_child(
    small_store, capsys
):
    """What the check cannot judge it does not block: a target not in the
    store has no type to build a parser from, so its child reports it, per
    target, as before -- and the targets that exist still run."""
    rc, _ = _run_json(
        capsys, constants.SYS_TOOL, constants.V_STATUS, "--sys", "dev1,fs1,ghost"
    )
    assert rc == 0
    assert [step[2] for step in small_store] == ["dev1", "fs1", "ghost"]


def test_delete_data_empties_the_model_and_delete_model_forgets_it(
    tmp_path, monkeypatch
):
    """delete-data re-installs the schema (force) and leaves the descriptor as
    create-model does; delete-model hands the backend uninstall_schema and leaves
    the domain with no model. Both refuse a domain that has none."""
    import argparse

    from tabsdata_dev.common.core import render
    from tabsdata_dev.common.systems import cli, console, descriptor
    from tabsdata_dev.common.systems.systems._common.commands import (
        dom_delete_data,
        dom_delete_model,
    )

    console.bind(render.Renderer(constants.DOM_TOOL))
    monkeypatch.setenv("_TDD_CRYPTO_KEY", "a-test-secret-long-enough")
    path = tmp_path / "d1"
    descriptor.write_domain(
        path, "postgres", "d1", sys_name="pg", external_name="d1", meta={"DB": "d1"}
    )
    model = "world"
    descriptor.set_model(path, model, datagen.entities_of(model))
    descriptor.record_data(path, "2", {e: 10 for e in datagen.entities_of(model)})

    calls: list[tuple] = []

    class Fake:
        def install_schema(self, meta, m, *, force=False):
            calls.append(("install", m, force))

        def uninstall_schema(self, meta, m):
            calls.append(("uninstall", m))

    def ctx(verb):
        return cli.Context(
            tool=constants.DOM_TOOL,
            verb=verb,
            slug="postgres",
            system=Fake(),  # type: ignore[arg-type]
            args=argparse.Namespace(),
            name="d1",
            info=descriptor.load(path),
            path=path,
            store_dir=tmp_path,
        )

    assert dom_delete_data.run(ctx(constants.V_DELETE_DATA)) == 0
    info = descriptor.load(path)
    assert calls == [("install", model, True)]
    assert info.model == model and info.data is None and info.seed == 0
    assert set(info.entities.values()) == {0}

    assert dom_delete_model.run(ctx(constants.V_DELETE_MODEL)) == 0
    info = descriptor.load(path)
    assert calls[-1] == ("uninstall", model)
    assert info.model is None and info.data is None and info.entities == {}

    for mod, verb in (
        (dom_delete_data, constants.V_DELETE_DATA),
        (dom_delete_model, constants.V_DELETE_MODEL),
    ):
        with pytest.raises(TdxError, match="no model"):
            mod.run(ctx(verb))


def test_every_backend_with_models_can_uninstall_them():
    """delete-model is gated on supports_models, so each such backend must
    implement uninstall_schema (the Protocol alone would let one slip)."""
    for slug in systems.all_slugs():
        cls = systems.get_class(slug)
        if cls.supports_models:
            assert callable(getattr(cls, "uninstall_schema", None)), slug


def test_mix_passes_delete_a_distinct_row_each_and_update_only_live_ones():
    """100 `modify-data --ops Mix --sets 5 --seed AUTO` passes over employees
    at xs, the live CDC suite's churn. The old walk offset the seed against the
    CURRENT row count; a Mix pass adds a row and a seed, which cancelled, and
    every pass deleted the same employee. Bounded by the SEEDED counts, each
    delete takes a row nothing touched before, no update lands on a deleted
    row, and once the seeded rows run out no delete is planned -- or reported."""
    from tabsdata_dev.common.systems.datagen import ChangeSpec, OpKind, OpSelector

    model = datagen.load_model("employees")
    seeded = {"employees": 100, "departments": 9}
    alive = {("emp_no", 10001 + i) for i in range(100)}
    deleted: list = []
    for seed in range(1, 101):
        spec = ChangeSpec(
            entities=[e.table for e in model.entities],
            ops=OpSelector.MIX,
            sets=5,
            rows_per_entity={e.table: e.rows_per_set for e in model.entities},
            seed=seed,
            insert_base=seed * datagen.FIXED_SEED_INSERT_STRIDE,
        )
        for txn in datagen.plan(model, spec, seeded):
            for ch in txn:
                if ch.table != "employees":
                    continue
                if ch.kind is OpKind.INSERT:
                    alive.add(("emp_no", ch.row["emp_no"]))
                    continue
                key = next(iter(ch.where.items()))
                assert key in alive, (seed, ch.kind, key)
                if ch.kind is OpKind.DELETE:
                    alive.discard(key)
                    deleted.append(key)
    assert len(deleted) == len(set(deleted)) == 99  # seeds 1..99; then exhausted


def test_dry_run_touches_nothing_and_emit_ops_appends_the_plan(tmp_path, monkeypatch):
    """`--dry-run` plans what create-data / modify-data / sentinel-data would
    do and applies none of it: the backend is never called and the descriptor
    keeps its seed and counts, so AUTO repeats the same plan, and create-data
    needs no --force on a domain that already has data. Alone it writes no
    file; `--emit-ops` APPENDS the plan, each line naming its run."""
    import argparse

    from tabsdata_dev.common.core import render
    from tabsdata_dev.common.systems import cli, console, descriptor
    from tabsdata_dev.common.systems.systems._common.commands import (
        dom_create_data,
        dom_modify_data,
        dom_sentinel_data,
    )

    console.bind(render.Renderer(constants.DOM_TOOL))
    monkeypatch.setenv("_TDD_CRYPTO_KEY", "a-test-secret-long-enough")
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "d1"
    descriptor.write_domain(
        path, "postgres", "d1", sys_name="pg", external_name="d1", meta={"DB": "d1"}
    )
    model = "employees"
    descriptor.set_model(path, model, datagen.entities_of(model))
    descriptor.record_data(path, "1", {"employees": 100, "departments": 9})
    before = path.read_bytes()

    class Untouchable:
        def __getattr__(self, name):
            raise AssertionError(f"dry run reached the system: {name}")

    def run(mod, verb, dest, **opts):
        args = argparse.Namespace(dry_run=True, emit_ops=dest and str(dest), **opts)
        return mod.run(
            cli.Context(
                tool=constants.DOM_TOOL,
                verb=verb,
                slug="postgres",
                system=Untouchable(),  # type: ignore[arg-type]
                args=args,
                name="d1",
                info=descriptor.load(path),
                path=path,
                store_dir=tmp_path,
            )
        )

    def lines(dest):
        return [json.loads(x) for x in dest.read_text().splitlines()]

    run_keys = {"ts", "domain", "verb", "dry_run", "txn", "op", "entity"}
    load = dict(size=1, force=False)
    assert run(dom_create_data, constants.V_CREATE_DATA, None, **load) == 0
    assert list(tmp_path.glob("*.jsonl")) == []  # a dry run alone writes nothing

    initial = tmp_path / "out" / "initial.jsonl"
    assert run(dom_create_data, constants.V_CREATE_DATA, initial, **load) == 0
    rows = lines(initial)
    assert rows and {r["op"] for r in rows} == {"insert"}
    assert {r["txn"] for r in rows} == {0} and {r["domain"] for r in rows} == {"d1"}
    assert {r["verb"] for r in rows} == {constants.V_CREATE_DATA}
    assert all(r["dry_run"] is True for r in rows)
    assert all(set(r) == run_keys | {"row"} for r in rows)

    opts = dict(entity="ALL", sets=3, ops="Mix", seed="AUTO")
    trail = tmp_path / "trail.jsonl"
    assert run(dom_modify_data, constants.V_MODIFY_DATA, trail, **opts) == 0
    first = lines(trail)
    assert run(dom_modify_data, constants.V_MODIFY_DATA, trail, **opts) == 0
    both = lines(trail)
    assert len(both) == 2 * len(first)  # appended, not replaced

    def untimed(rs):
        return [{k: v for k, v in r.items() if k != "ts"} for r in rs]

    assert untimed(both[len(first) :]) == untimed(first)  # AUTO did not advance
    assert {r["seed"] for r in first} == {1}
    assert [r["txn"] for r in first] == sorted(r["txn"] for r in first)
    by_op = {r["op"]: r for r in first}
    assert set(by_op) == {"insert", "update", "delete"}
    assert set(by_op["update"]) == run_keys | {"seed", "key", "set"}
    assert set(by_op["delete"]) == run_keys | {"seed", "key"}

    assert run(dom_sentinel_data, constants.V_SENTINEL_DATA, trail, key="k1") == 0
    last = lines(trail)[-1]
    assert last["verb"] == constants.V_SENTINEL_DATA and last["dry_run"] is True
    assert last["row"]["sentinel_key"] == "k1"
    assert path.read_bytes() == before


def test_every_model_carries_an_empty_sentinel_in_every_ddl():
    """xp_sentinel is in every generated model and every DDL of it, and nothing
    but sentinel-data writes it: no model builds it and no Entity declares it,
    so create-data leaves it empty and modify-data never picks it."""
    import random

    from tabsdata_dev.common.systems.systems._common.sql import SqlContainerBackend

    sentinel = datagen.SENTINEL_ENTITY
    for model in datagen.list_models():
        assert sentinel in datagen.entities_of(model), model
        obj = datagen.load_model(model)
        assert sentinel not in {e.table for e in obj.entities}, model
        tables = obj.build_initial(
            random.Random(datagen.INITIAL_SEED), datagen.BASE_SIZE
        )
        assert sentinel not in {t.name for t in tables}, model
    checked = 0
    for slug in systems.all_slugs():
        backend = systems.get(slug)
        if not isinstance(backend, SqlContainerBackend) or not backend.supports_models:
            continue
        for model in datagen.list_models():
            if not any(backend._ddl_dir(model).glob("*.ddl")):
                continue  # not a DDL model here (redpanda, or a missing dialect)
            ddl = backend.ddl_text(model)
            assert f"CREATE TABLE {sentinel} (" in ddl, (slug, model)
            assert "sentinel_key" in ddl and "sentinel_ts" in ddl, (slug, model)
            checked += 1
    assert checked >= 79


def test_sentinel_data_writes_one_stamped_row_and_create_data_keeps_its_count(
    tmp_path, monkeypatch
):
    """sentinel-data needs only the model: one INSERT of the key at the current
    UTC second, through apply_changes, counted in the descriptor. A first
    create-data leaves that count alone (it drops nothing); a reload zeroes it."""
    import argparse
    import contextlib
    from datetime import datetime, timezone

    from tabsdata_dev.common.core import render
    from tabsdata_dev.common.systems import cli, console, descriptor
    from tabsdata_dev.common.systems.systems._common.commands import (
        dom_create_data,
        dom_sentinel_data,
    )

    console.bind(render.Renderer(constants.DOM_TOOL))
    monkeypatch.setenv("_TDD_CRYPTO_KEY", "a-test-secret-long-enough")
    path = tmp_path / "d1"
    descriptor.write_domain(
        path, "postgres", "d1", sys_name="pg", external_name="d1", meta={"DB": "d1"}
    )
    applied: list = []
    labels: list = []

    class Fake:
        @contextlib.contextmanager
        def data_plane_uri(self, meta):
            yield "fake://"

        def apply_changes(self, uri, txns, before, *, label="modify-data"):
            labels.append(label)
            applied.extend(txns)
            new = dict(before)
            for table, delta in datagen.net_row_deltas(txns).items():
                new[table] = new.get(table, 0) + delta
            return new

        def install_schema(self, meta, model, *, force=False):
            pass

        def load_tables(self, uri, tables):
            return {t.name: len(t.rows) for t in tables}

    def run(mod, verb, **opts):
        return mod.run(
            cli.Context(
                tool=constants.DOM_TOOL,
                verb=verb,
                slug="postgres",
                system=Fake(),  # type: ignore[arg-type]
                args=argparse.Namespace(**opts),
                name="d1",
                info=descriptor.load(path),
                path=path,
                store_dir=tmp_path,
            )
        )

    with pytest.raises(TdxError, match="no model"):
        run(dom_sentinel_data, constants.V_SENTINEL_DATA, key="k1")
    descriptor.set_model(path, "world", datagen.entities_of("world"))

    before = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    trail = tmp_path / "trail.jsonl"
    live = dict(dry_run=False, emit_ops=str(trail))
    assert run(dom_sentinel_data, constants.V_SENTINEL_DATA, key="k1", **live) == 0
    [[change]] = applied
    assert labels == [constants.V_SENTINEL_DATA]  # a failure names this verb
    assert change.kind is datagen.OpKind.INSERT
    assert change.table == datagen.SENTINEL_ENTITY
    assert change.row["sentinel_key"] == "k1"
    ts = change.row["sentinel_ts"]
    assert ts.tzinfo is None and ts.microsecond == 0 and ts >= before
    assert datagen.render_sql(change).startswith(
        "INSERT INTO xp_sentinel (sentinel_key,sentinel_ts) VALUES ('k1','"
    )
    assert descriptor.load(path).entities[datagen.SENTINEL_ENTITY] == 1

    [line] = [json.loads(x) for x in trail.read_text().splitlines()]
    assert line["dry_run"] is False and line["row"]["sentinel_key"] == "k1"
    load = dict(size=1, force=False, **live)
    assert run(dom_create_data, constants.V_CREATE_DATA, **load) == 0
    assert descriptor.load(path).entities[datagen.SENTINEL_ENTITY] == 1
    assert run(dom_create_data, constants.V_CREATE_DATA, **{**load, "force": True}) == 0
    assert descriptor.load(path).entities[datagen.SENTINEL_ENTITY] == 0
    loads = [json.loads(x) for x in trail.read_text().splitlines()][1:]
    assert {r["verb"] for r in loads} == {constants.V_CREATE_DATA}
    assert {r["dry_run"] for r in loads} == {False}
    assert loads and len(loads) % 2 == 0  # both loads, the same rows each

    with pytest.raises(TdxError, match="1 to 255"):
        run(dom_sentinel_data, constants.V_SENTINEL_DATA, key="x" * 256, **live)
    assert len(trail.read_text().splitlines()) == 1 + len(loads)  # failed: nothing


def test_a_postgrescdc_domains_slot_is_named_after_its_database():
    """Slot names are lowercase letters, digits and `_`, at most 63: the
    database name folded into that, and a long one cut and hashed."""
    import re

    from tabsdata_dev.common.systems.systems.postgrescdc.backend import (
        replication_slot_of,
    )

    db = "xp_tucu_20260926T152121_55821d_postgrescdc_employees_xs"
    assert replication_slot_of(db) == db.lower()
    long_a, long_b = "d" * 70 + "_a", "d" * 70 + "_b"
    for name in (long_a, long_b, "Mixed-Case.db"):
        assert re.fullmatch(r"[a-z0-9_]{1,63}", replication_slot_of(name)), name
    assert replication_slot_of(long_a) != replication_slot_of(long_b)
    assert replication_slot_of("Mixed-Case.db") == "mixed_case_db"


def _cdc_backend(monkeypatch, slots: dict[str, list[str]]):
    """A postgrescdc backend whose admin SQL is recorded, not run; `slots` is the
    server's pg_replication_slots, database -> slot names."""
    import re

    from tabsdata_dev.common.systems.systems.postgrescdc.backend import Postgrescdc

    backend = Postgrescdc()
    ran: list[tuple[str, str]] = []

    def run_admin(admin, statements):
        for st in statements:
            ran.append((admin.db, st))
            m = re.search(r"pg_drop_replication_slot\('([^']+)'\)", st)
            if m:
                for names in slots.values():
                    if m.group(1) in names:
                        names.remove(m.group(1))

    def query_admin(admin, query):
        db = re.search(r"database = '([^']+)'", query).group(1)
        only = re.search(r"slot_name = '([^']+)'", query)
        names = slots.get(db, [])
        return [n for n in names if not only or n == only.group(1)]

    monkeypatch.setattr(backend, "_run_admin", run_admin)
    monkeypatch.setattr(backend, "_query_admin", query_admin)
    return backend, ran


def test_a_postgrescdc_domain_creates_its_slot_and_destroy_drops_it_first(
    monkeypatch,
):
    """Create makes the slot from a connection to the new database, and records
    it in the meta; destroy ends its reader and drops it before the database,
    which Postgres would otherwise refuse to drop."""
    from tabsdata_dev.common.systems.systems._common.sql import Admin
    from tabsdata_dev.common.systems.systems.postgrescdc.backend import (
        REPLICATION_SLOT_KEY,
    )

    admin = Admin(host="h", port="1", user="postgres", password="p", db="postgres")
    slots: dict[str, list[str]] = {}
    backend, ran = _cdc_backend(monkeypatch, slots)
    backend._do_create(admin, "Dom_A", "u", "pw")
    assert ran[-1] == (
        "Dom_A",
        "SELECT pg_create_logical_replication_slot('dom_a', 'wal2json')",
    )
    meta = backend.domain_meta({"PORT": "1"}, "Dom_A", "pw")
    assert meta[REPLICATION_SLOT_KEY] == "dom_a"

    slots["Dom_A"] = ["dom_a"]
    ran.clear()
    backend._do_delete(admin, "Dom_A")
    statements = [st for _, st in ran]
    terminate = next(i for i, s in enumerate(statements) if "pg_terminate_backend" in s)
    drop_slot = statements.index("SELECT pg_drop_replication_slot('dom_a')")
    drop_db = next(i for i, s in enumerate(statements) if s.startswith("DROP DATABASE"))
    assert terminate < drop_slot < drop_db
    assert all(db in (None, "postgres") for db, _ in ran)  # from the admin database


def test_postgrescdc_destroy_drops_every_slot_on_the_database_first(monkeypatch):
    """A slot a stream created for itself goes with the domain, like its own:
    a logical slot belongs to one database, and Postgres would not drop the
    database while any is on it. Each reader is ended before its drop; a slot
    on another database is not touched."""
    from tabsdata_dev.common.systems.systems._common.sql import Admin

    admin = Admin(host="h", port="1", user="postgres", password="p", db="postgres")
    slots = {"dom_a": ["dom_a", "td_cdc_initial_load"], "dom_b": ["dom_b"]}
    backend, ran = _cdc_backend(monkeypatch, slots)
    backend._do_delete(admin, "dom_a")
    assert slots == {"dom_a": [], "dom_b": ["dom_b"]}
    statements = [st for _, st in ran]
    drops = [i for i, st in enumerate(statements) if "pg_drop_replication_slot" in st]
    ends = [i for i, st in enumerate(statements) if "pg_terminate_backend" in st]
    drop_db = next(
        i for i, st in enumerate(statements) if st.startswith("DROP DATABASE")
    )
    assert (
        len(drops) == 2
        and all(e < d for e, d in zip(ends, drops))
        and max(drops) < drop_db
    )


def test_a_manifest_entrys_emit_ops_goes_to_its_create_data_step():
    """`emit-ops` is create-data's, not a create flag: the one key the entry
    passes to a later step rather than to `create`."""
    entry = {
        "name": "d1",
        "sys": "pg",
        "model": "world",
        "size": 1,
        "emit-ops": "/w/ops.jsonl",
    }
    create, model, data = dispatch._entry_steps(constants.DOM_TOOL, entry, force=False)
    assert constants.OPT_EMIT_OPS not in create and "--emit-ops" not in model
    assert data[:5] == [constants.V_CREATE_DATA, "--domain", "d1", "--size", "1"]
    assert data[5:7] == [constants.OPT_EMIT_OPS, "/w/ops.jsonl"]
    *_, plain = dispatch._entry_steps(
        constants.DOM_TOOL, {**entry, "emit-ops": None}, force=False
    )
    assert constants.OPT_EMIT_OPS not in plain


def test_db2cdc_cd_tables_are_each_domains_own_and_recorded_in_its_meta():
    """Two domains of one model on one system no longer meet on a CD table:
    each is named by its schema, and the domain says which prefix is its own
    for a function to name its tables by (${D0__CD_TABLE_PREFIX}EMPLOYEES)."""
    import re

    from tabsdata_dev.common.systems.systems.db2cdc.backend import (
        CD_TABLE_PREFIX_KEY,
        Db2Cdc,
    )

    b = Db2Cdc()
    a, c = b.cd_table("XP_A", "employees"), b.cd_table("XP_B", "employees")
    assert a != c and a.endswith("__EMPLOYEES") and a.startswith("ASN.TD_")
    assert re.fullmatch(r"ASN\.TD_[0-9A-F]{8}__EMPLOYEES", a)
    assert b.cd_table("xp_a", "EMPLOYEES") == a  # Db2 folds names to upper case
    meta = b.domain_meta({"PORT": "1"}, "d1", "pw")
    assert meta[CD_TABLE_PREFIX_KEY] + "EMPLOYEES" == b.cd_table(
        b._schema(meta["DB"]), "EMPLOYEES"
    )


def test_db2cdc_removes_the_cd_table_its_registration_records(monkeypatch):
    """A registration made under the old shared naming (ASN.TD_T__<TABLE>) is
    removed by the name IBMSNAP_REGISTER records for it, not by today's."""
    from tabsdata_dev.common.systems.systems.db2cdc.backend import Db2Cdc

    b = Db2Cdc()
    sqls: list[str] = []
    monkeypatch.setattr(
        b,
        "_clp_scalar",
        lambda c, sql: "TD_T__EMPLOYEES" if "min(cd_table)" in sql else "0",
    )
    monkeypatch.setattr(
        b, "_clp", lambda c, sql, ignore_failure=False: sqls.append(sql)
    )
    monkeypatch.setattr(b, "_send_capstop", lambda c, s, t: None)
    b._remove_registration("tdd_db2cdc", "XP_OLD", "EMPLOYEES")
    assert "drop table ASN.TD_T__EMPLOYEES" in sqls
    assert "drop trigger ASN.LM_TD_T__EMPLOYEES" in sqls
