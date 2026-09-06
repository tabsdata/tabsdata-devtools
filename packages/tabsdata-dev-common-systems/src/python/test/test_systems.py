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
    the tdx2* containers and refuses; with --yes it stops the running ones and
    removes all, and only the tdx2-prefixed names are ever touched."""
    from tabsdata_dev.common.systems import main, shell

    boxes = [
        {"id": "1", "name": "tdx2_mysql_a1", "state": "running", "image": "mysql:8"},
        {"id": "2", "name": "tdx2_pg-db-1", "state": "exited", "image": "postgres:16"},
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
        ("stop", "tdx2_mysql_a1"),
        ("rm", "tdx2_mysql_a1"),
        ("rm", "tdx2_pg-db-1"),
    ]
    assert ok["removed"] == ["tdx2_mysql_a1", "tdx2_pg-db-1"] and ok["failed"] == []


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


def test_managed_postgres_pair_shares_a_base_and_filters_its_own_provider():
    """awspostgres and gcppostgres differ only where the provider does. The role
    filter is the load-bearing part: `purge` drops what a listing offers, and a
    managed instance grants its master service roles of its own."""
    from tabsdata_dev.common.systems.systems._common.managed_postgres import (
        ManagedPostgres,
    )

    aws, gcp = systems.get("awspostgres"), systems.get("gcppostgres")
    for backend in (aws, gcp):
        assert isinstance(backend, ManagedPostgres)
        assert not backend.is_container and backend.supports_purge
        assert not (
            backend.supports_models or backend.supports_data or backend.supports_changes
        )
        assert backend.docker_images() == []
        # every connection option reads the backend's own env prefix
        env_opts = [o for o in backend.options() if o.default_doc.startswith("env $")]
        assert env_opts and all(
            o.default_doc.startswith(f"env ${backend.env_prefix}__") for o in env_opts
        )

    # RDS names an instance by region; Cloud SQL is reached at its host, so
    # there the region is recorded but never holds a create up
    def region(backend):
        return next(o for o in backend.options() if o.name == "REGION")

    assert region(aws).required and not region(gcp).required
    assert "informational" in region(gcp).default_doc

    assert "rdsadmin" in aws.system_schemas and "rds_" in aws.role_prefixes
    assert "cloudsqladmin" in gcp.system_schemas and "cloudsql" in gcp.role_prefixes
    # the master holds cloudsqlsuperuser; without the prefix it lists as a domain
    assert "starts_with(r.rolname, 'cloudsql')" in gcp.list_schemas_sql()
    assert "starts_with(r.rolname, 'rds_')" in aws.list_schemas_sql()
    for backend in (aws, gcp):
        assert "starts_with(r.rolname, 'pg_')" in backend.list_schemas_sql()
    # neither borrows the other's provider names
    assert "cloudsql" not in aws.list_schemas_sql()
    assert "rds_" not in gcp.list_schemas_sql()


def test_managed_postgres_urls_carry_the_mode_and_keep_the_root_cert_to_admin():
    """The root cert rides on tdx's own admin connections only: a descriptor's
    URIs carry the mode alone, since a connector-under-test brings its own root."""
    gcp = systems.get("gcppostgres")
    sys_meta = gcp.plan_system(
        "gcppostgres",
        {
            "HOSTNAME": "10.0.0.1",
            "PORT": "5432",
            "USERNAME": "postgres",
            "PASSWORD": "p@ss %20 word",
            "SSLMODE": "require",
        },
    )
    assert sys_meta["LOCATION"] == "postgresql://10.0.0.1:5432"

    admin_url = gcp._admin_url(gcp._admin(sys_meta))
    assert "sslmode=require" in admin_url
    # the password is percent-encoded, so a literal '%20' survives as itself
    assert "p%40ss%20%2520%20word" in admin_url

    dom = gcp.domain_meta(sys_meta, "d1", "secret")
    assert dom["SSLMODE"] == "require" and dom["REGION"] == ""
    # a domain records which instance its database lives in: not derivable from
    # a host that may be a bare IP
    assert dom["INSTANCE_ID"] == ""
    for key in ("SQLALCHEMY_URI", "URI"):
        assert "sslmode=require" in dom[key] and "sslrootcert" not in dom[key]
    # a container's keys have no meaning on an externally-owned instance
    assert not {"IMAGE", "SYS_CONTAINER", "SYS_CONTAINER_ID"} & set(dom)


def test_gcppostgres_stores_the_ca_itself_and_gives_a_connection_a_file(tmp_path):
    """The descriptor keeps the certificate, not a path into somebody's home
    directory: a path is read at create, the domain inherits the PEM, and a
    connection gets a file materialized from it."""
    pem = "-----BEGIN CERTIFICATE-----\nMIIBfake\n-----END CERTIFICATE-----\n"
    src = tmp_path / "server-ca.pem"
    src.write_text(pem)
    gcp = systems.get("gcppostgres")
    base = {
        "HOSTNAME": "10.0.0.1",
        "PORT": "5432",
        "USERNAME": "postgres",
        "PASSWORD": "p",
    }

    # a path is read at create; the PEM is what is stored
    meta = gcp.plan_system("gcppostgres", {**base, "SERVER_CA_PEM_PATH": str(src)})
    assert meta["SERVER_CA_PEM"] == pem
    # and so is the PEM handed over directly ($GCPPOSTGRES__SERVER_CA_PEM)
    assert (
        gcp.plan_system("gcppostgres", {**base, "SERVER_CA_PEM": pem})["SERVER_CA_PEM"]
        == pem
    )

    # the domain inherits the certificate, so it needs no back-ref to the system
    dom = gcp.domain_meta(meta, "d1", "secret")
    assert dom["SERVER_CA_PEM"] == pem
    # ... and never leaks into the URIs a connector-under-test is handed
    assert "sslrootcert" not in dom["SQLALCHEMY_URI"] + dom["URI"]

    # a connection gets a real file -- and only for as long as it is connecting
    admin = gcp._admin(dom)
    assert admin.ca_pem == pem and not admin.sslrootcert
    with gcp._ca_file(admin) as connectable:
        written = pathlib.Path(connectable.sslrootcert)
        assert written.read_text() == pem
        assert connectable.sslrootcert in gcp._admin_url(connectable).replace(
            "%2F", "/"
        )
    assert not written.exists() and not written.parent.exists()

    # POSIX quoting, so `eval "$(... --as export)"` reproduces a multiline PEM
    import shlex

    assert shlex.split(f"K={shlex.quote(pem)}")[0] == f"K={pem}"

    for bad in (
        {"SERVER_CA_PEM": "not a pem"},
        {"SERVER_CA_PEM_PATH": str(tmp_path / "x")},
    ):
        with pytest.raises(TdxError):
            gcp.plan_system("gcppostgres", {**base, **bad})
    with pytest.raises(TdxError, match="not both"):
        gcp.plan_system(
            "gcppostgres",
            {**base, "SERVER_CA_PEM": pem, "SERVER_CA_PEM_PATH": str(src)},
        )


def test_gcppostgres_refuses_a_verifying_sslmode_without_the_instance_ca(tmp_path):
    """Cloud SQL signs each instance with a CA of its own -- there is no bundle to
    download -- and libpq reports the miss as a bare 'certificate verify failed'
    long after create. So create refuses first, naming the way to get the cert."""
    gcp = systems.get("gcppostgres")
    base = {
        "HOSTNAME": "10.0.0.1",
        "PORT": "5432",
        "USERNAME": "postgres",
        "PASSWORD": "p",
        "REGION": "europe-west1",
    }
    # the default posture verifies, so it needs the cert
    assert gcp.ssl_mode == "verify-ca"
    with pytest.raises(TdxError) as missing:
        gcp.plan_system("gcppostgres", base)
    assert "gcloud sql instances describe INSTANCE" in str(missing.value)
    # ... and it names the instance when the system knows which one it is
    with pytest.raises(TdxError) as named:
        gcp.plan_system("gcppostgres", {**base, "INSTANCE_ID": "k8sdb"})
    assert "gcloud sql instances describe k8sdb" in str(named.value)
    assert "--sslmode require" in str(missing.value)

    with pytest.raises(TdxError, match="is not a file"):
        gcp.plan_system(
            "gcppostgres", {**base, "SERVER_CA_PEM_PATH": str(tmp_path / "nope.pem")}
        )
    with pytest.raises(TdxError, match="unknown sslmode"):
        gcp.plan_system("gcppostgres", {**base, "SSLMODE": "verify-most"})

    # require encrypts without verifying: no cert to supply
    assert gcp.plan_system("gcppostgres", {**base, "SSLMODE": "require"})
    # and a real cert file satisfies the verifying default, on the admin URL only
    pem = tmp_path / "server-ca.pem"
    pem.write_text("-----BEGIN CERTIFICATE-----\ncreate-time\n")
    meta = gcp.plan_system("gcppostgres", {**base, "SERVER_CA_PEM_PATH": str(pem)})
    with gcp._ca_file(gcp._admin(meta)) as connectable:
        admin_url = gcp._admin_url(connectable).replace("%2F", "/")
        assert "sslmode=verify-ca" in admin_url
        written = admin_url.split("sslrootcert=")[1]
        assert pathlib.Path(written).read_text() == pem.read_text()


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
    from tabsdata_dev.common.systems import onepassword

    # a host/port/user/password type is 1Password's DATABASE item, and gets the
    # database_type menu filled from the dialect (the human would have to guess)
    rds = systems.get("awspostgres")
    item = onepassword.item(rds)
    assert item["category"] == onepassword.CATEGORY_DATABASE
    assert item["fields"][0] == {
        "id": "database_type",
        "label": "type",
        "type": "MENU",
        "value": "postgresql",
    }
    assert not any(f["id"] == onepassword.EXPIRES_FIELD for f in item["fields"])

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


def test_gcppostgres_1p_item_carries_the_certificate_but_not_the_path_to_it(tmp_path):
    """The whole point of the item for this type: a Cloud SQL instance is signed
    by a CA of its own, so the certificate has to travel with the credentials."""
    from tabsdata_dev.common.systems import onepassword

    gcp = systems.get("gcppostgres")
    item = onepassword.item(gcp)
    ids = [f["id"] for f in item["fields"]]
    assert item["category"] == onepassword.CATEGORY_DATABASE
    assert "server_ca_pem" in ids
    # which instance this is, in Google's terms -- not how it is reached
    assert "instance_id" in ids
    # the path to a local copy is one machine's, and create refuses being told
    # the same thing twice -- an item carrying both would break every create
    assert "server_ca_pem_path" not in ids
    pem = "-----BEGIN CERTIFICATE-----\nMIIBfake\n"
    src = tmp_path / "server-ca.pem"
    src.write_text(pem)
    with pytest.raises(TdxError, match="not both"):
        gcp.plan_system(
            "g",
            {
                "HOSTNAME": "h",
                "PORT": "5432",
                "USERNAME": "postgres",
                "PASSWORD": "p",
                "SERVER_CA_PEM": pem,
                "SERVER_CA_PEM_PATH": str(src),
            },
        )

    # a computed default is written out, never left as a placeholder: read back
    # from the vault, "?" would be refused as an sslmode
    by_id = {f["id"]: f["value"] for f in item["fields"]}
    assert by_id["sslmode"] == gcp.ssl_mode == "verify-ca"
    assert by_id["database_type"] == "postgresql" and by_id["server_ca_pem"] == "?"

    # and what the vault yields is what create reads
    from tabsdata_dev.common.core.secrets_1p import _norm

    produced = {f"{_norm(item['title'])}__{_norm(i)}" for i in ids}
    assert {"GCPPOSTGRES__SERVER_CA_PEM", "GCPPOSTGRES__SSLMODE"} <= produced


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
