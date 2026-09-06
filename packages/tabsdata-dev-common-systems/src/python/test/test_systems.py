#
# Copyright 2026 Tabsdata Inc.
#

"""Smoke tests for the shared family: registry, models, constants -- nothing that
needs a driver, a docker daemon or a crypto key."""

import json

from tabsdata_dev.common.systems import constants, datagen, dispatch, systems


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
    rds = systems.get("rdspostgres")
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


def test_template_covers_every_type_and_says_so_when_none_is_named(capsys):
    from tabsdata_dev.common.systems import main

    rc = main.run(
        constants.SYS_TOOL,
        [constants.V_TEMPLATE, constants.OPT_TYPE, "ALL", constants.OPT_FORMAT, "1p"],
    )
    out = capsys.readouterr().out
    assert rc == 0
    items = json.loads(out[out.index("[") : out.rindex("]") + 1])
    assert len(items) == len(systems.all_slugs())

    # a template is about a type, and there is no current one to assume
    rc = main.run(constants.SYS_TOOL, [constants.V_TEMPLATE, "--format", "json"])
    events = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("{")
    ]
    err = [e for e in events if e["event"] == "error"][0]
    assert rc == 1 and constants.OPT_TYPE in err["message"]
