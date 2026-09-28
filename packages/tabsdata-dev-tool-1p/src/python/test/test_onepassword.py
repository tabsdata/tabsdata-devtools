#
# Copyright 2026 Tabsdata Inc.
#

"""`tdd _1p fetch` against a stand-in provider: what reaches 1Password, and
the export lines that come back."""

import json
import pathlib
import shlex

import pytest

from tabsdata_dev.common.core import secrets, secrets_1p
from tabsdata_dev.tool import onepassword

KEY = "a-key-long-enough"


@pytest.fixture
def op(monkeypatch):
    """1Password as two dicts: fields read one at a time, and vault sweeps."""
    reads: list[tuple] = []
    fields = {("Employee", "DevSecrets", "TD_BACKENDS_CRYPTO_KEY"): KEY}
    vaults = {"dev_xp": {"PG__PASSWORD": "p w'd", "PG__HOST": "h", "S3__BUCKET": "b"}}

    def read_field(vault, item, field):
        reads.append((vault, item, field))
        return fields[(vault, item, field)]

    def fetch(vault):
        reads.append((vault,))
        return dict(vaults[vault])

    monkeypatch.setattr(secrets_1p, "read_field", read_field)
    monkeypatch.setattr(secrets_1p, "fetch", fetch)
    monkeypatch.delenv("_TDD_TOOL", raising=False)
    return type("Op", (), {"reads": reads, "fields": fields})


def _run(argv, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["_1p", *argv])
    code = onepassword.main()
    return code, [json.loads(x) for x in capsys.readouterr().out.splitlines()]


def _exports(message: str) -> dict[str, str]:
    """The export lines as a shell would read them."""
    out = {}
    for line in message.splitlines():
        word, assign = line.split(" ", 1)
        assert word == "export"
        name, value = assign.split("=", 1)
        (out[name],) = shlex.split(value)
    return out


def test_fetches_both_in_one_call_as_export_lines(op, monkeypatch, capsys):
    code, events = _run(
        [
            "fetch",
            "--crypto",
            "1p:Employee",
            "--secrets",
            "1p:dev_xp",
            "--format",
            "json",
        ],
        monkeypatch,
        capsys,
    )
    assert code == 0
    ok = events[-1]
    got = _exports(ok["message"])
    assert got == {
        "_TDD_CRYPTO_KEY": KEY,
        "PG__PASSWORD": "p w'd",  # quoted for the shell
        "PG__HOST": "h",
        "S3__BUCKET": "b",
        "_TDD_SYSTEMS": "PG S3",
    }
    assert ok["names"] == list(got)
    assert op.reads == [
        ("Employee", "DevSecrets", "TD_BACKENDS_CRYPTO_KEY"),
        ("dev_xp",),
    ]


def test_crypto_takes_another_item_and_field(op, monkeypatch, capsys):
    op.fields[("Mine", "Keys", "TDD")] = KEY
    code, events = _run(
        [
            "fetch",
            "--crypto",
            "1p:Mine",
            "--item",
            "Keys",
            "--field",
            "TDD",
            "--format",
            "json",
        ],
        monkeypatch,
        capsys,
    )
    assert code == 0 and _exports(events[-1]["message"]) == {"_TDD_CRYPTO_KEY": KEY}


def test_a_short_key_is_refused_with_where_it_came_from(op, monkeypatch, capsys):
    op.fields[("Employee", "DevSecrets", "TD_BACKENDS_CRYPTO_KEY")] = "short"
    code, events = _run(
        ["fetch", "--crypto", "1p:Employee", "--format", "json"], monkeypatch, capsys
    )
    assert code == 1
    message = events[-1]["message"]
    assert "1p:Employee/DevSecrets/TD_BACKENDS_CRYPTO_KEY is 5 characters" in message
    assert "short" not in message.split("is 5")[0]  # the value is never said


@pytest.mark.parametrize(
    ("argv", "says"),
    [
        (["fetch"], "nothing to fetch"),
        (["fetch", "--crypto", "Employee"], "--crypto takes a provider ref, 1p:VAULT"),
        (["fetch", "--secrets", "1p:"], "--secrets takes a provider ref"),
        (["fetch", "--secrets", "1p:dev_xp", "--item", "X"], "pass --crypto"),
        ([], "a subcommand is required"),
    ],
)
def test_refuses_before_reading_anything(op, monkeypatch, capsys, argv, says):
    code, events = _run([*argv, "--format", "json"], monkeypatch, capsys)
    assert code == 1 and says in events[-1]["message"]
    assert op.reads == []


def test_the_key_length_is_the_one_env_and_crypto_enforce():
    """`tdd env set --crypto --value` checks the same minimum in both shells."""
    root = pathlib.Path(__file__).resolve().parents[5]
    scripts = root / "packages/tabsdata-dev-shell/scripts"
    n = secrets.CRYPTO_KEY_MIN_LEN
    assert f"_TDD_CRYPTO_MIN={n}" in (scripts / "unix/env.sh").read_text()
    assert (
        f"$global:_TDD_CRYPTO_MIN = {n}" in (scripts / "powershell/env.ps1").read_text()
    )
