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

    from tabsdata_dev.common.systems.systems._common.ports import (
        PortRangeMixin,
        system_port_range,
    )

    class Fake(PortRangeMixin):
        slug = "mysql"

    lo, hi = system_port_range("mysql")
    busy = socket.socket()
    busy.bind(("", lo))
    busy.listen(1)
    try:
        f = Fake()
        got = [f.next_free_port() for _ in range(3)]
        assert lo not in got and len(set(got)) == 3 and all(lo < p <= hi for p in got)
        g = Fake()
        g.use_ports([lo + 50, lo + 51])
        assert [g.next_free_port() for _ in range(3)] == [lo + 50, lo + 51, got[0]]
    finally:
        busy.close()
