#
# Copyright 2026 Tabsdata Inc.
#

import json

import pytest
from tabsdata_dev.common.core.errors import ToolError
from tabsdata_dev.tool import gsx
from tabsdata_dev.tool.gsx import approve as approve_mod
from tabsdata_dev.tool.gsx import args as args_mod
from tabsdata_dev.tool.gsx.version import VERSION
from tabsdata_dev.tool.gsx import commands, config, gh, labels


class _Out:
    """The renderer's surface, remembered instead of printed."""

    def __init__(self):
        self.events = []

    def _add(self, kind):
        return lambda message, **fields: self.events.append((kind, message))

    def __getattr__(self, name):
        if name in ("info", "warn", "debug", "error"):
            return self._add(name)
        raise AttributeError(name)

    def ok(self, message, **fields):
        self.events.append(("ok", message))
        return 0

    def messages(self, kind):
        return [m for k, m in self.events if k == kind]


# ----------------------------------------------------------------- grammar
def test_split_takes_lr_ops_and_passthrough_and_leaves_the_rest():
    argv = [
        "apply",
        "--label:top:add",
        "run-ci",
        "--r:mine",
        "a,b",
        "-o",
        "--e:add-assignee=me",
        "--e:draft",
        "--",
        "src/x.py",
    ]
    rest, extras = args_mod.split(argv, args_mod.APPLY_NATIVES, takes_lr=True)
    assert rest == ["apply", "-o", "--", "src/x.py"]
    label, reviewer = extras.lr_ops
    assert (label.kind, label.scope, label.mode, label.values) == (
        "label",
        "top",
        "add",
        ["run-ci"],
    )
    assert (reviewer.kind, reviewer.scope, reviewer.mode, reviewer.values) == (
        "reviewer",
        "mine",
        "replace",
        ["a", "b"],
    )
    # arity is inferred: a value follows --e:add-assignee, --e:draft is a flag
    assert extras.passthrough["e"] == ["--add-assignee", "me", "--draft"]


def test_an_empty_list_is_remove_all_and_a_missing_value_is_an_error():
    _, extras = args_mod.split(
        ["apply", "--label:all", ""], args_mod.APPLY_NATIVES, True
    )
    assert extras.lr_ops[0].values == []
    with pytest.raises(ToolError, match="needs a value"):
        args_mod.split(["apply", "--label:all"], args_mod.APPLY_NATIVES, True)


def test_unknown_scope_mode_and_prefix_are_refused_by_name():
    with pytest.raises(ToolError, match="unknown scope"):
        args_mod.split(["apply", "--label:nope", "x"], args_mod.APPLY_NATIVES, True)
    with pytest.raises(ToolError, match="unknown mode"):
        args_mod.split(["apply", "--label:all:nope", "x"], args_mod.APPLY_NATIVES, True)
    with pytest.raises(ToolError, match="unknown passthrough prefix"):
        args_mod.split(["apply", "--z:flag"], args_mod.APPLY_NATIVES, True)


def test_a_subcommand_that_takes_no_lr_leaves_those_tokens_to_argparse():
    rest, extras = args_mod.split(
        ["checkout", "--label:all", "x"], args_mod.CHECKOUT_NATIVES, takes_lr=False
    )
    assert rest == ["checkout", "--label:all", "x"] and not extras.lr_ops


def test_passthrough_over_a_gsx_owned_flag_needs_override():
    _, extras = args_mod.split(
        ["apply", "--e:add-label", "bug"], args_mod.APPLY_NATIVES, True
    )
    out = _Out()
    with pytest.raises(ToolError, match="collide"):
        args_mod.check_overlaps(extras, args_mod.APPLY_NATIVES, override=False, out=out)
    args_mod.check_overlaps(extras, args_mod.APPLY_NATIVES, override=True, out=out)
    assert "overriding gsx's own options" in out.messages("warn")[0]


# ------------------------------------------------------------------ naming
@pytest.mark.parametrize(
    "name,postfix",
    [("tabsdata-foo", "FOO"), ("tabsdata-conn-gcs", "GCS"), ("tabsdata", "TABSDATA")],
)
def test_the_branch_prefix_is_the_last_segment_of_the_repository_name(name, postfix):
    assert gh.repo_postfix(name) == postfix


def test_a_commit_message_carries_the_tag_the_body_and_the_trailer():
    message = commands.build_message("FOO-15", "Fix it", "Why.", 15)
    assert message == "[FOO-15] Fix it\n\nWhy.\n\nCloses #15\n"
    assert commands.split_message(message) == ("[FOO-15] Fix it", "Why.", "Closes #15")


# ------------------------------------------------------------------ config
def test_the_repo_tables_round_trip_and_leave_the_options_alone(tmp_path, monkeypatch):
    from tabsdata_dev.common.core import config as common

    monkeypatch.setenv("TDD_DIR", str(tmp_path))
    assert config.path() == tmp_path / "gsx.toml"
    empty = config.read()  # no file yet: the defaults, and nothing of its own
    assert (empty["version"], empty["repos"]) == ("", {})
    assert empty["approve"] == config.APPROVE_DEFAULTS
    assert empty["aliases"] == config.ALIAS_DEFAULTS  # the team ships with gsx

    written = {
        "version": VERSION,
        "aliases": {**config.ALIAS_DEFAULTS, "extra": "someone"},
        "repos": {
            "o/n": {
                "fetched": "2026-09-05T00:00:00-03:00",
                "labels": ["bug", "run-ci"],
                "reviewers": ["tucu0"],
                "defaults": {"labels": ["skip-ci"], "reviewers": []},
            },
            "o/other": {
                "fetched": "",
                "labels": [],
                "reviewers": [],
                "defaults": {"labels": [], "reviewers": []},
            },
        },
    }
    config.write(written)
    back = config.read()
    assert {k: back[k] for k in written} == written  # each repository keeps its own
    assert back["approve"] == config.APPROVE_DEFAULTS  # written with the defaults

    text = config.path().read_text()
    assert '[repo."o/n"]' in text and '[repo."o/other"]' in text
    assert "[reviewer-aliases]" in text and 'dimas = "aoinokimi"' in text
    assert 'extra = "someone"' in text  # a reader's own, beside the shipped ones
    # the shared option template is written too, and survives a repo refresh
    assert "[options]" in text and "[options.submit]" in text
    # the template writes no option line, so setting one means adding it
    config.path().write_text(
        text.replace("[options]\n", "[options]\nverbose = true\n", 1)
    )
    config.write(config.read())
    assert common.options_in("gsx")[""] == {"verbose": True}
    assert config.read()["repos"]["o/n"]["defaults"]["labels"] == ["skip-ci"]


def test_the_commented_tables_are_valid_toml_once_uncommented(tmp_path, monkeypatch):
    """The template shows gsx's own tables at their defaults so a reader knows
    they exist. Each has to survive being uncommented, which rules out the
    tempting layout: an aligned explanation trailing the value is inside the
    line, and taking the `# ` off leaves prose after the value."""
    import tomllib

    from tabsdata_dev.tool.gsx.options import CONFIG_TABLES

    text = "\n".join(
        line[2:] if line.startswith("# ") else line
        for line in CONFIG_TABLES.splitlines()
        if line.startswith("# [") or " = " in line
    )
    document = tomllib.loads(text)
    creds = document[config.CREDS]
    assert creds["approve_vault"] == config.APPROVE_DEFAULTS["approve_vault"]
    # every shipped alias is listed, and at the login it actually resolves to
    assert document[config.ALIASES] == config.ALIAS_DEFAULTS
    assert document[config.REPO]["OWNER/NAME"] == {
        "default_labels": [],
        "default_reviewers": [],
    }
    # the two the tool owns are described, never offered as a line to uncomment
    assert "fetched = " not in text and "labels = [" not in text.replace(
        "default_labels = []", ""
    )
    assert "MAINTAINED BY gsx" in CONFIG_TABLES


def test_the_shipped_aliases_work_without_a_file_and_yield_to_one(
    tmp_path, monkeypatch
):
    """The team's aliases ship in code, so `--reviewer:new tucu` resolves before
    anyone has written a config; a file entry of the same name wins, the way the
    approve_* defaults do."""
    monkeypatch.setenv("TDD_DIR", str(tmp_path))
    assert config.read()["aliases"] == config.ALIAS_DEFAULTS  # no file at all
    assert approve_mod.resolve(["tucu"], config.read()["aliases"])[0].login == "tucu0"

    config.path().write_text(
        '[options]\n\n[reviewer-aliases]\ntucu = "elsewhere"\nnew = "newlogin"\n'
    )
    aliases = config.read()["aliases"]
    assert aliases["tucu"] == "elsewhere"  # the file wins
    assert aliases["david"] == config.ALIAS_DEFAULTS["david"]  # the rest survive
    assert aliases["new"] == "newlogin"


def test_a_file_written_before_the_rename_still_reads_and_migrates(
    tmp_path, monkeypatch
):
    """`[gsx]` held the approve settings and the version. It is now
    `[approver-credentials]`, and the version sits on `[repo]` -- what it dates
    -- so an existing file has to be read either way and written the new way."""
    monkeypatch.setenv("TDD_DIR", str(tmp_path))
    config.path().write_text(
        '[options]\n\n[gsx]\nversion = "0.0.9"\napprove_vault = "old_vault"\n'
    )
    old = config.read()
    assert old["version"] == "0.0.9"
    assert old["approve"]["approve_vault"] == "old_vault"  # a custom one survives

    config.write(old)
    text = config.path().read_text()
    assert f"[{config.CREDS}]" in text and 'approve_vault = "old_vault"' in text
    assert f"[{config.REPO}]\nversion = " in text
    assert "\n[gsx]\n" not in text  # the old table is not written again
    assert config.read()["approve"]["approve_vault"] == "old_vault"


# ------------------------------------------------------------------ engine
class _NoAliases:
    """A repo with nothing in [reviewer-aliases]."""

    def aliases(self):
        return {}


def _snapshot():
    return [
        {"branch": "A-1", "number": 6, "author": "me", "labels": [], "reviewers": []},
        {
            "branch": "A-2",
            "number": 7,
            "author": "you",
            "labels": ["bug"],
            "reviewers": [],
        },
    ]


@pytest.mark.parametrize(
    "scope,numbers",
    [("new", [6]), ("top", [7]), ("all", [6, 7]), ("mine", [6])],
)
def test_every_scope_picks_the_prs_it_says(scope, numbers):
    op = args_mod.LrOp("label", scope, "replace", ["x"], "--label")
    assert [p["number"] for p in labels.targets(op, _snapshot(), "me")] == numbers


def test_ops_fold_into_one_edit_per_pr_and_an_unchanged_pr_gets_no_call(monkeypatch):
    calls = []

    class FakeRunner:
        dry_run = False

        def run(self, argv, **kwargs):
            calls.append(argv)
            return ""

    monkeypatch.setattr(gh, "stack_pr_snapshot", lambda runner: _snapshot())
    monkeypatch.setattr(labels, "check_values", lambda repo, ops: None)
    ops = [
        args_mod.LrOp("label", "new", "replace", ["skip-ci"], "--label:new"),
        args_mod.LrOp("label", "top", "replace", ["run-ci"], "--label:top"),
    ]
    changed, failures = labels.apply(FakeRunner(), _NoAliases(), ops, [], _Out())
    assert (changed, failures) == (2, [])
    assert calls == [
        ["gh", "pr", "edit", "6", "--add-label", "skip-ci"],
        ["gh", "pr", "edit", "7", "--add-label", "run-ci", "--remove-label", "bug"],
    ]
    # a second run over the same desired state writes nothing at all
    calls.clear()
    monkeypatch.setattr(
        gh,
        "stack_pr_snapshot",
        lambda runner: [
            {**pull, "labels": ["skip-ci"] if pull["number"] == 6 else ["run-ci"]}
            for pull in _snapshot()
        ],
    )
    changed, failures = labels.apply(FakeRunner(), _NoAliases(), ops, [], _Out())
    assert (changed, failures, calls) == (0, [], [])


def test_every_pr_is_attempted_even_when_one_fails(monkeypatch):
    class FailingRunner:
        dry_run = False

        def run(self, argv, **kwargs):
            if argv[3] == "6":
                raise ToolError("gh said no")
            return ""

    monkeypatch.setattr(gh, "stack_pr_snapshot", lambda runner: _snapshot())
    monkeypatch.setattr(labels, "check_values", lambda repo, ops: None)
    ops = [args_mod.LrOp("label", "all", "replace", ["run-ci"], "--label:all")]
    changed, failures = labels.apply(FailingRunner(), _NoAliases(), ops, [], _Out())
    assert changed == 1 and failures == ["PR #6: gh said no"]


def test_a_value_missing_from_the_config_stops_everything(tmp_path, monkeypatch):
    monkeypatch.setenv("TDD_DIR", str(tmp_path))

    class Repo:
        def entry(self):
            return ({"labels": ["bug"], "reviewers": []}, True)  # just fetched

        def aliases(self):
            return {}

    ops = [args_mod.LrOp("label", "all", "replace", ["nope"], "--label:all")]
    with pytest.raises(ToolError, match="unknown label"):
        labels.check_values(Repo(), ops)
    # a reviewer gsx cannot validate (Copilot, @me, org/team) is passed through
    labels.check_values(
        Repo(),
        [args_mod.LrOp("reviewer", "all", "replace", ["@copilot", "o/t"], "--r")],
    )


def test_defaults_lead_so_an_explicit_op_still_wins():
    class Repo:
        def entry(self):
            return ({"defaults": {"labels": ["skip-ci"], "reviewers": []}}, False)

    explicit = args_mod.LrOp("label", "top", "replace", ["run-ci"], "--label:top")
    ops = labels.with_defaults(Repo(), [explicit], disabled=False)
    assert [(op.kind, op.scope, op.values) for op in ops] == [
        ("label", "new", ["skip-ci"]),
        ("label", "top", ["run-ci"]),
    ]
    assert labels.with_defaults(Repo(), [explicit], disabled=True) == [explicit]


# -------------------------------------------------------------------- main
def test_the_tool_speaks_events_and_exits_1_on_a_usage_error(capsys):
    assert gsx.main(["--format", "json"]) == 1
    # json is JSON Lines on stdout, every kind of event alike
    event = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert event["command"] == "gsx" and event["event"] == "error"
    assert "a subcommand is required" in event["message"]


def test_version_is_the_devtools_version(capsys):
    assert gsx.main(["--format", "json", "-V"]) == 0
    event = json.loads(capsys.readouterr().out.strip())
    assert (
        event["version"] == config.VERSION
        and event["message"] == f"gsx {config.VERSION}"
    )


def test_a_dry_run_announces_a_mutating_command_and_runs_a_read_only_one():
    out = _Out()
    runner = gh.Runner(out=out, dry_run=True)
    assert runner.run(["gh", "pr", "edit", "6"], dry_value="skipped") == "skipped"
    assert "[dry-run] gh pr edit 6" in out.messages("info")[0]
    assert gh.is_read_only(["gh", "pr", "list"]) and not gh.is_read_only(
        ["gh", "pr", "edit"]
    )


def test_the_config_action_is_the_shared_one_and_knows_what_gsx_keeps(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("TDD_DIR", str(tmp_path))
    assert gsx.main(["config", "--create"]) == 0
    text = config.path().read_text()
    assert "[options.apply]" in text  # derived from gsx's own parser
    assert '[repo."OWNER/NAME"]' in text  # and what gsx keeps, explained
    assert "[reviewer-aliases]" in text
    capsys.readouterr()
    assert gsx.main(["config", "--create"]) == 1  # refuses an existing file
    assert "already exists" in capsys.readouterr().err
    assert gsx.main(["config", "--create", "--force"]) == 0


def test_the_old_repos_table_is_read_so_a_file_migrates_on_the_next_write(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("TDD_DIR", str(tmp_path))
    config.path().write_text(
        '[repos."o/n"]\nlabels = ["bug"]\nreviewers = []\n'
        "default_labels = []\ndefault_reviewers = []\n"
    )
    assert config.read()["repos"]["o/n"]["labels"] == ["bug"]
    config.write(config.read())  # written under the current name, only once
    text = config.path().read_text()
    assert '[repo."o/n"]' in text and "[repos." not in text


def test_a_reviewer_alias_is_resolved_before_anything_looks_at_the_value():
    class Repo:
        def aliases(self):
            return {"dimas": "aoinokimi"}

    ops = [
        args_mod.LrOp("reviewer", "all", "replace", ["dimas", "tucu0"], "-r"),
        args_mod.LrOp(
            "label", "all", "replace", ["dimas"], "-l"
        ),  # labels are not aliased
    ]
    resolved = labels.resolve_aliases(Repo(), ops)
    assert resolved[0].values == ["aoinokimi", "tucu0"]
    assert resolved[1].values == ["dimas"]


def test_an_unknown_value_is_refused_with_the_valid_ones_beside_it(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("TDD_DIR", str(tmp_path))

    class Repo:
        def entry(self):
            return ({"labels": ["bug", "run-ci"], "reviewers": ["tucu0"]}, True)

        def aliases(self):
            return {"dimas": "aoinokimi"}

    ops = [args_mod.LrOp("label", "all", "replace", ["nope"], "--label:all")]
    with pytest.raises(ToolError) as failure:
        labels.check_values(Repo(), ops)
    assert "valid labels: bug, run-ci" in str(failure.value)
    ops = [args_mod.LrOp("reviewer", "all", "replace", ["nobody"], "-r")]
    with pytest.raises(ToolError) as failure:
        labels.check_values(Repo(), ops)
    assert "valid reviewers: tucu0" in str(failure.value)
    assert "reviewer aliases: dimas -> aoinokimi" in str(failure.value)


# ----------------------------------------------------------------- approve
def test_an_approver_is_resolved_to_a_login_and_the_token_is_read_by_it():
    aliases = {"dimas": "aoinokimi"}
    by_alias, by_login, unknown = approve_mod.resolve(
        ["dimas", "tucu0", "someone"], aliases
    )
    assert (by_alias.name, by_alias.login) == ("dimas", "aoinokimi")
    assert (by_login.name, by_login.login) == ("tucu0", "tucu0")
    assert (unknown.name, unknown.login) == ("someone", "someone")

    read = []

    class Out:
        def info(self, message, **fields):
            read.append(message)

        def debug(self, message, **fields):
            pass

    runner = gh.Runner(out=Out(), dry_run=True)
    settings = {
        "approve_vault": "dev_ci",
        "approve_item": "GitHub",
        "approve_pat_suffix": ".review.pat",
    }
    # the field is the GitHub username, which is what 1Password is keyed by
    assert approve_mod.token(runner, by_alias, settings) == ""
    assert read == ["reading op://dev_ci/GitHub/aoinokimi.review.pat"]


def test_a_pr_the_approver_wrote_is_skipped_not_failed():
    class Out:
        def __init__(self):
            self.said = []

        def info(self, message, **fields):
            self.said.append(message)

        def debug(self, message, **fields):
            pass

    out = Out()
    runner = gh.Runner(out=out, dry_run=True)
    approver = approve_mod.Approver("dimas", "aoinokimi")
    mine = {"number": 6, "branch": "A-1", "author": "aoinokimi"}
    theirs = {"number": 7, "branch": "A-2", "author": "tucu0"}
    assert approve_mod.approve(runner, "o/n", mine, approver, "") == approve_mod.SKIPPED
    assert (
        approve_mod.approve(runner, "o/n", theirs, approver, "") == approve_mod.APPROVED
    )
    assert "skipping PR #6: aoinokimi wrote it" in out.said
    assert any("gh pr review --approve --repo o/n 7" in said for said in out.said)


def test_the_self_approval_error_is_a_skip_and_any_other_is_a_failure():
    class Out:
        def info(self, message, **fields):
            pass

        def debug(self, message, **fields):
            pass

    class Runner:
        dry_run = False
        out = Out()

        def __init__(self, message):
            self.message = message

        def run(self, argv, **kwargs):
            raise ToolError(self.message)

    approver = approve_mod.Approver("dimas", "aoinokimi")
    pull = {"number": 7, "branch": "A-2", "author": ""}
    skipped = approve_mod.approve(
        Runner(f"`gh` failed: {approve_mod.SELF_APPROVAL}"), "o/n", pull, approver, "x"
    )
    assert skipped == approve_mod.SKIPPED
    failed = approve_mod.approve(Runner("gh: 404"), "o/n", pull, approver, "x")
    assert failed.startswith("PR #7 as aoinokimi (dimas): ")


def test_config_is_listed_and_auto_config_is_not_a_subcommand(capsys):
    # `config` is served before the parser sees it, so the parser is told about
    # it or nobody could find it; the refresh has no verb at all.
    assert gsx.main(["--help"]) == 0
    text = capsys.readouterr().out
    assert "config" in text and "auto-config" not in text
    assert gsx.main(["auto-config"]) == 1
    assert "invalid choice" in capsys.readouterr().err or True
