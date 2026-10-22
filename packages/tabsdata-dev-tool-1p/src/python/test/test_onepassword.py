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
    fields = {
        ("Employee", "DevSecrets", "TD_BACKENDS_CRYPTO_KEY"): KEY,
        ("Employee", "DevSecrets", "PYPI_TWINE_USERNAME"): "__token__",
        ("Employee", "DevSecrets", "PYPI_TWINE_PASSWORD"): "pypi-s3cr'et",
    }
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


def _stdout(argv, monkeypatch, capsys):
    """(exit code, stdout, stderr) of a run in the default format."""
    monkeypatch.setattr("sys.argv", ["_1p", *argv])
    code = onepassword.main()
    out, err = capsys.readouterr()
    return code, out, err


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
    """export is the default: the lines on stdout are the outcome, nothing else
    is there, and a shell reads back exactly the values."""
    code, out, _ = _stdout(
        ["fetch", "--crypto", "1p:Employee", "--secrets", "1p:dev_xp"],
        monkeypatch,
        capsys,
    )
    assert code == 0
    got = _exports(out)
    assert got == {
        "_TDD_CRYPTO_KEY": KEY,
        "PG__PASSWORD": "p w'd",  # quoted for the shell
        "PG__HOST": "h",
        "S3__BUCKET": "b",
        "_TDD_SYSTEMS": "PG S3",
    }
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
    assert code == 0 and events[-1]["values"] == {"_TDD_CRYPTO_KEY": KEY}


def test_pypi_twine_exports_the_upload_credentials_under_twines_names(
    op, monkeypatch, capsys
):
    """`--pypi-twine` alone reads DevSecrets' PYPI_TWINE_USERNAME/_PASSWORD in
    the crypto key's vault and exports them as the names twine reads."""
    code, out, _ = _stdout(["fetch", "--pypi-twine"], monkeypatch, capsys)
    assert code == 0
    assert _exports(out) == {
        "TWINE_USERNAME": "__token__",
        "TWINE_PASSWORD": "pypi-s3cr'et",
    }
    assert op.reads == [
        ("Employee", "DevSecrets", "PYPI_TWINE_USERNAME"),
        ("Employee", "DevSecrets", "PYPI_TWINE_PASSWORD"),
    ]


def test_pypi_twine_combines_with_the_rest_in_one_call(op, monkeypatch, capsys):
    code, out, _ = _stdout(
        ["fetch", "--crypto", "--pypi-twine", "--secrets"], monkeypatch, capsys
    )
    assert code == 0
    assert {"_TDD_CRYPTO_KEY", "TWINE_USERNAME", "TWINE_PASSWORD"} <= set(_exports(out))


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
        (["fetch", "--pypi-twine", "Employee"], "--pypi-twine takes a provider ref"),
        ([], "a subcommand is required: fetch, push"),
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


@pytest.fixture
def op_items(monkeypatch):
    """`op` for items: what it was asked, whether the title is filed already,
    and what it was handed on stdin."""
    calls: list[list[str]] = []
    sent: dict = {"exists": False}

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
            cp.returncode = 0 if sent["exists"] else 1
        if "create" in argv:
            # the item is piped in, not written anywhere and not in argv
            sent["stdin"] = kw.get("input", "")
            cp.stdout = '{"id": "abc123"}'
        return cp

    monkeypatch.setattr(secrets_1p.subprocess, "run", fake_run)
    monkeypatch.delenv("_TDD_TOOL", raising=False)
    return type("OpItems", (), {"calls": calls, "sent": sent})


ITEM = {"title": "S3", "category": "API_CREDENTIAL", "fields": [{"id": "bucket"}]}


def test_push_deletes_before_creating_so_a_title_cannot_duplicate(
    op_items, tmp_path, monkeypatch, capsys
):
    """`op item create` files a second item under a title that already exists
    rather than replacing the first, and a vault with two `S3` items reads back
    a coin toss -- so a set is a delete followed by a create."""
    entry = tmp_path / "s3.json"
    entry.write_text(json.dumps(ITEM))
    argv = ["push", "--vault", "1p:dev_xp", "--entry", str(entry), "--format", "json"]

    op_items.sent["exists"] = True  # the item is already filed
    code, events = _run(argv, monkeypatch, capsys)
    assert code == 0
    calls = op_items.calls
    assert [c[c.index("item") + 1] for c in calls if "item" in c] == [
        "get",
        "delete",
        "create",
    ]
    assert all(c[c.index("--vault") + 1] == "dev_xp" for c in calls if "--vault" in c)
    # what op is handed is the item itself, on stdin: not in argv (which every
    # user on the machine can read) and not written to a file at all
    assert json.loads(op_items.sent["stdin"]) == ITEM
    assert not any("--template" in c or "secret" in " ".join(c) for c in calls)
    ok = events[-1]
    assert ok["replaced"] is True and ok["id"] == "abc123" and ok["vault"] == "dev_xp"
    assert "replaced 'S3' in 1p:dev_xp" in ok["message"]
    assert "Recently Deleted" in ok["message"]

    calls.clear()
    op_items.sent["exists"] = False  # nothing filed under that title yet
    code, events = _run(argv, monkeypatch, capsys)
    assert code == 0 and events[-1]["replaced"] is False
    assert [c[c.index("item") + 1] for c in calls if "item" in c] == ["get", "create"]
    assert "created 'S3'" in events[-1]["message"]


def test_push_reads_the_item_from_stdin(op_items, monkeypatch, capsys):
    import io

    raw = io.BytesIO(json.dumps({**ITEM, "title": "S3 \u00e9"}).encode("utf-8"))
    monkeypatch.setattr("sys.stdin", type("In", (), {"buffer": raw})())
    code, events = _run(
        ["push", "--vault", "1p:dev_xp", "--entry", "-", "--format", "json"],
        monkeypatch,
        capsys,
    )
    assert code == 0 and events[-1]["title"] == "S3 \u00e9"


@pytest.mark.parametrize(
    ("vault", "entry", "says"),
    [
        ("dev_xp", "s3.json", "--vault takes a provider ref, 1p:VAULT"),
        ("hc:dev_xp", "s3.json", "only 1p:VAULT files an item"),
        ("1p:dev_xp", "bad.json", "no category, fields"),
        ("1p:dev_xp", "list.json", "one 1Password item"),
        ("1p:dev_xp", "nope.json", "cannot read --entry"),
    ],
)
def test_push_refuses_before_it_deletes(
    op_items, tmp_path, monkeypatch, capsys, vault, entry, says
):
    """Checked here rather than left to op: a refusal after the delete has
    already run is a refusal that has destroyed something."""
    (tmp_path / "s3.json").write_text(json.dumps(ITEM))
    (tmp_path / "bad.json").write_text('{"title": "S3"}')
    (tmp_path / "list.json").write_text("[]")
    code, events = _run(
        [
            "push",
            "--vault",
            vault,
            "--entry",
            str(tmp_path / entry),
            "--format",
            "json",
        ],
        monkeypatch,
        capsys,
    )
    assert code == 1 and says in events[-1]["message"]
    assert op_items.calls == []


def test_push_files_only_what_a_create_may_carry(tmp_path):
    """A whole `op item get --format=json` can be handed straight back: read an
    item, edit a value, file it again. What is dropped is the identity of the
    item it was read *from* -- id, version, vault, timestamps -- and each
    field's op:// reference, which 1Password mints from where the field ends
    up, so a copied one points somewhere else."""
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
    out = onepassword.read_entry(str(entry))
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


def test_bare_selections_read_the_default_vaults(op, monkeypatch, capsys):
    """`--crypto` and `--secrets` alone read the Employee and dev_xp vaults --
    the same literals `tdd env` keeps in env.toml."""
    code, out, _ = _stdout(["fetch", "--crypto", "--secrets"], monkeypatch, capsys)
    assert code == 0 and set(_exports(out)) >= {"_TDD_CRYPTO_KEY", "_TDD_SYSTEMS"}
    assert op.reads == [
        ("Employee", "DevSecrets", "TD_BACKENDS_CRYPTO_KEY"),
        ("dev_xp",),
    ]
    assert onepassword.DEFAULT_CRYPTO_VAULT == "1p:Employee"
    assert onepassword.DEFAULT_SECRETS_VAULT == "1p:dev_xp"
    root = pathlib.Path(__file__).resolve().parents[5]
    env_sh = (root / "packages/tabsdata-dev-shell/scripts/unix/env.sh").read_text()
    assert f'_TDD_VAULT_CRYPTO="{onepassword.DEFAULT_CRYPTO_VAULT}"' in env_sh
    assert f'_TDD_VAULT_SECRETS="{onepassword.DEFAULT_SECRETS_VAULT}"' in env_sh


def test_an_export_for_windows_is_a_powershell_file_of_the_same_values(
    op,
    monkeypatch,
    capsys,
):
    """macOS is the default and Linux writes the same lines; for Windows, which
    has no 1Password, the same variables come as $env: lines in a file that
    says what it is -- secrets.render's own test loads one in real pwsh."""
    argv = ["fetch", "--crypto", "1p:Employee", "--secrets", "1p:dev_xp"]
    _, macos, _ = _stdout(argv, monkeypatch, capsys)
    _, linux, _ = _stdout([*argv, "--platform", "linux"], monkeypatch, capsys)
    assert linux == macos
    code, windows, _ = _stdout([*argv, "--platform", "windows"], monkeypatch, capsys)
    assert code == 0
    assert windows.startswith(
        "# Secrets exported by `tdd _1p fetch --platform windows`"
    )
    lines = [line for line in windows.splitlines() if line.startswith("$env:")]
    assert [line.split(" = ", 1)[0] for line in lines] == [
        f"$env:{name}" for name in _exports(macos)
    ]
    assert "$env:PG__PASSWORD = 'p w''d'" in lines  # quoted for PowerShell


def test_view_names_what_was_fetched_and_json_carries_the_values(
    op, monkeypatch, capsys
):
    code, out, _ = _stdout(
        ["fetch", "--crypto", "--format", "view"], monkeypatch, capsys
    )
    assert code == 0
    assert out.strip() == "fetched 1 variable(s): _TDD_CRYPTO_KEY"
    assert KEY not in out  # a person at a terminal never sees a value
    code, events = _run(["fetch", "--crypto", "--format", "json"], monkeypatch, capsys)
    assert events[-1]["values"] == {"_TDD_CRYPTO_KEY": KEY}
    # the format goes before the subcommand word as well as after it
    code, out, _ = _stdout(
        ["--format", "view", "fetch", "--crypto"], monkeypatch, capsys
    )
    assert KEY not in out


def test_push_has_nothing_to_export(op_items, tmp_path, monkeypatch, capsys):
    """The tool's default format is export, for fetch; push reads it as view,
    and does not offer export itself."""
    entry = tmp_path / "s3.json"
    entry.write_text(json.dumps(ITEM))
    code, out, _ = _stdout(
        ["push", "--vault", "1p:dev_xp", "--entry", str(entry)], monkeypatch, capsys
    )
    assert code == 0 and out.startswith("created 'S3' in 1p:dev_xp")
    code = _run(
        ["push", "--vault", "1p:dev_xp", "--entry", str(entry), "--format", "export"],
        monkeypatch,
        capsys,
    )[0]
    assert code == 1
