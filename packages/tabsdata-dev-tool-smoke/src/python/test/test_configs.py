#
# Copyright 2026 Tabsdata Inc.
#

"""The config edits of a smoke run (`tdd _smoke`), against the shapes of the
files tdkserver generates."""

import io
import json
import shutil

import pytest
from tabsdata_dev.common.core import errors
from tabsdata_dev.tool.smoke import configs, engine

#: Everything a password may hold that sed would read as syntax.
NASTY = r"p&ss\1\\word$1/x{}[]*.^"


def test_substitution_is_literal_on_both_sides(tmp_path, resource_folder):
    """The placeholder holds `${{`, `?` and `:`; the value can be a password, a
    PEM or JSON. Neither may be read as a pattern or as a backreference, which
    is what ruled sed out."""
    cfg = tmp_path / "a.yaml"
    shutil.copy(resource_folder / "placeholders.yaml", cfg)
    assert configs.fill_placeholder([cfg], "${{secret:pw?}}", NASTY) == 1
    assert configs.fill_placeholder([cfg], "${{literal:host}}", "10.0.0.1") == 1
    assert configs.fill_placeholder([cfg], "${{literal:absent}}", "x") == 0
    configs.set_uv_index(cfg, "https://cdn.example/simple/")
    written = cfg.read_text().splitlines()
    assert written[0] == f"key: {NASTY}", written[0]
    assert written[1] == "other: 10.0.0.1"
    # the rewrite keeps the line's indentation and takes the URL verbatim
    assert written[2] == "  UV_INDEX: https://cdn.example/simple/"


def test_an_edit_keeps_the_file_s_line_endings(tmp_path):
    """A config written on Windows may end its lines in CRLF; an edit must not
    turn half of them into LF, nor the other way round."""
    cfg = tmp_path / "crlf.yaml"
    cfg.write_bytes(b"a: ${{literal:x}}\r\n  UV_INDEX: old\r\nb: 1\r\n")
    configs.fill_placeholder([cfg], "${{literal:x}}", "1")
    configs.set_uv_index(cfg, "https://new/")
    assert cfg.read_bytes() == b"a: 1\r\n  UV_INDEX: https://new/\r\nb: 1\r\n"


def test_fill_pem_writes_a_yaml_block_scalar(tmp_path, resource_folder):
    """A certificate is many lines, and fill_placeholder substitutes text.
    Dropped in raw, a PEM's newlines continue the plain scalar and YAML folds
    them into spaces: the file still parses, and then no certificate ever
    loads. So the whole `key: ${{...}}` line becomes a block scalar indented
    past its key."""
    pem = (resource_folder / "certificate.pem").read_text()
    cfg = tmp_path / "db.yaml"

    def fresh():
        shutil.copy(resource_folder / "pem.yaml", cfg)
        return [cfg]

    assert configs.fill_pem(fresh(), "${{secret:ca}}", pem) == len(
        pem.strip().splitlines()
    )
    assert cfg.read_text() == (resource_folder / "pem.expected.yaml").read_text()
    # a config that only looks filled is the failure worth catching early, so
    # neither an empty value nor an absent placeholder passes quietly
    with pytest.raises(errors.ToolError, match="the value is empty"):
        configs.fill_pem(fresh(), "${{secret:ca}}", "  \n")
    with pytest.raises(errors.ToolError, match="is not in any of"):
        configs.fill_pem(fresh(), "${{secret:nope}}", pem)


def test_set_fn_resources_sizes_the_function_pods_and_only_them(
    tmp_path, resource_folder
):
    """`--td-fn-memory`/`--td-fn-disk` rewrite pods.function.resources in a
    tabsdata.yaml that carries a `resources:` block under every service as
    well. The edit walks the indentation to the function block's own, rewrites
    the two lines in place -- tdkserver compares the filled file's shape to the
    template's -- and fails unless exactly one memory and one disk line
    changed, because a sizing that silently missed would pass that shape check
    and surface as a pod that never schedules."""
    template = (resource_folder / "tabsdata.yaml").read_text()
    cfg = tmp_path / "tabsdata.yaml"

    cfg.write_text(template)
    configs.set_fn_resources(cfg, "8Gi", "32Gi")
    # the function block moved, and nothing else did: the service blocks keep
    # their 1Gi/16Gi and 8Gi/64Gi, the cpu and the placement are untouched
    assert cfg.read_text() == template.replace(
        "      memory: 16Gi\n      disk: 64Gi\n",
        "      memory: 8Gi\n      disk: 32Gi\n",
    )

    # no function block: refused, and the file is left as it was
    headless = template.split("  function:\n", 1)[0]
    cfg.write_text(headless)
    with pytest.raises(errors.ToolError, match="expected one memory and one disk"):
        configs.set_fn_resources(cfg, "8Gi", "32Gi")
    assert cfg.read_text() == headless

    # two function blocks would be two rewrites: refused too
    cfg.write_text(template + "  function:\n" + template.split("  function:\n", 1)[1])
    with pytest.raises(errors.ToolError):
        configs.set_fn_resources(cfg, "8Gi", "32Gi")


def test_placeholders_left_names_only_the_required_ones(tmp_path):
    """`literal:` and `secret:` without `?` must be filled; an optional `?`
    one, and `system:`/`secretAuto:` (tabsdata's own), may stay."""
    (tmp_path / "a.yaml").write_text(
        "a: ${{literal:host}}\nb: ${{secret:pw?}}\nc: ${{system:x}}\nd: ${{secret}}\n"
    )
    (tmp_path / "notes.txt").write_text("${{literal:ignored}}\n")
    path = tmp_path / "a.yaml"
    assert configs.placeholders_left(tmp_path) == [
        f"{path}:1:a: " + "${{literal:host}}",
        f"{path}:4:d: " + "${{secret}}",
    ]
    (tmp_path / "a.yaml").write_text("a: 1\n")
    assert configs.placeholders_left(tmp_path) == []


STORAGE_ENV = {
    "STORD__URI": "s3://bucket/run/",
    "STORS__REGION": "eu-west-1",
    "STORS__ACCESS_KEY": "AKIA",
    "STORS__SECRET_KEY": "",
    "STORD__SERVICE_ACCOUNT_KEY": '{"type": "service_account", "key": "a\\nb"}',
    "STORD__ACCOUNT_KEY": NASTY,
}


@pytest.mark.parametrize("cloud", configs.CLOUDS)
def test_fill_storage_writes_every_value_as_a_yaml_scalar(
    tmp_path, resource_folder, cloud
):
    """tdkserver compares the filled config's shape against its template's and
    refuses a value whose shape changed (ResolverError::StructureMismatch). The
    GCS service-account key is itself JSON, so dropped in bare it reads back as
    a flow MAPPING where the template holds a scalar -- a run reached `create`
    before failing on it. Every value goes in as a YAML double-quoted scalar."""
    cfg = tmp_path / "apiserver.storage.yaml"
    shutil.copy(resource_folder / "storage.yaml", cfg)
    found = configs.fill_storage(cfg, cloud, STORAGE_ENV)
    text = cfg.read_text()
    for mount, folder in configs.STORAGE_MOUNTS.items():
        assert f"uri: {json.dumps(f's3://bucket/run/{folder}/')}" in text, mount
        assert f"{mount}.uri" in found["filled"]
    # a key no map knows is left for placeholders-left to name
    assert "mystery_key: ${{secret}}" in text
    assert "mystery_key" in found["unknown"]
    if cloud == "aws":
        assert 'aws_region: "eu-west-1"' in text
        # the s3 system may hold no secret key; aws writes it as it is
        assert "aws_secret_access_key" not in found["empty"]
    if cloud == "gcp":
        account = json.dumps(STORAGE_ENV["STORD__SERVICE_ACCOUNT_KEY"])
        assert f"google_service_account_key: {account}" in text
        assert 'aws_region: "auto"' in text
        # no HMAC pair set: left, and said so
        assert found["empty"] == ["aws_access_key_id"]
    if cloud == "azure":
        assert f"account_key: {json.dumps(NASTY)}" in text
        assert "aws_region: ${{secret}}" in text


def test_fill_storage_reads_a_service_account_key_from_its_file(
    tmp_path, resource_folder
):
    key = tmp_path / "sa.json"
    key.write_text('{"type": "service_account"}\n')
    cfg = tmp_path / "apiserver.storage.yaml"
    shutil.copy(resource_folder / "storage.yaml", cfg)
    configs.fill_storage(
        cfg,
        "gcp",
        {"STORD__URI": "gs://b", "STORD__SERVICE_ACCOUNT_KEY": str(key)},
    )
    assert json.dumps('{"type": "service_account"}') in cfg.read_text()


def test_event_field_reads_the_ok_event_of_json_lines():
    lines = [
        '{"command":"xp","event":"info","message":"reading"}\n',
        '{"command":"xp","event":"ok","message":"2 dirs","dirs":["test","cdc"]}\n',
    ]
    assert configs.event_field(lines, "dirs") == ["test", "cdc"]
    with pytest.raises(errors.ToolError, match="no ok event"):
        configs.event_field(lines[:1], "dirs")


def test_a_value_is_read_from_the_environment_and_answered_on_stdout(
    tmp_path, monkeypatch, capsys
):
    """The value can be a password, so it is never an argument; and the answer
    is the ok message, alone on stdout, which `$(tdd _smoke ...)` reads in
    either shell family."""
    cfg = tmp_path / "a.yaml"
    cfg.write_text("pw: ${{secret:pw}}\n")
    argv = ["_smoke", "fill-placeholder", "--placeholder", "${{secret:pw}}", str(cfg)]
    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.delenv(engine.VALUE_ENV, raising=False)
    assert engine.main() == 1
    assert cfg.read_text() == "pw: ${{secret:pw}}\n"

    monkeypatch.setenv(engine.VALUE_ENV, NASTY)
    capsys.readouterr()
    assert engine.main() == 0
    assert cfg.read_text() == f"pw: {NASTY}\n"
    done = capsys.readouterr()
    assert NASTY not in done.out + done.err

    feed = io.StringIO('{"event":"ok","message":"","dirs":["a","b"]}\n')
    monkeypatch.setattr("sys.stdin", feed)
    monkeypatch.setattr("sys.argv", ["_smoke", "event-field", "--field", "dirs"])
    assert engine.main() == 0
    assert capsys.readouterr().out == "a\nb\n"
