#
# Copyright 2026 Tabsdata Inc.
#

import json
import pathlib

import pytest
from tabsdata_dev.common.core.errors import ToolError
from tabsdata_dev.tool import gsx
from tabsdata_dev.tool.gsx import approve as approve_mod
from tabsdata_dev.tool.gsx import args as args_mod
from tabsdata_dev.tool.gsx.version import VERSION
from tabsdata_dev.tool.gsx import commands, config, gh, labels, progress
from tabsdata_dev.tool.gsx import move as move_mod
from tabsdata_dev.tool.gsx import prune as prune_mod
from tabsdata_dev.tool.gsx import purge as purge_mod
from tabsdata_dev.tool.gsx import hooks as hooks_mod
from tabsdata_dev.tool.gsx import sync as sync_mod


@pytest.fixture(autouse=True)
def _clone_is_prepared(monkeypatch):
    """Every test but the guard's own runs as though `gsx init` has been run.

    The guard is a precondition of the guarded commands rather than part of
    what any of them does, so asserting it in each of their tests would be the
    same fact 20 times. The tests that ARE about it drop this.
    """
    monkeypatch.setenv(gsx.ESCAPE, "1")


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

    def lines(self):
        return [m for _, m in self.events]


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


# ---------------------------------------------------------------- progress
def _three_prs():
    return [
        {"branch": "A-1", "number": 6, "author": "me", "labels": [], "reviewers": []},
        {
            "branch": "A-2",
            "number": 7,
            "author": "you",
            "labels": ["run-ci"],
            "reviewers": [],
        },
        {"branch": "A-3", "number": 8, "author": "me", "labels": [], "reviewers": []},
    ]


def _fake_gh(monkeypatch, tmp_path, snapshot, failing=()):
    """A whole gsx run with every child process faked: no gh, no git, no
    network, and a config file of its own under tmp_path."""
    monkeypatch.setenv("TDD_DIR", str(tmp_path))
    calls = []

    class FakeRunner:
        def __init__(self, out, dry_run=False):
            self.out = out
            self.dry_run = dry_run

        def run(self, argv, **kwargs):
            calls.append(argv)
            if argv[:3] == ["gh", "pr", "edit"] and int(argv[3]) in failing:
                raise ToolError("gh: could not edit it")
            return ""

        def json(self, argv):
            return None

    monkeypatch.setattr(gh, "Runner", FakeRunner)
    monkeypatch.setattr(gh, "require_tools", lambda runner: None)
    monkeypatch.setattr(gh, "repo_slug", lambda runner: "o/n")
    monkeypatch.setattr(gh, "stack_pr_snapshot", lambda runner: snapshot)
    monkeypatch.setattr(
        gh,
        "stack_state",
        lambda runner: {"branches": [{"name": p["branch"]} for p in snapshot]},
    )
    monkeypatch.setattr(labels, "check_values", lambda repo, ops: None)
    return calls


def _counter_lines(text):
    return [
        line
        for line in text.splitlines()
        if line.startswith("[") and not line.startswith("[dry-run")
    ]


def test_the_counter_pads_to_the_total_and_invents_none_when_there_is_no_total():
    out = _Out()
    known = progress.Counter(out, total=10)
    for _ in range(9):
        known.step("a unit")
    known.failed("the tenth")
    open_ended = progress.Counter(out)
    open_ended.step("a unit")
    lines = out.lines()
    assert lines[0] == "[ 1/10] a unit"  # padded, so the column never moves
    assert lines[9] == "[10/10] the tenth"
    assert out.messages("warn") == ["[10/10] the tenth"]  # a failure is a warn
    assert lines[10] == "[1] a unit"  # no total, no denominator invented


def test_apply_numbers_every_pr_of_the_stack_and_keeps_counting_past_a_failure(
    tmp_path, monkeypatch, capsys
):
    """The total is the snapshot: a PR that needs no call and a PR that fails
    each spend their number, so the last line reaches it."""
    _fake_gh(monkeypatch, tmp_path, _three_prs(), failing={8})
    assert gsx.main(["apply", "--label:all", "run-ci", "--no-defaults"]) == 1
    captured = capsys.readouterr()
    assert _counter_lines(captured.err) == [
        "[1/3] updated #6: +label run-ci",
        "[2/3] #7 already as asked",
        "[3/3] #8 could not be updated: gh: could not edit it",
    ]
    # the failures are still collected and reported together at the end
    assert "1 PR(s) could not be updated: PR #8" in captured.err


def test_the_same_run_in_json_carries_the_counter_in_the_fields(
    tmp_path, monkeypatch, capsys
):
    _fake_gh(monkeypatch, tmp_path, _three_prs(), failing={8})
    argv = ["apply", "--label:all", "run-ci", "--no-defaults", "--format", "json"]
    assert gsx.main(argv) == 1
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    steps = [event for event in events if "n" in event]
    assert [
        (event["event"], event["n"], event["total"], event["pr"], event["outcome"])
        for event in steps
    ] == [
        ("info", 1, 3, 6, "updated"),
        ("info", 2, 3, 7, "unchanged"),
        ("warn", 3, 3, 8, "failed"),
    ]
    # the counter is in the message, the step is in the fields
    assert steps[0]["message"] == "[1/3] updated #6: +label run-ci"
    assert steps[0]["edits"] == ["+label run-ci"]
    assert events[-1]["event"] == "error"


def test_submit_counts_without_a_total_because_its_prs_do_not_exist_yet(
    tmp_path, monkeypatch, capsys
):
    """A submit may be opening the PRs it is about to label, so it cannot know
    how many units it has; it counts [n] rather than guess a denominator."""
    _fake_gh(monkeypatch, tmp_path, _three_prs())
    assert gsx.main(["submit", "--label:all", "run-ci", "--no-defaults"]) == 0
    assert _counter_lines(capsys.readouterr().err) == [
        "[1] pushed the stack and opened its PRs",
        "[2] updated #6: +label run-ci",
        "[3] #7 already as asked",
        "[4] updated #8: +label run-ci",
    ]


def test_approve_counts_every_approver_against_every_pr(tmp_path, monkeypatch, capsys):
    _fake_gh(monkeypatch, tmp_path, _three_prs()[:2])
    argv = ["approve", "--approvers", "tucu0,me", "--pr", "6,7", "--dry-run"]
    assert gsx.main(argv) == 0
    assert _counter_lines(capsys.readouterr().err) == [
        "[1/4] approved #6 as tucu0",
        "[2/4] approved #7 as tucu0",
        "[3/4] skipped #6: me wrote it",
        "[4/4] approved #7 as me",
    ]


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
    out = _Out()
    runner = gh.Runner(out=out, dry_run=True)
    steps = progress.Counter(out, total=2)
    approver = approve_mod.Approver("dimas", "aoinokimi")
    mine = {"number": 6, "branch": "A-1", "author": "aoinokimi"}
    theirs = {"number": 7, "branch": "A-2", "author": "tucu0"}
    assert (
        approve_mod.approve(runner, "o/n", mine, approver, "", steps)
        == approve_mod.SKIPPED
    )
    assert (
        approve_mod.approve(runner, "o/n", theirs, approver, "", steps)
        == approve_mod.APPROVED
    )
    said = out.messages("info")
    # a skip is an outcome, not an absence: it spends its number and says why
    assert "[1/2] skipped #6: aoinokimi wrote it" in said
    assert "[2/2] approved #7 as aoinokimi (dimas)" in said
    assert any("gh pr review --approve --repo o/n 7" in message for message in said)


def test_the_self_approval_error_is_a_skip_and_any_other_is_a_failure():
    class Runner:
        dry_run = False

        def __init__(self, message):
            self.message = message
            self.out = _Out()

        def run(self, argv, **kwargs):
            raise ToolError(self.message)

    approver = approve_mod.Approver("dimas", "aoinokimi")
    pull = {"number": 7, "branch": "A-2", "author": ""}
    runner = Runner(f"`gh` failed: {approve_mod.SELF_APPROVAL}")
    skipped = approve_mod.approve(
        runner, "o/n", pull, approver, "x", progress.Counter(runner.out, total=1)
    )
    assert skipped == approve_mod.SKIPPED
    assert runner.out.messages("info") == ["[1/1] skipped #7: it is aoinokimi's own"]

    runner = Runner("gh: 404")
    failed = approve_mod.approve(
        runner, "o/n", pull, approver, "x", progress.Counter(runner.out, total=1)
    )
    assert failed.startswith("PR #7 as aoinokimi (dimas): ")
    # the failure is a warn as it happens, and still spends its number
    assert runner.out.messages("warn") == [
        "[1/1] #7 was not approved as aoinokimi (dimas): gh: 404"
    ]


def test_config_is_listed_and_auto_config_is_not_a_subcommand(capsys):
    # `config` is served before the parser sees it, so the parser is told about
    # it or nobody could find it; the refresh has no verb at all.
    assert gsx.main(["--help"]) == 0
    text = capsys.readouterr().out
    assert "config" in text and "auto-config" not in text
    assert gsx.main(["auto-config"]) == 1
    assert "invalid choice" in capsys.readouterr().err or True


# ------------------------------------------------------------------- purge
def _pr(number, state, branch=None):
    payload = {"number": number, "state": state}
    if branch is not None:
        payload["headRefName"] = branch
    return payload


def test_the_trunk_and_the_never_candidates_are_not_up_for_deletion():
    """`main`/`master` are refused whatever the trunk is: a repository whose
    default branch is `develop` still should not lose `main`."""
    branches = ["main", "master", "develop", "GCS-15", "scratch"]
    assert purge_mod.candidates(branches, "develop") == ["GCS-15", "scratch"]
    # and with gh unable to say what the trunk is, the fixed names still hold
    assert purge_mod.candidates(branches, "") == ["develop", "GCS-15", "scratch"]


@pytest.mark.parametrize(
    "pulls, outcome, reason",
    [
        ([_pr(21, "MERGED")], purge_mod.DELETED, "merged #21"),
        ([_pr(23, "CLOSED")], purge_mod.DELETED, "closed #23"),
        ([], purge_mod.KEPT, "no PR"),
        ([_pr(30, "OPEN")], purge_mod.KEPT, "open PR #30"),
        # a reopened branch: an older PR was merged, but one is open NOW
        ([_pr(21, "MERGED"), _pr(30, "OPEN")], purge_mod.KEPT, "open PR #30"),
        # a second attempt after the first was closed: the newest one decides
        ([_pr(21, "CLOSED"), _pr(30, "MERGED")], purge_mod.DELETED, "merged #30"),
        # a state gsx does not know is a reason to do nothing
        ([_pr(31, "DRAFTED")], purge_mod.KEPT, "PR #31 is DRAFTED"),
    ],
)
def test_github_decides_and_an_open_pr_anywhere_keeps_the_branch(
    pulls, outcome, reason
):
    verdict = purge_mod.classify("GCS-15", pulls, merged_only=False, checked_out=False)
    assert (verdict.outcome, verdict.reason) == (outcome, reason)


def test_merged_only_spares_a_branch_whose_pr_was_closed_unmerged():
    """A closed PR's commits were never merged anywhere, so the branch is the
    only copy -- which is worth an option even though the default deletes it."""
    closed = [_pr(23, "CLOSED")]
    assert (
        purge_mod.classify(
            "GCS-16", closed, merged_only=True, checked_out=False
        ).outcome
        == purge_mod.KEPT
    )
    assert (
        purge_mod.classify(
            "GCS-16", closed, merged_only=False, checked_out=False
        ).outcome
        == purge_mod.DELETED
    )


def test_the_checked_out_branch_is_kept_and_says_how_to_delete_it():
    """git refuses to delete the current branch, and its message does not say
    which one to switch to. This does."""
    verdict = purge_mod.classify(
        "GCS-15", [_pr(21, "MERGED")], merged_only=False, checked_out=True
    )
    assert verdict.outcome == purge_mod.KEPT
    assert "checked out" in verdict.reason and "merged #21" in verdict.reason


def _fake_purge(monkeypatch, tmp_path, branches, pulls, current="main", failing=()):
    """A whole purge run with git and gh faked: the branches are `branches`,
    the repository's PRs are `pulls` (branch -> list), and `failing` names the
    branches whose `git branch -D` refuses."""
    monkeypatch.setenv("TDD_DIR", str(tmp_path))
    calls = []

    class FakeRunner:
        def __init__(self, out, dry_run=False):
            self.out = out
            self.dry_run = dry_run

        def run(self, argv, **kwargs):
            calls.append(argv)
            if argv[:3] == ["git", "branch", "-D"] and argv[3] in failing:
                raise ToolError("git: worktree has it checked out")
            if argv[:2] == ["git", "for-each-ref"]:
                return "\n".join(branches)
            if argv[:2] == ["git", "rev-parse"]:
                return current
            return ""

        def json(self, argv):
            return None

    monkeypatch.setattr(gh, "Runner", FakeRunner)
    monkeypatch.setattr(gh, "require_binaries", lambda: None)
    # every command looks for a move in progress first; here there is none
    monkeypatch.setattr(gh, "git_dir", lambda runner: tmp_path)
    monkeypatch.setattr(gh, "default_branch", lambda runner: "main")
    monkeypatch.setattr(gh, "prs_by_branch", lambda runner, limit=500: pulls)
    monkeypatch.setattr(gh, "branch_prs", lambda runner, branch: [])
    return calls


def test_purge_deletes_what_github_is_done_with_and_numbers_every_branch(
    tmp_path, monkeypatch, capsys
):
    """Every candidate branch spends a number, kept ones included -- the report
    IS the value of the command, and a run that only counted deletions would
    not say why the others survived."""
    calls = _fake_purge(
        monkeypatch,
        tmp_path,
        ["main", "GCS-15", "GCS-16", "GCS-20", "scratch"],
        {
            "GCS-15": [_pr(21, "MERGED")],
            "GCS-16": [_pr(23, "CLOSED")],
            "GCS-20": [_pr(30, "OPEN")],
        },
    )
    assert gsx.main(["purge"]) == 0
    captured = capsys.readouterr()
    assert _counter_lines(captured.err) == [
        "[1/4] deleted GCS-15: merged #21",
        "[2/4] deleted GCS-16: closed #23",
        "[3/4] kept GCS-20: open PR #30",
        "[4/4] kept scratch: no PR",
    ]
    # only the two, and with -D: -d refuses a squash-merged branch
    assert [c for c in calls if c[:2] == ["git", "branch"]] == [
        ["git", "branch", "-D", "GCS-15"],
        ["git", "branch", "-D", "GCS-16"],
    ]
    assert ["git", "fetch", "--prune"] in calls
    assert "deleted 2 branch(es), kept 2" in captured.out


def test_purge_attempts_every_branch_and_reports_the_failures_together(
    tmp_path, monkeypatch, capsys
):
    calls = _fake_purge(
        monkeypatch,
        tmp_path,
        ["main", "GCS-15", "GCS-16"],
        {"GCS-15": [_pr(21, "MERGED")], "GCS-16": [_pr(23, "MERGED")]},
        failing={"GCS-15"},
    )
    assert gsx.main(["purge"]) == 1
    captured = capsys.readouterr()
    assert _counter_lines(captured.err) == [
        "[1/2] could not delete GCS-15: git: worktree has it checked out",
        "[2/2] deleted GCS-16: merged #23",
    ]
    # the second was still attempted, and the failure is reported once at the end
    assert ["git", "branch", "-D", "GCS-16"] in calls
    assert "1 branch(es) could not be deleted: GCS-15" in captured.err


def test_a_dry_run_of_purge_says_what_it_would_delete_and_deletes_nothing():
    """`git branch` LISTS, so it sits in the read-only set -- but the same word
    deletes, and a dry run that ran the delete would be the one mistake the
    flag exists to prevent."""
    out = _Out()
    runner = gh.Runner(out=out, dry_run=True)
    runner.run(["git", "branch", "-D", "GCS-15"])
    assert "[dry-run] git branch -D GCS-15" in out.messages("info")[0]
    assert not gh.is_read_only(["git", "branch", "-D", "GCS-15"])
    assert not gh.is_read_only(["git", "branch", "--delete", "GCS-15"])
    assert gh.is_read_only(["git", "branch", "--list"])
    assert gh.is_read_only(["git", "for-each-ref", "--format=%(refname:short)"])


def test_purge_needs_git_and_gh_but_not_the_gh_stack_extension(
    tmp_path, monkeypatch, capsys
):
    """A leftover branch is a leftover whether a stack put it there or not, so
    demanding the extension would refuse a repository that never used one."""
    _fake_purge(monkeypatch, tmp_path, ["main", "GCS-15"], {})
    monkeypatch.setattr(
        gh,
        "require_tools",
        lambda runner: (_ for _ in ()).throw(ToolError("gh-stack is not installed")),
    )
    assert gsx.main(["purge"]) == 0
    assert "nothing deleted" in capsys.readouterr().out


def test_purge_carries_its_verdicts_in_the_json_fields(tmp_path, monkeypatch, capsys):
    _fake_purge(
        monkeypatch,
        tmp_path,
        ["main", "GCS-15", "GCS-20"],
        {"GCS-15": [_pr(21, "MERGED")], "GCS-20": [_pr(30, "OPEN")]},
    )
    assert gsx.main(["purge", "--format", "json"]) == 0
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    steps = [event for event in events if "branch" in event]
    assert [(e["n"], e["total"], e["branch"], e["outcome"]) for e in steps] == [
        (1, 2, "GCS-15", "deleted"),
        (2, 2, "GCS-20", "kept"),
    ]
    assert events[-1]["deleted"] == ["GCS-15"] and events[-1]["kept"] == ["GCS-20"]


def test_purge_takes_no_passthrough_because_it_drives_nothing_worth_one():
    assert args_mod.NATIVES["purge"] == []
    with pytest.raises(ToolError, match="accepts: none"):
        args_mod.split(["purge", "--e:draft"], args_mod.PURGE_NATIVES, False)
    # its own options are argparse's and pass straight through
    rest, extras = args_mod.split(
        ["purge", "--merged-only", "--no-fetch"], args_mod.PURGE_NATIVES, False
    )
    assert rest == ["purge", "--merged-only", "--no-fetch"] and not extras.passthrough


# ---------------------------------------------------------------- checkout
@pytest.mark.parametrize(
    "target, kind, value",
    [
        ("#42", "pr", "42"),
        (" #42 ", "pr", "42"),
        ("GCS-15", "branch", "GCS-15"),
        ("feat/api-routes", "branch", "feat/api-routes"),
    ],
)
def test_a_checkout_target_is_a_branch_name_or_a_hash_number(target, kind, value):
    assert commands.parse_checkout_target(target) == (kind, value)


@pytest.mark.parametrize(
    "target, message",
    [
        # the whole point: gh tries a bare number as a stack number FIRST, so
        # `42` does not reliably mean the PR the reader had in mind
        ("42", "ambiguous"),
        ("https://github.com/o/n/pull/42", "#42"),
        ("http://example.com/x", "#<PR>"),
        ("#", "not a pull request"),
        ("#abc", "not a pull request"),
        ("   ", "needs a branch name"),
    ],
)
def test_every_other_shape_is_refused_and_says_what_to_write(target, message):
    with pytest.raises(ToolError, match=message):
        commands.parse_checkout_target(target)


def test_a_pr_target_reaches_gh_as_a_url_because_a_bare_number_would_not(
    tmp_path, monkeypatch, capsys
):
    """`#42` has to mean pull request 42. A bare 42 would be tried as stack 42
    first, so the URL -- the one shape gh cannot read as anything else -- is
    what makes the promise true. It is refused as INPUT and used as output."""
    calls = _fake_purge(monkeypatch, tmp_path, ["main"], {})
    monkeypatch.setattr(gh, "require_tools", lambda runner: None)
    monkeypatch.setattr(gh, "repo_url", lambda runner: "https://github.com/o/n")
    monkeypatch.setattr(gh, "current_pr", lambda runner: 42)

    assert gsx.main(["checkout", "#42"]) == 0
    assert ["gh", "stack", "checkout", "https://github.com/o/n/pull/42"] in calls
    assert "checking out PR #42" in capsys.readouterr().err

    calls.clear()
    assert gsx.main(["checkout", "GCS-15"]) == 0
    # a branch name goes as it was typed, and gh never sees a number
    assert ["gh", "stack", "checkout", "GCS-15"] in calls
    assert "checking out branch GCS-15" in capsys.readouterr().err

    calls.clear()
    assert gsx.main(["checkout"]) == 0
    assert ["gh", "stack", "checkout"] in calls


def test_checkout_dry_runs_without_clashing_with_the_runners_own_field(
    tmp_path, monkeypatch, capsys
):
    """`dry_run` is on every ok event already, so a command that returned one
    of its own made `ok()` get the keyword twice -- a TypeError, on the one
    flag whose whole job is to be safe to try."""
    calls = _fake_purge(monkeypatch, tmp_path, ["main"], {})
    monkeypatch.setattr(gh, "require_tools", lambda runner: None)
    monkeypatch.setattr(gh, "repo_url", lambda runner: "https://github.com/o/n")
    argv = ["checkout", "#42", "--dry-run", "--format", "json"]
    assert gsx.main(argv) == 0
    last = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert last["event"] == "ok" and last["dry_run"] is True
    # what the flag SKIPS is the real Runner's business, and is covered where
    # the real one is used; this fake records every call it is handed.
    assert calls


def _fake_checkout(monkeypatch, tmp_path, refuse=(), pulls=(), saying="", stacks=()):
    """A checkout run where `gh stack checkout` refuses the argv prefixes in
    `refuse`, the way it refuses a branch of a stack this checkout does not
    track: exit 2, "no locally tracked stack found". `saying` is appended to
    the refusal, for the other exit-2 gh has: "not part of a stack"."""
    monkeypatch.setenv("TDD_DIR", str(tmp_path))
    calls = []

    class FakeRunner:
        def __init__(self, out, dry_run=False):
            self.out = out
            self.dry_run = dry_run

        def run(self, argv, **kwargs):
            calls.append(argv)
            for prefix in refuse:
                if argv[: len(prefix)] == prefix:
                    raise ToolError(
                        f"`{' '.join(argv)}` failed (exit 2)"
                        + (f": {saying}" if saying else "")
                    )
            return ""

        def json(self, argv):
            return None

    monkeypatch.setattr(gh, "Runner", FakeRunner)
    monkeypatch.setattr(gh, "require_tools", lambda runner: None)
    # every command looks for a move in progress first; here there is none
    monkeypatch.setattr(gh, "git_dir", lambda runner: tmp_path)
    monkeypatch.setattr(gh, "repo_url", lambda runner: "https://github.com/o/n")
    monkeypatch.setattr(gh, "current_branch", lambda runner: "OS-3348")
    monkeypatch.setattr(gh, "current_pr", lambda runner: None)
    monkeypatch.setattr(gh, "branch_prs", lambda runner, branch: list(pulls))
    monkeypatch.setattr(gh, "default_branch", lambda runner: "main")
    # what GitHub's listing answers, which is how a failed stack checkout is
    # told apart from a PR that is in no stack at all
    monkeypatch.setattr(gh, "stacks", lambda runner, **kw: list(stacks))
    return calls


def test_a_pr_that_is_in_no_stack_is_checked_out_on_its_own(
    tmp_path, monkeypatch, capsys
):
    """The asymmetry gsx has to absorb: a stack on GitHub needs two PRs, so a
    single-branch stack submits as a PR and no stack -- and every `gh stack
    checkout` path is stack-shaped. Measured in tabsdata-ui: `gsx checkout
    UI-485` failed twice, once per path, on a PR that was there all along."""
    calls = _fake_checkout(
        monkeypatch,
        tmp_path,
        refuse=[["gh", "stack", "checkout"]],
        pulls=[{"number": 486, "state": "OPEN", "headRefName": "UI-485"}],
    )
    assert gsx.main(["checkout", "UI-485"]) == 0
    assert calls == [
        ["gh", "stack", "checkout", "UI-485"],  # not tracked here
        ["gh", "stack", "checkout", "https://github.com/o/n/pull/486"],  # no stack
        ["git", "rev-parse", "-q", "--verify", "refs/heads/UI-485"],  # not here
        ["gh", "pr", "checkout", "486"],  # ...so plain git, through gh
        ["gh", "stack", "init", "--base", "main", "UI-485"],
    ]
    said = capsys.readouterr().err
    assert "PR #486 is in no stack on GitHub -- a stack needs two PRs" in said
    assert "tracked UI-485 here as the stack of one it is" in said


def test_the_pr_form_reaches_the_same_place(tmp_path, monkeypatch, capsys):
    """`#486` resolves straight to the PR, and the PR is in no stack: the same
    asymmetry by its other name, so the same way out."""
    calls = _fake_checkout(monkeypatch, tmp_path, refuse=[["gh", "stack", "checkout"]])
    monkeypatch.setattr(gh, "pr_branch", lambda runner, number: "UI-485")
    assert gsx.main(["checkout", "#486"]) == 0
    assert ["gh", "pr", "checkout", "486"] in calls
    assert ["gh", "stack", "init", "--base", "main", "UI-485"] in calls


def test_a_branch_already_here_is_only_switched_to(tmp_path, monkeypatch, capsys):
    """Nothing to fetch, so nothing is fetched -- and `gh pr checkout` on a
    branch that already has local commits is not a thing to find out about."""
    calls = _fake_checkout(
        monkeypatch,
        tmp_path,
        refuse=[["gh", "stack", "checkout"]],
        pulls=[{"number": 486, "state": "OPEN", "headRefName": "UI-485"}],
    )
    monkeypatch.setattr(gh, "sha", lambda runner, ref: "sha-UI-485")
    assert gsx.main(["checkout", "UI-485"]) == 0
    assert ["git", "checkout", "-q", "UI-485"] in calls
    assert not any(call[:3] == ["gh", "pr", "checkout"] for call in calls)


def test_a_pr_already_tracked_here_is_not_re_initialised(tmp_path, monkeypatch):
    """`gh stack init` refuses a branch that is already in a tracked stack, and
    the whole point of the step is to leave the branch tracked."""
    calls = _fake_checkout(
        monkeypatch,
        tmp_path,
        refuse=[["gh", "stack", "checkout"]],
        pulls=[{"number": 486, "state": "OPEN", "headRefName": "UI-485"}],
    )
    (tmp_path / "gh-stack").write_text(
        json.dumps(_tracked((None, "main", [("UI-485", 486)])))
    )
    assert gsx.main(["checkout", "UI-485"]) == 0
    assert not any(call[:3] == ["gh", "stack", "init"] for call in calls)


def test_a_stack_checkout_that_failed_for_any_other_reason_still_fails(
    tmp_path, monkeypatch, capsys
):
    """Taking the branch alone would leave a one-branch stack that
    misrepresents GitHub, so the fallback is earned by the listing saying there
    is no stack -- here it says there is one, and the failure stands."""
    _fake_checkout(
        monkeypatch,
        tmp_path,
        refuse=[["gh", "stack", "checkout"]],
        pulls=[{"number": 486, "state": "OPEN", "headRefName": "UI-485"}],
        saying="could not resolve host: api.github.com",
        stacks=[_listed(41, [(486, "UI-485")])],
    )
    assert gsx.main(["checkout", "UI-485"]) == 1
    assert "could not resolve host" in capsys.readouterr().err


def test_a_branch_this_checkout_does_not_track_is_reached_through_its_pr(
    tmp_path, monkeypatch, capsys
):
    """`gh stack checkout BRANCH` only resolves a branch of a stack already
    tracked here; for any other branch it exits 2 and says to use the PR
    number. In a fresh clone that is every branch, so `gsx checkout OS-3348`
    could not work -- it takes gh's advice now."""
    calls = _fake_checkout(
        monkeypatch,
        tmp_path,
        refuse=[["gh", "stack", "checkout", "OS-3348"]],
        pulls=[{"number": 3442, "state": "OPEN"}],
    )
    assert gsx.main(["checkout", "OS-3348"]) == 0
    assert calls == [
        ["gh", "stack", "checkout", "OS-3348"],  # the tracked case, tried first
        ["gh", "stack", "checkout", "https://github.com/o/n/pull/3442"],
    ]
    assert "not in a stack tracked here; pulling it down by PR #3442" in (
        capsys.readouterr().err
    )


def test_a_branch_with_no_pr_at_all_is_gits_business_not_this_commands(
    tmp_path, monkeypatch, capsys
):
    _fake_checkout(
        monkeypatch, tmp_path, refuse=[["gh", "stack", "checkout", "scratch"]]
    )
    assert gsx.main(["checkout", "scratch"]) == 1
    said = capsys.readouterr().err
    assert "gh knows no PR for it" in said and "git switch scratch" in said


def test_a_pr_target_that_gh_refuses_is_not_retried_as_anything_else(
    tmp_path, monkeypatch, capsys
):
    """The fallback exists because a branch name has a second reading. `#42`
    has only one, so a failure there is the answer."""
    calls = _fake_checkout(monkeypatch, tmp_path, refuse=[["gh", "stack", "checkout"]])
    assert gsx.main(["checkout", "#42"]) == 1
    assert len(calls) == 1 and "failed (exit 2)" in capsys.readouterr().err


def test_a_refused_checkout_target_costs_no_child_process(tmp_path, monkeypatch):
    """A target gsx will not accept is a usage error, so it is settled before
    gh is asked anything -- including the extension check."""
    calls = _fake_purge(monkeypatch, tmp_path, ["main"], {})
    monkeypatch.setattr(
        gh,
        "require_tools",
        lambda runner: (_ for _ in ()).throw(ToolError("should not get here")),
    )
    assert gsx.main(["checkout", "42"]) == 1
    assert calls == []


def _landed_stack(open_prs=("c1", "c2"), landed=("a1", "a2", "b1")):
    """One tracked stack whose bottom has landed: `(number, trunk, entries)`
    with a PR per branch, numbered from 40."""
    names = [*landed, *open_prs]
    return _tracked((52, "main", [(name, 40 + n) for n, name in enumerate(names)]))


def _states(landed=3, total=5, first=40):
    return {
        first + n: {"state": "MERGED" if n < landed else "OPEN"} for n in range(total)
    }


def test_prune_drops_the_landed_pull_requests_and_keeps_the_rest():
    plan = prune_mod.build(_landed_stack()["stacks"][0], _states())
    assert plan.number == 52 and plan.trunk == "main"
    assert plan.drop == [("a1", 40), ("a2", 41), ("b1", 42)]
    assert plan.keep == [("c1", 43), ("c2", 44)]
    assert plan.prs == [43, 44] and plan.branches == ["c1", "c2"]
    text = plan.text()
    assert "gh stack unstack 52   # on GitHub, irreversible" in text
    assert "gh stack link 43 44" in text
    assert "gh stack init --base main c1 c2" in text
    assert "#52 is lost" in text and "No PR number changes" in text


def test_prune_keeps_a_branch_that_has_no_pr_yet():
    """Not history and not landed: work that has not been submitted. It cannot
    be linked on GitHub -- there is nothing there to link -- but dropping it
    from the local stack would lose the arrangement it is part of."""
    stack = _landed_stack()["stacks"][0]
    stack["branches"].append({"branch": "d1", "pullRequest": None})
    plan = prune_mod.build(stack, _states())
    assert plan.untracked == ["d1"] and plan.prs == [43, 44]
    assert plan.branches == ["c1", "c2", "d1"]
    assert "d1   # no PR yet" in plan.text()


def test_prune_will_not_spend_a_stack_number_for_nothing():
    with pytest.raises(ToolError, match="every PR of stack #52 is still open"):
        prune_mod.build(_landed_stack()["stacks"][0], _states(landed=0))


def test_prune_needs_the_stack_to_be_on_github_at_all():
    stack = dict(_landed_stack()["stacks"][0], number=None)
    with pytest.raises(ToolError, match="not on GitHub yet"):
        prune_mod.build(stack, _states())


def test_prune_says_a_pr_it_cannot_ask_about_is_kept():
    """A missing answer is not certainty, and prune only drops what is
    certainly finished."""
    plan = prune_mod.build(_landed_stack()["stacks"][0], {40: {"state": "MERGED"}})
    assert plan.drop == [("a1", 40)] and len(plan.keep) == 4


def test_a_remainder_too_small_to_be_a_stack_is_only_dissolved():
    plan = prune_mod.build(
        _landed_stack(open_prs=("c1",), landed=("a1", "a2"))["stacks"][0],
        _states(landed=2, total=3),
    )
    assert plan.links is False
    assert "a stack needs 2 PRs and 1 would be left" in plan.text()


def test_prune_dissolves_then_links_then_tracks_it_here(tmp_path, monkeypatch, capsys):
    """The order is forced: `gh stack link` rejects a PR that belongs to
    another stack, so the old one goes first."""
    state = _landed_stack()
    calls = _fake_move(monkeypatch, tmp_path, state, current="c1")
    monkeypatch.setattr(gh, "pull_requests", lambda runner, numbers: _states())
    monkeypatch.setattr(
        gh, "stacks", lambda runner, **kw: [_listed(61, [(43, "c1"), (44, "c2")])]
    )
    assert gsx.main(["prune", "--yes"]) == 0
    stack_calls = [call for call in calls if call[:2] == ["gh", "stack"]]
    assert stack_calls == [
        ["gh", "stack", "unstack", "52"],
        ["gh", "stack", "link", "43", "44"],
        ["gh", "stack", "unstack", "--local"],
        ["gh", "stack", "init", "--base", "main", "c1", "c2"],
    ]
    said = capsys.readouterr().out
    assert "its open PRs are stack #61 now" in said
    assert "3 merged or closed PR(s) dropped" in said
    # nothing pushed, and link was never handed a branch name
    assert not any("push" in " ".join(call) for call in calls)
    assert not any(
        call[:3] == ["gh", "stack", "link"] and "c1" in call for call in calls
    )


def test_prune_is_refused_while_a_move_is_unpublished(tmp_path, monkeypatch, capsys):
    """Prune dissolves a stack on GitHub, and until the move is published the
    two sides disagree about which PRs live together."""
    _fake_move(monkeypatch, tmp_path, _landed_stack(), current="c1")
    move_mod.save(
        gh.Runner(out=_Out()),
        move_mod.Session(
            stage=move_mod.PUBLISH,
            started_on="c1",
            moving=["c1"],
            target="x",
            onto="x",
            upstream="sha",
            tips={},
            tracking=None,
            moves=[{"moving": ["c1"], "onto": "x", "from": "c1"}],
        ),
    )
    assert gsx.main(["prune", "--yes"]) == 1
    said = capsys.readouterr().err
    assert "not published" in said and "prune after that" in said


def test_prune_needs_a_stack_to_stand_in(tmp_path, monkeypatch, capsys):
    _fake_move(monkeypatch, tmp_path, {"stacks": []}, current="c1")
    assert gsx.main(["prune", "--yes"]) == 1
    assert "is not in any stack tracked here" in capsys.readouterr().err


# -------------------------------------------------------------------- move
def _tracked(*stacks):
    """gh-stack's tracking file, from `(number, trunk, [(branch, pr), ...])`."""
    return {
        "stacks": [
            {
                "number": number,
                "trunk": {"branch": trunk},
                "branches": [
                    {
                        "branch": branch,
                        "pullRequest": {"number": pr} if pr else None,
                    }
                    for branch, pr in entries
                ],
            }
            for number, trunk, entries in stacks
        ]
    }


#: The two stacks most of these use: #44 = a1 <- a2, #36 = b1 <- b2 <- b3.
def _two():
    return _tracked(
        (44, "main", [("a1", 42), ("a2", 43)]),
        (36, "main", [("b1", 24), ("b2", 25), ("b3", 26)]),
    )


class _MoveRunner:
    """git and gh for the planner and the driver: every branch exists, every
    command is remembered, and nothing has an opinion of its own."""

    dry_run = False

    def __init__(self, out=None, heads=(), git_dir=None):
        self.out = out or _Out()
        self.heads = {f"refs/heads/{name}": f"sha-{name}" for name in heads}
        self.git_dir = git_dir
        self.calls = []

    def run(self, argv, **kwargs):
        self.calls.append(argv)
        if argv[:3] == ["git", "rev-parse", "--git-dir"]:
            return str(self.git_dir)
        if argv[:3] == ["git", "rev-parse", "-q"]:
            return self.heads.get(argv[-1], "")
        if argv[:2] == ["git", "for-each-ref"]:
            return "\n".join(
                f"{ref.rsplit('/', 1)[-1]} {sha}" for ref, sha in self.heads.items()
            )
        if argv[:2] == ["git", "config"]:
            return ""
        return ""

    def json(self, argv):
        return None

    def stack_calls(self):
        return [call for call in self.calls if call[:2] == ["gh", "stack"]]


def test_you_move_out_of_the_stack_you_are_standing_in():
    source = move_mod.source_stack(_two(), "a1")
    assert (source.number, source.trunk, source.index) == (44, "main", 1)
    assert source.moving == ["a1", "a2"] and source.keep == []
    source = move_mod.source_stack(_two(), "a2")
    assert source.moving == ["a2"] and source.keep == ["a1"]
    assert source.moving_prs == [43]


@pytest.mark.parametrize(
    "branch, message",
    [
        ("nowhere", "not in any stack tracked here"),
        ("main", "not in any stack tracked here"),
    ],
)
def test_a_branch_with_no_stack_of_its_own_cannot_be_moved(branch, message):
    with pytest.raises(ToolError, match=message):
        move_mod.source_stack(_two(), branch)


def test_standing_on_a_trunk_that_is_listed_in_the_stack_is_refused():
    """gh-stack usually keeps the trunk out of `.branches[]`; when it does not,
    standing on it is still not a branch that can be moved."""
    state = _tracked((44, "main", [("main", None), ("a1", 42)]))
    with pytest.raises(ToolError, match="on the trunk"):
        move_mod.source_stack(state, "main")


def test_a_branch_in_two_tracked_stacks_is_refused_rather_than_guessed():
    state = _two()
    state["stacks"].append(
        {"number": 45, "trunk": {"branch": "main"}, "branches": [{"branch": "a2"}]}
    )
    with pytest.raises(ToolError, match="several stacks tracked here"):
        move_mod.source_stack(state, "a2")


def _target(runner, value, branch="a1", state=None, out=None):
    state = state or _two()
    source = move_mod.source_stack(state, branch)
    return move_mod.resolve_target(runner, value, source, state, "main", out or _Out())


def test_to_takes_a_stack_number_its_top_branch_the_trunk_or_a_plain_pr():
    runner = _MoveRunner(heads=["a1", "a2", "b1", "b2", "b3", "plain", "main"])

    # a stack by number: the moved branches go on top of its top branch
    target = _target(runner, "#36")
    assert (target.mode, target.head, target.number) == (move_mod.STACK, "b3", 36)
    assert target.branches == ["b1", "b2", "b3"] and target.trunk == "main"
    # ...and by that branch's name, which is the same thing said differently
    assert _target(runner, "b3").branches == ["b1", "b2", "b3"]

    # a branch whose PR is in no stack: the two become one stack
    out = _Out()
    target = _target(runner, "plain", out=out)
    assert (target.mode, target.head, target.branches) == (
        move_mod.PLAIN,
        "plain",
        ["plain"],
    )
    assert "in no stack tracked here" in " ".join(out.lines())

    # the trunk: a stack of the moved branches alone
    target = _target(runner, "main", branch="a2")
    assert (target.mode, target.head, target.branches) == (move_mod.TRUNK, "main", [])


@pytest.mark.parametrize(
    "value, branch, message",
    [
        # the whole point of the two rules the operator asked for
        ("#99", "a1", "not tracked in this checkout"),
        ("b2", "a1", "not the top of its stack"),
        # the stack you are standing in, named either way
        ("#44", "a1", "the stack you are standing in"),
        ("a2", "a1", "the stack you are moving out of"),
        # nothing to move: you are the bottom and the trunk is already below
        ("main", "a1", "already the bottom"),
        ("#abc", "a1", "not a stack number"),
        ("gone", "a1", "does not exist here"),
    ],
)
def test_a_target_that_cannot_be_moved_onto_is_refused(value, branch, message):
    runner = _MoveRunner(heads=["a1", "a2", "b1", "b2", "b3", "main"])
    with pytest.raises(ToolError, match=message):
        _target(runner, value, branch=branch)


def test_the_plan_is_local_commands_and_says_so():
    runner = _MoveRunner(heads=["a1", "a2", "b1", "b2", "b3", "main"])
    source = move_mod.source_stack(_two(), "a2")
    plan = move_mod.build(source, _target(runner, "#36", branch="a2"))
    assert plan.dest_init == ["b1", "b2", "b3", "a2"] and plan.dest_base == "main"
    assert plan.keep_init == ["a1"] and plan.parent == "a1"
    assert plan.steps == [
        "gh stack unstack --local   # forget #44",
        "gh stack checkout b3 && gh stack unstack --local   # ...and #36",
        "git checkout main && gh stack init --base main a1   # what stays below",
        "git checkout main && gh stack init --base main b1 b2 b3 a2   # the destination",
        # off the branch it used to sit on, which is the only range that is its
        # own commits
        "git rebase --onto b3 a1 a2   # replay a2, off a1",
        "git checkout a2",
    ]
    text = move_mod.text(plan)
    assert "stay : a1" in text and "move : a2" in text
    assert "all local; `gsx submit --move` is what publishes it" in text
    assert "push" not in text and "unstack --local" in text


def test_more_than_one_moved_branch_hands_the_rest_to_the_cascade():
    """The bottom is plain git -- its parent changed, and only this command
    knows what it used to be. Everything above it still sits on the branch
    below, whose recorded base is that branch's own old tip, so gh-stack's
    cascade has the ranges right. `--upstack` is what keeps it to those:
    without it the cascade starts at the bottom of the whole stack."""
    runner = _MoveRunner(heads=["a1", "a2", "a3", "b1", "main"])
    state = _tracked((44, "main", [("a1", 42), ("a2", 43), ("a3", 44)]))
    state["stacks"].append(
        {"number": 36, "trunk": {"branch": "main"}, "branches": [{"branch": "b1"}]}
    )
    source = move_mod.source_stack(state, "a2")
    target = move_mod.resolve_target(runner, "#36", source, state, "main", _Out())
    plan = move_mod.build(source, target)
    assert plan.steps[-3:-1] == [
        "git rebase --onto b1 a1 a2   # replay a2, off a1",
        "git checkout a2 && gh stack rebase --upstack --no-trunk   # replay a3",
    ]


def test_moving_onto_the_trunk_needs_no_target_stack_to_forget():
    runner = _MoveRunner(heads=["a1", "a2", "main"])
    source = move_mod.source_stack(_two(), "a2")
    plan = move_mod.build(source, _target(runner, "main", branch="a2"))
    assert plan.dest_init == ["a2"] and plan.untrack_target is False
    assert not any("checkout b" in step for step in plan.steps)


def test_the_landed_bottom_of_a_target_stack_is_not_declared_again():
    """`gh stack checkout <n>` imports every branch a stack ever had: a real
    stack arrived as 93 branches, 90 of them merged and all pointing at the
    trunk's tip. Re-declaring those made a 112-branch local stack, lost the PR
    association of every merged one, and would have handed `gh stack submit`
    branches whose PRs are closed and whose remote refs are gone."""
    runner = _MoveRunner(heads=["a1", "a2", "b1", "b2", "b3", "main"])
    source = move_mod.source_stack(_two(), "a2")
    target = _target(runner, "#36", branch="a2")
    plan = move_mod.build(source, target, landed={24, 25})
    assert plan.dest_init == ["b3", "a2"] and plan.landed == ["b1", "b2"]
    assert (
        "git checkout main && gh stack init --base main b3 a2   # the destination"
        in plan.steps
    )
    # ...and the operator is told, rather than left to notice the absence
    assert "minus 2 branch(es) whose PR is merged or closed: b1 b2" in move_mod.text(
        plan
    )


def test_the_replay_is_off_the_nearest_branch_that_is_actually_here():
    """`gh stack checkout <n>` records every branch a stack ever had but pulls
    only the ones the remote still has, so the branch directly below the moved
    slice is often absent. It is the rebase's upstream, and a real move stopped
    on it: `branch 'OS-3345' does not exist here, so where 'OS-3346' sits
    cannot be worked out`."""
    runner = _MoveRunner(heads=["a1", "a2", "b1", "main"])
    state = _tracked(
        (44, "main", [("m1", 10), ("m2", 11), ("a1", 42), ("a2", 43)]),
        (36, "main", [("b1", 24)]),
    )
    source = move_mod.source_stack(state, "a1")
    target = move_mod.resolve_target(runner, "#36", source, state, "main", _Out())
    plan = move_mod.build(source, target, present={"main", "a1", "a2", "b1"})
    assert plan.parent == "main" and plan.absent == ["m2", "m1"]
    assert "git rebase --onto b1 main a1   # replay a1, off main" in plan.steps
    assert "off   main   (m2 is not in this checkout" in move_mod.text(plan)

    # ...and the one below is used the moment it is here
    plan = move_mod.build(source, target, present={"main", "m2", "a1", "a2", "b1"})
    assert plan.parent == "m2" and plan.absent == []


def test_a_move_out_of_a_stack_whose_history_was_never_pulled_runs(
    tmp_path, monkeypatch, capsys
):
    """The whole of what stayed below is merged and gone, so there is nothing
    to declare and nothing to sit on but the trunk -- and the trunk stays out
    of the consistency check, where it would read as "a1 does not contain
    main" for every branch cut from an older trunk."""
    state = _tracked(
        (44, "main", [("m1", 10), ("m2", 11), ("a1", 42), ("a2", 43)]),
        (36, "main", [("b1", 24)]),
    )
    _fake_move(
        monkeypatch, tmp_path, state, current="a1", here=["main", "a1", "a2", "b1"]
    )
    monkeypatch.setattr(
        gh,
        "pull_requests",
        lambda runner, numbers: {
            10: {"state": "MERGED"},
            11: {"state": "MERGED"},
            24: {"state": "OPEN"},
            42: {"state": "OPEN"},
            43: {"state": "OPEN"},
        },
    )
    asked = []
    monkeypatch.setattr(
        gh,
        "is_ancestor",
        lambda runner, older, newer: asked.append((older, newer)) or True,
    )
    assert gsx.main(["move", "--to", "#36", "--yes"]) == 0
    assert asked == [("refs/heads/a1", "refs/heads/a2")]  # no main in the chain
    said = capsys.readouterr()
    plan = said.out + said.err
    assert "off   main   (m2 is not in this checkout" in plan
    assert "init --base main b1 a1 a2" in plan and "stays below" not in plan


def test_only_the_run_at_the_bottom_goes():
    """A merged PR above an open one is somebody's odd state, not history, and
    dropping it would leave a hole in the chain of parents the replay reads."""
    runner = _MoveRunner(heads=["a1", "a2", "b1", "b2", "b3", "main"])
    source = move_mod.source_stack(_two(), "a2")
    target = _target(runner, "#36", branch="a2")
    plan = move_mod.build(source, target, landed={25, 26})
    assert plan.dest_init == ["b1", "b2", "b3", "a2"] and plan.landed == []


def test_a_stack_with_nothing_open_left_is_not_a_target():
    runner = _MoveRunner(heads=["a1", "a2", "b1", "b2", "b3", "main"])
    source = move_mod.source_stack(_two(), "a2")
    target = _target(runner, "#36", branch="a2")
    with pytest.raises(ToolError, match="every PR in #36 is merged or closed"):
        move_mod.build(source, target, landed={24, 25, 26})


def test_what_stays_below_is_trimmed_too_but_the_rebase_keeps_its_real_parent():
    """The declaring leaves a landed branch out; the replay cannot. The moved
    commits really do sit on top of it, so it is the rebase's upstream whatever
    its PR says."""
    runner = _MoveRunner(heads=["a1", "a2", "b1", "b2", "b3", "main"])
    source = move_mod.source_stack(_two(), "a2")
    target = _target(runner, "#36", branch="a2")
    plan = move_mod.build(source, target, landed={42})
    assert plan.keep_init == [] and plan.parent == "a1"
    assert not any("stays below" in step for step in plan.steps)
    assert "git rebase --onto b3 a1 a2   # replay a2, off a1" in plan.steps


def test_both_stacks_pr_states_are_asked_for_in_one_call(tmp_path, monkeypatch, capsys):
    """The moved PRs decide whether the move may run, the ones below them
    decide what is still worth declaring -- one round trip for both."""
    _fake_move(monkeypatch, tmp_path, _two())
    asked = []

    def states(runner, numbers):
        asked.append(list(numbers))
        return {24: {"state": "MERGED"}, 25: {"state": "MERGED"}}

    monkeypatch.setattr(gh, "pull_requests", states)
    assert gsx.main(["move", "--to", "#36", "--dry-run"]) == 0
    assert asked == [[24, 25, 26, 42, 43]]
    said = capsys.readouterr()
    plan = said.out + said.err
    assert "->  b3 a2" in plan and "minus 2 branch(es)" in plan


def test_every_init_runs_from_the_trunk_because_it_refuses_to_run_in_a_stack(
    tmp_path,
):
    """`gh stack init` checks the CURRENT branch as well as the named ones, and
    the init before it leaves you on the top of the stack it just made. A real
    move died there: `✗ current branch "OS-3482" is already part of a stack`
    (exit 5), with the source and target already forgotten."""
    runner = _MoveRunner(heads=["a1", "a2", "b1", "b2", "b3", "main"], git_dir=tmp_path)
    source = move_mod.source_stack(_two(), "a2")
    plan = move_mod.build(source, _target(runner, "#36", branch="a2"))
    move_mod.run(runner, plan, runner.out, progress.Counter(runner.out, total=6))
    inits = [
        (previous, call)
        for previous, call in zip(runner.calls, runner.calls[1:])
        if call[:3] == ["gh", "stack", "init"]
    ]
    assert len(inits) == 2
    for previous, _ in inits:
        assert previous == ["git", "checkout", "-q", "main"]


def test_the_driver_runs_gh_stacks_own_commands_and_nothing_that_pushes(tmp_path):
    runner = _MoveRunner(heads=["a1", "a2", "b1", "b2", "b3", "main"], git_dir=tmp_path)
    source = move_mod.source_stack(_two(), "a2")
    plan = move_mod.build(source, _target(runner, "#36", branch="a2"))
    plan.upstream = "sha-a1"
    fields = move_mod.run(
        runner, plan, runner.out, progress.Counter(runner.out, total=6)
    )
    assert runner.stack_calls() == [
        ["gh", "stack", "unstack", "--local"],
        ["gh", "stack", "checkout", "b3"],
        ["gh", "stack", "unstack", "--local"],
        ["gh", "stack", "init", "--base", "main", "a1"],
        ["gh", "stack", "init", "--base", "main", "b1", "b2", "b3", "a2"],
    ]
    # one moved branch, so the replay is the one rebase and no cascade
    assert [call for call in runner.calls if "rebase" in call] == [
        ["git", "-c", "rerere.enabled=true", "rebase", "--onto", "b3", "sha-a1", "a2"]
    ]
    for call in runner.calls:
        assert call[:2] != ["git", "push"]
        assert call[:3] != ["gh", "stack", "link"]
        assert call[:3] != ["gh", "stack", "submit"]
        assert call[:3] != ["gh", "stack", "sync"]
        assert call[:3] != ["gh", "stack", "push"]
        if call[:3] == ["gh", "stack", "unstack"]:
            assert "--local" in call
    # back where you were, and the session waiting to be published
    assert ["git", "checkout", "-q", "a2"] in runner.calls
    assert move_mod.load(runner).stage == move_mod.PUBLISH
    assert fields["pushed"] is False and fields["next"] == "gsx submit --move"


#: GitHub's view of the two stacks in `_two()`, before any move.
def _server():
    return [
        _listed(44, [(42, "a1"), (43, "a2")]),
        _listed(36, [(24, "b1"), (25, "b2"), (26, "b3")]),
    ]


def test_a_conflict_hands_back_two_commands_not_a_recipe(tmp_path):
    """By the time anything can conflict, the old stacks are forgotten and the
    new ones written -- so "resolve and rerun" is not available. The session on
    disk is what makes the two ways out two commands: only this command knows
    what the move still has to do, and only it can put the tracking back."""
    session = move_mod.Session(
        stage=move_mod.REBASE,
        started_on="a2",
        moving=["a2", "a3"],
        target="b1",
        onto="b1",
        upstream="sha-a1",
        tips={"a2": "sha-a2", "a3": "sha-a3"},
        tracking='{"stacks": []}',
        stacks=[44, 36],
    )
    said = str(move_mod.stopped(session, "the replay of a2 onto b1 stopped"))
    assert "the replay of a2 onto b1 stopped" in said
    assert "tdd gsx move --continue" in said and "tdd gsx move --abort" in said
    assert "nothing has been pushed" in said


def test_the_session_says_what_is_left_and_how_to_undo_it(tmp_path):
    runner = _MoveRunner(heads=["a1", "a2", "a3", "b1", "main"], git_dir=tmp_path)
    (tmp_path / "gh-stack").write_text(json.dumps(_two()))
    state = _tracked((44, "main", [("a1", 42), ("a2", 43), ("a3", 44)]))
    state["stacks"].append(
        {"number": 36, "trunk": {"branch": "main"}, "branches": [{"branch": "b1"}]}
    )
    source = move_mod.source_stack(state, "a2")
    target = move_mod.resolve_target(runner, "#36", source, state, "main", _Out())
    plan = move_mod.build(source, target)
    plan.upstream = "sha-a1"
    move_mod.run(runner, plan, runner.out, progress.Counter(runner.out))

    # a finished move is still a move in progress: its replay is over and
    # nothing is published, which is what `gsx submit --move` is for
    waiting = move_mod.load(runner)
    assert waiting.stage == move_mod.PUBLISH and waiting.replaying is False
    assert "1 local move is not published (a2 a3 onto b1)" in waiting.line()
    assert "submit --move" in waiting.line() and "--abort" in waiting.line()

    # ...and one that stopped leaves everything an undo needs
    session = move_mod.Session(
        stage=move_mod.CASCADE,
        started_on="a2",
        moving=["a2", "a3"],
        target="b1",
        onto="b1",
        upstream="sha-a1",
        tips={"a2": "sha-a2", "a3": "sha-a3"},
        tracking=json.dumps(_two()),
        stacks=[44, 36],
    )
    move_mod.save(runner, session)
    again = move_mod.load(runner)
    assert again.stage == move_mod.CASCADE and again.moving == ["a2", "a3"]
    assert json.loads(again.tracking) == _two()
    assert again.bottom == "a2"


def test_the_session_records_every_branch_the_move_involves(tmp_path):
    """The tips are what an abort puts back, and a surprise is exactly what an
    undo is for -- so the ones staying and the target stack's are recorded too,
    not just the ones meant to be rewritten. From the refs, never from the
    remote: a branch may hold commits that were never pushed."""
    runner = _MoveRunner(heads=["a1", "a2", "a3", "b1", "b2", "main"], git_dir=tmp_path)
    state = _tracked((44, "main", [("a1", 42), ("a2", 43), ("a3", 44)]))
    state["stacks"].append(
        {
            "number": 36,
            "trunk": {"branch": "main"},
            "branches": [{"branch": "b1"}, {"branch": "b2"}],
        }
    )
    source = move_mod.source_stack(state, "a2")
    target = move_mod.resolve_target(runner, "#36", source, state, "main", _Out())
    plan = move_mod.build(source, target)
    plan.upstream = "sha-a1"
    move_mod.run(runner, plan, runner.out, progress.Counter(runner.out))

    # the session survives a finished replay, and holds the tips from before it
    assert move_mod.load(runner).stage == move_mod.PUBLISH
    # what run() wrote before the first change, which is what an abort reads
    written = []
    monkey = move_mod.save
    try:
        move_mod.save = lambda runner, s: written.append(s)
        move_mod.run(runner, plan, runner.out, progress.Counter(runner.out))
    finally:
        move_mod.save = monkey
    assert sorted(written[0].tips) == ["a1", "a2", "a3", "b1", "b2"]
    assert all(sha.startswith("sha-") for sha in written[0].tips.values())
    # never a remote ref
    assert not any(
        "remotes" in call[-1] for call in runner.calls if "rev-parse" in call
    )


def test_moves_accumulate_and_one_abort_undoes_all_of_them(
    tmp_path, monkeypatch, capsys
):
    """A move is not over when its replay finishes: it is local until `gsx
    submit --move`, further moves join it, and one `--abort` undoes the lot --
    back to the tips and the tracking file from before the FIRST one."""
    state = _tracked(
        (44, "main", [("a1", 42), ("a2", 43)]),
        (36, "main", [("b1", 24), ("b2", 25)]),
        (52, "main", [("c1", 61)]),
    )
    _fake_move(monkeypatch, tmp_path, state, current="a2")
    assert gsx.main(["move", "--to", "#36", "--yes"]) == 0
    runner = gh.Runner(out=_Out())
    first = move_mod.load(runner)
    assert first.stage == move_mod.PUBLISH and len(first.moves) == 1

    # a second move joins it rather than being refused
    monkeypatch.setattr(gh, "current_branch", lambda runner: "b1")
    assert gsx.main(["move", "--to", "#52", "--yes"]) == 0
    said = capsys.readouterr()
    assert "joining 1 unpublished move(s) (a2 onto b2)" in said.err
    both = move_mod.load(runner)
    assert [move["moving"] for move in both.moves] == [["a2"], ["b1", "b2"]]
    assert "2 local moves are not published (a2 onto b2; b1 b2 onto c1)" in both.line()
    # the sequence's own facts stay the first move's
    assert both.started_on == "a2" and both.tracking == first.tracking
    assert both.before == first.before and both.tips["a2"] == first.tips["a2"]
    assert sorted(both.stacks) == [36, 44, 52]

    # ...and one abort undoes both, back to where the first one started
    assert gsx.main(["move", "--abort"]) == 0
    said = capsys.readouterr()
    assert "undoing 2 move(s): a2 onto b2; b1 b2 onto c1" in said.err
    assert move_mod.load(runner) is None


def test_a_stopped_move_is_the_one_that_blocks_another(tmp_path, monkeypatch, capsys):
    """A half-replayed arrangement is not a thing to move out of, and the
    session cannot describe two replays at once."""
    _fake_move(monkeypatch, tmp_path, _two())
    move_mod.save(
        gh.Runner(out=_Out()),
        move_mod.Session(
            stage=move_mod.REBASE,
            started_on="a2",
            moving=["a2"],
            target="b3",
            onto="b3",
            upstream="sha-a1",
            tips={"a2": "sha-a2"},
            tracking=None,
        ),
    )
    assert gsx.main(["move", "--to", "#36", "--yes"]) == 1
    said = capsys.readouterr().err
    assert "stopped in the rebase" in said and "then move again" in said


def test_continue_is_for_a_conflict_and_nothing_else(tmp_path, monkeypatch, capsys):
    _fake_move(monkeypatch, tmp_path, _two())
    assert gsx.main(["move", "--to", "#36", "--yes"]) == 0
    capsys.readouterr()
    assert gsx.main(["move", "--continue"]) == 1
    assert "nothing to continue" in capsys.readouterr().err


def test_every_command_says_a_move_is_unfinished(tmp_path, monkeypatch, capsys):
    """Said once, before any command runs: in that window every branch may be
    somewhere the operator did not put it and GitHub knows nothing about it."""
    _fake_purge(monkeypatch, tmp_path, ["main"], {})
    monkeypatch.setattr(gh, "require_repo", lambda runner: None)
    monkeypatch.setattr(gh, "require_tools", lambda runner: None)
    move_mod.save(
        gh.Runner(out=_Out()),
        move_mod.Session(
            stage=move_mod.PUBLISH,
            started_on="a2",
            moving=["a2"],
            target="b3",
            onto="b3",
            upstream="sha-a1",
            tips={"a2": "sha-a2"},
            tracking=None,
        ),
    )
    for argv in (["purge", "--no-fetch"], ["stack", "--local", "--short"]):
        gsx.main(argv)
        assert "1 local move is not published (a2 onto b3)" in capsys.readouterr().err


def test_the_report_is_the_two_states_and_the_difference(tmp_path, monkeypatch, capsys):
    """Nothing in the repository still holds the arrangement a move started
    from, so the session carries it -- each branch with its PR and its commit
    -- and `--report` puts it beside what is there now."""
    _fake_move(monkeypatch, tmp_path, _two())
    assert gsx.main(["move", "--to", "#36", "--yes"]) == 0
    capsys.readouterr()
    assert gsx.main(["move", "--report"]) == 0
    said = capsys.readouterr().out
    assert "at the start   (2 stack(s))" in said
    start, _, current = said.partition("  now")
    assert "#44" in start and "#36" in start
    # each branch with its PR and the commit it pointed at when the move began
    assert "a2           #43      sha-a2" in start
    assert current.startswith("   (on a2, stage publish)")


def test_the_report_needs_a_move_to_report_on(tmp_path, monkeypatch, capsys):
    _fake_move(monkeypatch, tmp_path, _two())
    assert gsx.main(["move", "--report"]) == 1
    assert "nothing to report" in capsys.readouterr().err


def test_the_original_state_is_written_once_and_not_rewritten(tmp_path):
    """ "If it is not there already": the value of "as it was" is that it is not
    updated. A second move cannot start today, but the day one can it is the
    first move's state that an undo and a report both need."""
    runner = _MoveRunner(heads=["a1", "a2", "b1", "b2", "b3", "main"], git_dir=tmp_path)
    (tmp_path / "gh-stack").write_text(json.dumps(_two()))
    source = move_mod.source_stack(_two(), "a2")
    plan = move_mod.build(source, _target(runner, "#36", branch="a2"))
    move_mod.run(runner, plan, runner.out, progress.Counter(runner.out))
    first = move_mod.load(runner).before
    assert [stack["number"] for stack in first] == [44, 36]
    assert first[0]["branches"][1] == {"branch": "a2", "pr": 43, "sha": "sha-a2"}

    (tmp_path / "gh-stack").write_text('{"stacks": []}')  # a different arrangement
    move_mod.run(runner, plan, runner.out, progress.Counter(runner.out))
    assert move_mod.load(runner).before == first


def test_submit_move_completes_the_move_and_the_session_goes(
    tmp_path, monkeypatch, capsys
):
    """The dissolve is the point of no return: from there an `--abort` would
    reset local branches while GitHub holds the new arrangement, so the record
    of how to undo goes at the moment it becomes a trap."""
    after = _tracked(
        (None, "main", [("b1", 24), ("b2", 25), ("b3", 26), ("a1", 42), ("a2", 43)])
    )
    _fake_move(monkeypatch, tmp_path, after, listing=_server())
    runner = gh.Runner(out=_Out())
    move_mod.save(
        runner,
        move_mod.Session(
            stage=move_mod.PUBLISH,
            started_on="a2",
            moving=["a2"],
            target="b3",
            onto="b3",
            upstream="sha-a1",
            tips={"a2": "sha-a2"},
            tracking=None,
        ),
    )
    # without --move it is refused on the session alone, whatever GitHub says
    assert gsx.main(["submit"]) == 1
    assert "1 local move is not published" in capsys.readouterr().err

    answers = [_server(), [_listed(36, [(24, "b1")])]]
    monkeypatch.setattr(
        gh, "stacks", lambda runner, **kw: answers.pop(0) if answers else []
    )
    monkeypatch.setattr(gh, "stack_pr_snapshot", lambda runner: [])
    monkeypatch.setattr(labels, "Repo", lambda runner, out: None)
    monkeypatch.setattr(labels, "with_defaults", lambda repo, ops, no: [])
    assert gsx.main(["submit", "--move"]) == 0
    assert move_mod.load(runner) is None


def test_a_stopped_move_is_not_published(tmp_path, monkeypatch, capsys):
    """Half a rearrangement, with the branches mid-rebase: whatever a push sent
    would be neither arrangement."""
    _fake_move(monkeypatch, tmp_path, _two())
    move_mod.save(
        gh.Runner(out=_Out()),
        move_mod.Session(
            stage=move_mod.CASCADE,
            started_on="a2",
            moving=["a2", "a3"],
            target="b3",
            onto="b3",
            upstream="sha-a1",
            tips={"a2": "sha-a2"},
            tracking=None,
        ),
    )
    assert gsx.main(["submit", "--move"]) == 1
    said = capsys.readouterr().err
    assert "stopped in the cascade" in said and "publish it after that" in said


def test_abort_puts_the_branches_and_both_stacks_back(tmp_path):
    """Restoring the file gh-stack owns, rather than running the rearrangement
    backwards -- which could not be complete."""
    runner = _MoveRunner(heads=["a1", "a2", "a3", "main"], git_dir=tmp_path)
    (tmp_path / "gh-stack").write_text('{"stacks": []}')  # the rearranged one
    session = move_mod.Session(
        stage=move_mod.CASCADE,
        started_on="a2",
        moving=["a2", "a3"],
        target="b1",
        onto="b1",
        upstream="sha-a1",
        tips={"a2": "old-a2", "a3": "old-a3"},
        tracking=json.dumps(_two()),
        stacks=[44, 36],
    )
    move_mod.save(runner, session)
    fields = move_mod.unwind(runner, session, runner.out)

    assert ["git", "reset", "-q", "--hard", "old-a2"] in runner.calls
    assert ["git", "branch", "-f", "a3", "old-a3"] in runner.calls
    assert fields["restored"] == ["a2", "a3"] and fields["tracking"] == "restored"
    assert json.loads((tmp_path / "gh-stack").read_text()) == _two()
    assert move_mod.load(runner) is None


def test_abort_removes_a_tracking_file_that_was_not_there_before(tmp_path):
    runner = _MoveRunner(heads=["a2"], git_dir=tmp_path)
    (tmp_path / "gh-stack").write_text('{"stacks": []}')
    session = move_mod.Session(
        stage=move_mod.REBASE,
        started_on="a2",
        moving=["a2"],
        target="main",
        onto="main",
        upstream="sha-a1",
        tips={},
        tracking=None,
    )
    move_mod.unwind(runner, session, runner.out)
    assert not (tmp_path / "gh-stack").exists()


def test_nothing_is_pending_when_the_two_sides_agree():
    assert not move_mod.pending(_two(), _server())


def test_a_stack_that_can_still_grow_into_place_is_not_pending():
    """`gh stack link <n> ...` appends, so a GitHub stack whose PRs are the
    bottom of a local stack needs no dissolving -- it keeps its number and
    grows. That is what makes the target of a move cheap."""
    moved = _tracked((36, "main", [("b1", 24), ("b2", 25), ("b3", 26), ("new", 99)]))
    assert not move_mod.pending(moved, _server())


def test_a_whole_stack_moved_onto_another_is_pending():
    """The case the first rule missed: nothing is split, but #44's PRs now sit
    on top of #36's, and only one stack can hold them."""
    after = _tracked(
        (None, "main", [("b1", 24), ("b2", 25), ("b3", 26), ("a1", 42), ("a2", 43)])
    )
    found = move_mod.pending(after, _server())
    assert found and found.dissolve == [44]
    assert found.prs == {42: 44, 43: 44}
    assert found.stacks == [["b1", "b2", "b3", "a1", "a2"]]
    # what has to happen, not which PRs moved: naming the movers meant picking
    # them out of the stack that lost them, and an early version said all three
    # of #3485/#3486/#3487 had gone when only one had
    # one line for what is going on, then a row per stack naming the branches
    # and PRs it is about, then the ways out
    lines = found.line().splitlines()
    assert lines[0] == (
        "GitHub and this checkout disagree about 1 stack(s) "
        "-- most likely an unpublished `gsx move`:"
    )
    assert lines[1] == "  #44     a1 (#42) a2 (#43)"
    # all three ways out, and the one that needs a session says so: this
    # finding is read off the two sides, so it turns up in checkouts that have
    # none and `--abort` would answer "no move is in progress" there
    rest = "\n".join(lines[2:])
    assert "out:    `tdd gsx submit --move` makes it effective" in rest
    assert "move --abort` cancels it, if this checkout still has the move's" in rest
    assert "gh stack checkout <n>` re-imports" in rest
    assert "gsx submit --move" in found.line()


def test_half_a_stack_moved_leaves_both_halves_to_submit():
    after = _tracked(
        (44, "main", [("a1", 42)]),
        (None, "main", [("b1", 24), ("b2", 25), ("b3", 26), ("a2", 43)]),
    )
    found = move_mod.pending(after, _server())
    assert found.dissolve == [44] and found.prs == {42: 44, 43: 44}
    # both, because dissolving #44 takes the half that stayed down with it
    assert found.stacks == [["a1"], ["b1", "b2", "b3", "a2"]]


def test_a_pr_this_checkout_does_not_track_is_not_evidence_of_a_move():
    """Someone else adding a PR to your stack is the other reason the two sides
    differ, and it is not a move: it needs a sync, not a dissolve."""
    server = [_listed(36, [(24, "b1"), (25, "b2"), (26, "b3"), (99, "theirs")])]
    assert not move_mod.pending(_two(), server)


def test_a_closed_stack_on_github_is_left_alone():
    server = [_listed(44, [(42, "a1"), (43, "a2")], open_stack=False)]
    after = _tracked((None, "main", [("b1", 24), ("a1", 42), ("a2", 43)]))
    assert not move_mod.pending(after, server)


@pytest.mark.parametrize(
    "node, message",
    [
        ({"state": "MERGED"}, "is MERGED"),
        ({"state": "OPEN", "isInMergeQueue": True}, "merge queue"),
        (
            {"state": "OPEN", "autoMergeRequest": {"enabledAt": "x"}},
            "auto-merge",
        ),
    ],
)
def test_a_pr_the_publish_could_not_restack_is_refused_up_front(node, message):
    """GitHub leaves a queued PR stacked and then keeps the whole stack, so the
    dissolve would silently do nothing and the PR would be in two stacks."""
    with pytest.raises(ToolError, match=message):
        commands._refuse_unmovable({43: node}, [43])


def _fake_move(monkeypatch, tmp_path, state, listing=(), current="a2", here=None):
    """A whole move run with git and gh faked: `state` is the tracking file on
    disk, `listing` what GitHub's stacks API answers, `here` the branches the
    checkout has (by default every branch the tracking names, plus the trunk)."""
    monkeypatch.setenv("TDD_DIR", str(tmp_path))
    here = (
        ["main", *(item["branch"] for s in state["stacks"] for item in s["branches"])]
        if here is None
        else list(here)
    )
    (tmp_path / "gh-stack").write_text(json.dumps(state))
    calls = []

    class FakeRunner:
        def __init__(self, out, dry_run=False):
            self.out = out
            self.dry_run = dry_run

        def run(self, argv, **kwargs):
            calls.append(argv)
            if argv[:3] == ["git", "rev-parse", "-q"]:
                return f"sha-{argv[-1]}"
            if argv[:2] == ["git", "for-each-ref"]:
                # name and sha, which is what `gh.head_shas` reads
                return "\n".join(f"{name} sha-{name}" for name in here)
            return ""

        def json(self, argv):
            return None

    monkeypatch.setattr(gh, "Runner", FakeRunner)
    monkeypatch.setattr(gh, "require_tools", lambda runner: None)
    monkeypatch.setattr(gh, "require_repo", lambda runner: None)
    monkeypatch.setattr(gh, "git_dir", lambda runner: tmp_path)
    monkeypatch.setattr(gh, "default_branch", lambda runner: "main")
    monkeypatch.setattr(gh, "current_branch", lambda runner: current)
    monkeypatch.setattr(gh, "dirty", lambda runner: False)
    monkeypatch.setattr(gh, "pull_requests", lambda runner, numbers: {})
    monkeypatch.setattr(gh, "stacks", lambda runner, **kw: list(listing))
    monkeypatch.setattr(gh, "stack_remote", lambda runner: "origin")
    # `is_ancestor` asks git directly (the answer is an exit code), so a fake
    # runner cannot answer it: a consistent stack is the default here and the
    # test that cares patches it itself.
    monkeypatch.setattr(gh, "is_ancestor", lambda runner, older, newer: True)
    return calls


def test_move_refuses_while_someone_elses_rebase_is_stopped(
    tmp_path, monkeypatch, capsys
):
    _fake_move(monkeypatch, tmp_path, _two())
    (tmp_path / "gh-stack-rebase-state").write_text(
        json.dumps({"conflictBranch": "b2"})
    )
    assert gsx.main(["move", "--to", "#36"]) == 1
    said = capsys.readouterr().err
    assert "a stack rebase is stopped on 'b2'" in said
    assert "gh stack rebase --continue" in said and "--abort" in said


def test_move_drives_the_four_commands_and_says_what_publishes_it(
    tmp_path, monkeypatch, capsys
):
    calls = _fake_move(monkeypatch, tmp_path, _two())
    assert gsx.main(["move", "--to", "#36", "--yes"]) == 0
    out = capsys.readouterr()
    assert [call for call in calls if call[:2] == ["gh", "stack"]] == [
        ["gh", "stack", "unstack", "--local"],
        ["gh", "stack", "checkout", "b3"],
        ["gh", "stack", "unstack", "--local"],
        ["gh", "stack", "init", "--base", "main", "a1"],
        ["gh", "stack", "init", "--base", "main", "b1", "b2", "b3", "a2"],
    ]
    assert "moved 1 branch(es) onto b3, locally" in out.out
    assert "gsx submit --move" in out.out


def test_a_stack_whose_branches_do_not_contain_their_parents_is_refused(
    tmp_path, monkeypatch, capsys
):
    """The cascade above the first moved branch reads the base `gh stack init`
    recorded -- the merge-base with the parent the branch was declared to have,
    which is much older when the branch does not contain that parent. A real
    stack was in that state (one branch on an older trunk than the ten below
    it) and the cascade replayed twenty-four commits it already had into four
    conflicting files. This is that, said before anything changes."""
    calls = _fake_move(monkeypatch, tmp_path, _two(), current="a1")
    monkeypatch.setattr(
        gh, "is_ancestor", lambda runner, older, newer: "a1" not in older
    )
    assert gsx.main(["move", "--to", "#36", "--yes"]) == 1
    said = capsys.readouterr().err
    assert "a2 does not contain a1" in said
    assert "gh stack rebase --no-trunk" in said
    # and nothing was forgotten on the way to finding out
    assert not any(call[:3] == ["gh", "stack", "unstack"] for call in calls)


def test_the_trunk_is_left_out_of_that_check(tmp_path, monkeypatch, capsys):
    """A branch cut from an older trunk is the ordinary case: `git rebase
    --onto X <trunk> B` replays `<trunk>..B`, which is B's own commits whether
    or not B contains the trunk's tip."""
    _fake_move(monkeypatch, tmp_path, _two(), current="a1")
    asked = []
    monkeypatch.setattr(
        gh,
        "is_ancestor",
        lambda runner, older, newer: asked.append((older, newer)) or True,
    )
    assert gsx.main(["move", "--to", "#36", "--yes"]) == 0
    # a1 moves with everything above it, so the trunk is the parent -- and it
    # is not in the pairs that were checked
    assert asked == [("refs/heads/a1", "refs/heads/a2")]


def test_stack_says_the_two_sides_no_longer_agree(tmp_path, monkeypatch, capsys):
    """Not "a move is in progress": the move finished, and what is left is a
    disagreement waiting to be published."""
    after = _tracked(
        (None, "main", [("b1", 24), ("b2", 25), ("b3", 26), ("a1", 42), ("a2", 43)])
    )
    _fake_move(monkeypatch, tmp_path, after, listing=_server())
    monkeypatch.setattr(
        gh,
        "branch_sync",
        lambda runner, names, remote, *_: dict.fromkeys(names, gh.IN_SYNC),
    )
    monkeypatch.setattr(gh, "pr_titles", lambda runner, numbers: {})
    assert gsx.main(["move", "--to", "main"]) == 1  # (unrelated: nothing to move)
    capsys.readouterr()
    assert gsx.main(["stack", "--short", "--no-fetch"]) == 0
    said = capsys.readouterr().err
    assert "disagree about 1 stack(s)" in said and "in progress" not in said


def test_submit_refuses_to_publish_a_move_without_being_told_to(
    tmp_path, monkeypatch, capsys
):
    after = _tracked(
        (None, "main", [("b1", 24), ("b2", 25), ("b3", 26), ("a1", 42), ("a2", 43)])
    )
    _fake_move(monkeypatch, tmp_path, after, listing=_server())
    assert gsx.main(["submit"]) == 1
    said = capsys.readouterr().err
    assert "disagree about 1 stack(s)" in said and "--move" in said


def test_submit_move_dissolves_the_old_stack_before_it_pushes(
    tmp_path, monkeypatch, capsys
):
    """Order is the whole of it: the API cannot take a PR out of a stack, so
    the old one goes first or the new one cannot be made."""
    after = _tracked(
        (None, "main", [("b1", 24), ("b2", 25), ("b3", 26), ("a1", 42), ("a2", 43)])
    )
    calls = _fake_move(monkeypatch, tmp_path, after, listing=_server())
    # the listing is read twice: once to notice the move, once after the
    # dissolve to check GitHub really let go of the stack
    answers = [_server(), [_listed(36, [(24, "b1")])]]
    monkeypatch.setattr(
        gh, "stacks", lambda runner, **kw: answers.pop(0) if answers else []
    )
    monkeypatch.setattr(gh, "stack_pr_snapshot", lambda runner: [])
    monkeypatch.setattr(labels, "Repo", lambda runner, out: None)
    monkeypatch.setattr(labels, "with_defaults", lambda repo, ops, no: [])
    assert gsx.main(["submit", "--move"]) == 0
    interesting = [
        call
        for call in calls
        if call[:3] in (["gh", "stack", "unstack"], ["gh", "stack", "submit"])
    ]
    assert interesting == [
        ["gh", "stack", "unstack", "44"],
        ["gh", "stack", "submit", "--auto", "--open"],
    ]


def test_submit_move_stops_if_github_kept_the_stack(tmp_path, monkeypatch, capsys):
    """A queued PR makes the dissolve a no-op and GitHub keeps the stack; the
    push must not happen, because the move cannot be completed."""
    after = _tracked(
        (None, "main", [("b1", 24), ("b2", 25), ("b3", 26), ("a1", 42), ("a2", 43)])
    )
    calls = _fake_move(monkeypatch, tmp_path, after, listing=_server())
    monkeypatch.setattr(labels, "Repo", lambda runner, out: None)
    assert gsx.main(["submit", "--move"]) == 1
    assert "GitHub kept stack(s) #44" in capsys.readouterr().err
    assert not any(call[:3] == ["gh", "stack", "submit"] for call in calls)


# ------------------------------------------------------------------- stack
def _state(number=34, trunk="main", names=("a1", "a2")):
    return {
        "stacks": [
            {
                "number": number,
                "trunk": {"branch": trunk},
                "branches": [{"branch": name} for name in names],
            }
        ]
    }


def _sync(**by_name):
    return by_name


def test_each_branch_carries_how_it_stands_against_the_remote():
    state = _state(names=("a1", "a2"))
    state["stacks"].append(
        {
            "number": 40,
            "trunk": {"branch": "main"},
            "branches": [{"branch": "b24"}, {"branch": "b25"}],
        }
    )
    state["stacks"].append(
        {"number": None, "trunk": {"branch": "main"}, "branches": [{"branch": "c1"}]}
    )
    rows = commands.stack_rows(
        state,
        "a2",
        _sync(a1=gh.IN_SYNC, a2=gh.AHEAD, b24=gh.BEHIND, b25=gh.DIVERGED, c1=gh.AHEAD),
    )
    assert [row["number"] for row in rows] == [34, 40, None]
    assert rows[0]["branches"] == [
        {
            "name": "a1",
            "pr": None,
            "sync": gh.IN_SYNC,
            "current": False,
            "remote_only": False,
            "local_only": False,
        },
        {
            "name": "a2",
            "pr": None,
            "sync": gh.AHEAD,
            "current": True,
            "remote_only": False,
            "local_only": False,
        },
    ]
    assert rows[0]["current"] is True and rows[1]["current"] is False
    # a branch with no sync answer at all is "no local branch", never "in sync"
    assert commands.stack_rows(state, "")[0]["branches"][0]["sync"] == gh.NO_LOCAL


def test_the_symbol_before_a_name_says_where_that_branch_stands():
    state = _state(names=("insync", "ahead"))
    state["stacks"].append(
        {
            "number": 40,
            "trunk": {"branch": "main"},
            "branches": [{"branch": "behind"}, {"branch": "diverged"}],
        }
    )
    state["stacks"].append(
        {
            "number": None,
            "trunk": {"branch": "main"},
            "branches": [{"branch": "unpushed"}, {"branch": "gone"}],
        }
    )
    rows = commands.stack_rows(
        state,
        "ahead",
        _sync(
            insync=gh.IN_SYNC,
            ahead=gh.AHEAD,
            behind=gh.BEHIND,
            diverged=gh.DIVERGED,
            unpushed=gh.AHEAD,
            gone=gh.NO_LOCAL,
        ),
    )
    # the brackets' two slots are the spaces around `<-`, so a bracketed cell
    # is exactly as wide as a plain one and the names line up across stacks
    # whichever one is bracketed
    assert commands.stack_lines(rows).splitlines() == [
        "[#34]  main <- =insync   <-+[ahead]",
        " #40   main <- -behind   <- xdiverged",
        " #-    main <- +unpushed <- ?gone",
    ]
    for line in commands.stack_lines(rows).splitlines():
        assert line == line.rstrip(), line


def test_the_symbol_stays_outside_the_brackets_and_the_brackets_are_white():
    rows = commands.stack_rows(
        _state(names=("a1", "a2")), "a2", _sync(a1=gh.DIVERGED, a2=gh.BEHIND)
    )
    painted = commands.stack_lines(
        rows, lambda name, text: f"<{name or 'plain'}>{text}</>"
    )
    assert painted == (
        "<white>[</>#34<white>]</>  main "
        # the symbol says how the branch stands and the brackets say which row
        # you are on: two facts about two different things, so the brackets
        # hold only the name -- `-[a2]`, not `[-a2]`
        "<- <red>x</><red>a1</> <-<yellow>-</><white>[</><yellow>a2</><white>]</>"
    )
    every = {
        gh.IN_SYNC: ("=", "green"),
        gh.AHEAD: ("+", "blue"),
        gh.BEHIND: ("-", "yellow"),
        gh.DIVERGED: ("x", "red"),
    }
    assert {state: commands.MARKS[state] for state in every} == every
    # an unknown state gets a symbol but no colour: nothing is claimed about it
    assert commands.MARKS[gh.NO_LOCAL] == ("?", "")


def _listed(number, prs, base="main", open_stack=True):
    """One stack as the stacks REST API returns it: `prs` are
    `(pr number, branch)`, or `(pr number, branch, state)` for a PR that is
    done with."""
    return {
        "number": number,
        "base": {"ref": base},
        "open": open_stack,
        "pull_requests": [
            {
                "number": pr[0],
                "state": pr[2] if len(pr) > 2 else "open",
                "merged_at": "2026-09-01T00:00:00Z" if len(pr) > 3 else None,
                "head": {"ref": pr[1], "sha": f"sha-{pr[1]}"},
            }
            for pr in prs
        ],
    }


def test_a_pr_only_github_has_joins_the_stack_it_is_in():
    """The tracking file cannot know a PR someone else added to your stack --
    `gh stack sync` is what would pull it down, and appends it at the top, so
    that is where it goes here too."""
    rows = commands.stack_rows(
        _state(names=("a1", "a2")),
        "a2",
        remote=[_listed(34, [(21, "a1"), (22, "a2"), (29, "a3")])],
    )
    assert [branch["name"] for branch in rows[0]["branches"]] == ["a1", "a2", "a3"]
    theirs = rows[0]["branches"][-1]
    assert (theirs["pr"], theirs["remote_only"], theirs["current"]) == (29, True, False)
    # ...and the stack itself is not "remote only": this checkout tracks it
    assert rows[0]["remote_only"] is False


def test_a_stack_only_github_has_is_a_row_of_its_own():
    rows = commands.stack_rows(
        _state(names=("a1", "a2")),
        "a2",
        remote=[_listed(34, [(21, "a1"), (22, "a2")]), _listed(41, [(52, "c1")])],
    )
    assert [row["number"] for row in rows] == [34, 41]
    theirs = rows[1]
    assert theirs["remote_only"] is True and theirs["trunk"] == "main"
    assert [(b["name"], b["pr"], b["remote_only"]) for b in theirs["branches"]] == [
        ("c1", 52, True)
    ]


@pytest.mark.parametrize(
    "pull",
    [
        (29, "a3", "closed"),  # closed unmerged
        (29, "a3", "closed", "merged"),  # and merged
    ],
)
def test_a_pr_that_is_done_with_is_not_something_you_are_missing(pull):
    """A stack keeps its merged PRs, and a row saying you lack a merged branch
    would be noise on every stack that has ever landed anything."""
    rows = commands.stack_rows(
        _state(names=("a1", "a2")),
        "a2",
        remote=[_listed(34, [(21, "a1"), (22, "a2"), pull])],
    )
    assert [branch["name"] for branch in rows[0]["branches"]] == ["a1", "a2"]


def test_a_closed_stack_is_left_out_altogether():
    rows = commands.stack_rows(
        {"stacks": []}, "", remote=[_listed(41, [(52, "c1")], open_stack=False)]
    )
    assert rows == []


def test_each_source_takes_its_rows_from_its_own_side():
    state = _state(names=("a1", "a2"))
    remote = [_listed(34, [(21, "a1"), (29, "a3")]), _listed(41, [(52, "c1")])]

    local = commands.stack_rows(state, "a2", remote=remote, source=commands.LOCAL)
    assert [row["number"] for row in local] == [34]
    assert [b["name"] for b in local[0]["branches"]] == ["a1", "a2"]

    # GitHub's view: its stacks, its order, and a2 gone because no PR of #34
    # has it any more -- which is the thing --remote is for seeing
    only = commands.stack_rows(state, "a2", remote=remote, source=commands.REMOTE)
    assert [row["number"] for row in only] == [34, 41]
    assert [b["name"] for b in only[0]["branches"]] == ["a1", "a3"]
    assert [b["remote_only"] for b in only[0]["branches"]] == [False, True]
    assert only[1]["remote_only"] is True

    both = commands.stack_rows(state, "a2", remote=remote, source=commands.BOTH)
    assert [row["number"] for row in both] == [34, 41]
    assert [b["name"] for b in both[0]["branches"]] == ["a1", "a2", "a3"]


def test_what_only_github_has_is_a_magenta_question_mark():
    rows = commands.stack_rows(
        _state(names=("a1",)),
        "a1",
        _sync(a1=gh.IN_SYNC),
        remote=[_listed(34, [(21, "a1"), (29, "a3")]), _listed(41, [(52, "c1")])],
    )
    painted = commands.stack_lines(
        rows, lambda name, text: f"<{name or 'plain'}>{text}</>"
    )
    assert painted.splitlines() == [
        # a mark gets a column of ITS own, left of the brackets, because a
        # stack can be both the one you are on and one GitHub does not have
        " <white>[</>#34<white>]</>  main "
        "<-<green>=</><white>[</><green>a1</><white>]</>"
        "<- <magenta>?</><magenta>a3</>",
        # a whole stack this checkout does not track: the same `?` in the same
        # magenta, and the number takes the mark's colour as a branch's name
        # takes its own. The tag is bracketed tightly and the padding goes
        # after it, so `#-` beside `#3443` does not read as `[#-   ]`
        "<magenta>?</> <magenta>#41</>   main <- <magenta>?</><magenta>c1</>",
    ]
    assert commands.REMOTE_MARK == ("?", "magenta")
    assert commands.GUARDS == {"current": ("[", "]", "white")}


def test_a_stack_the_listing_has_no_open_number_for_is_local_only():
    """Measured in tabsdata-os: the tracking file held #3488, #3478 and #3495
    and GitHub had exactly one open stack, #3495 -- the other two had been
    re-linked into it, and nothing in the view said so."""
    state = _with_prs(_state(number=3478, names=("a1", "a2")), [(21, 22)])
    state["stacks"].append(
        {
            "number": 3495,
            "trunk": {"branch": "main"},
            "branches": [
                {"branch": "a1", "pullRequest": {"number": 21}},
                {"branch": "a2", "pullRequest": {"number": 22}},
                {"branch": "a3", "pullRequest": {"number": 29}},
            ],
        }
    )
    listing = [_listed(3495, [(21, "a1"), (22, "a2"), (29, "a3")])]
    rows = commands.stack_rows(state, "a2", remote=listing, asked=True)
    # by NUMBER: #3478's branches all sit in the stack that replaced it, which
    # is exactly the case a reader has to be told about
    assert [(row["number"], row["local_only"]) for row in rows] == [
        (3478, True),
        (3495, False),
    ]
    # ...and the branches are not marked as well: GitHub's stacks do have them
    assert not any(b["local_only"] for row in rows for b in row["branches"])
    assert commands.LOCAL_MARK == ("!", "red")


def test_a_branch_no_stack_on_github_holds_is_local_only():
    state = _with_prs(_state(names=("a1", "a2", "a3")), [(21, 22, None)])
    rows = commands.stack_rows(
        state, "a2", remote=[_listed(34, [(21, "a1")])], asked=True
    )
    assert [(b["name"], b["local_only"]) for b in rows[0]["branches"]] == [
        ("a1", False),
        # its PR is in the file and in no stack GitHub has
        ("a2", True),
        # and a branch with no PR has not been submitted rather than been
        # forgotten: `-` in the number column says that, and `+` says the
        # remote has nothing of it either
        ("a3", False),
    ]
    assert rows[0]["local_only"] is False  # #34 is open on GitHub


def test_nothing_is_local_only_unless_the_listing_was_really_had():
    """An empty listing is what a repository with no open stacks and a listing
    that could not be read both look like, and the difference between them is
    the difference between a fact and a false alarm."""
    state = _with_prs(_state(names=("a1", "a2")), [(21, 22)])
    assert not any(
        row["local_only"] or any(b["local_only"] for b in row["branches"])
        for row in commands.stack_rows(state, "a2", remote=[])
    )
    # --local asks nobody, which is its point
    assert not any(
        row["local_only"]
        for row in commands.stack_rows(state, "a2", remote=[], source=commands.LOCAL)
    )
    # asked, and GitHub really has no open stack: then it is a fact
    every = commands.stack_rows(state, "a2", remote=[], asked=True)
    assert every[0]["local_only"] is True
    assert [b["local_only"] for b in every[0]["branches"]] == [True, True]


def test_what_only_this_checkout_has_is_a_red_bang():
    state = _with_prs(_state(names=("a1",)), [(21,)])
    rows = commands.stack_rows(
        state, "a1", _sync(a1=gh.AHEAD), remote=[_listed(41, [(52, "c1")])], asked=True
    )
    painted = commands.stack_lines(
        rows, lambda name, text: f"<{name or 'plain'}>{text}</>"
    )
    assert painted.splitlines() == [
        # the stack you are on AND one GitHub does not have: the mark has a
        # column of its own precisely so both can be said
        "<red>!</><white>[</><red>#34</><white>]</>  main "
        # `!` takes the place of the sync symbol, as `?` does
        "<-<red>!</><white>[</><red>a1</><white>]</>",
        "<magenta>?</> <magenta>#41</>   main <- <magenta>?</><magenta>c1</>",
    ]
    line = commands.legend(rows, "origin", lambda name, text: f"<{name}>{text}</>")
    # the mirror sits next to what it mirrors
    assert "<magenta>?</> remote only  <red>!</> local only" in line
    # and `?` is not also explained as "no local branch": the branch wearing a
    # sync symbol is the only thing that entry is about
    assert "no local branch" not in line


def test_at_most_one_stack_is_the_one_you_are_on():
    """A branch can sit in several tracked stacks -- leftovers do exactly
    that -- and only one of them is what `submit` and `apply` act on."""
    state = _with_prs(_state(number=3488, names=("a1", "a2")), [(21, 22)])
    state["stacks"].append(
        {
            "number": 3495,
            "trunk": {"branch": "main"},
            "branches": [
                {"branch": "a0", "pullRequest": {"number": 20}},
                {"branch": "a2", "pullRequest": {"number": 22}},
            ],
        }
    )
    rows = commands.stack_rows(state, "a2", remote=[_listed(3495, [(20, "a0")])])
    # the first in the file, because that is the one every other subcommand
    # takes (`move.stack_of`)
    assert [row["current"] for row in rows] == [True, False]
    # the BRANCH keeps its brackets in every row it appears in: it is the
    # branch you are on wherever it is listed, and seeing it twice is the news
    assert [[b["current"] for b in row["branches"]] for row in rows] == [
        [False, True],
        [False, True],
    ]


def _merged(number, branch):
    return {
        "number": number,
        "state": "closed",
        "merged_at": "2026-09-07T12:56:20Z",
        "head": {"ref": branch},
    }


def test_a_stacks_merged_prs_are_its_history_not_its_state():
    """`gsx stack -a -s` on a real stack (#3443 in tabsdata-os) printed ninety
    `?OS-32xx` before the three branches that were still open. The three were
    the answer; the ninety came from the tracking file, which keeps them."""
    listing = [
        {
            "number": 34,
            "base": {"ref": "main"},
            "open": True,
            "pull_requests": [
                _merged(21, "a1"),
                {
                    "number": 22,
                    "state": "open",
                    "merged_at": None,
                    "head": {"ref": "a2"},
                },
            ],
        }
    ]
    assert commands.finished_prs(listing) == {21}
    rows = commands.stack_rows(
        _with_prs(_state(names=("a1", "a2")), [(21, 22)]), "a2", remote=listing
    )
    kept, hidden = commands.without_finished(rows, commands.finished_prs(listing))
    assert hidden == 1
    assert [branch["name"] for branch in kept[0]["branches"]] == ["a2"]


def test_a_stack_with_nothing_left_open_goes_with_them():
    listing = [
        {
            "number": 34,
            "base": {"ref": "main"},
            "open": True,
            "pull_requests": [_merged(21, "a1"), _merged(22, "a2")],
        }
    ]
    rows = commands.stack_rows(
        _with_prs(_state(names=("a1", "a2")), [(21, 22)]), "a2", remote=listing
    )
    kept, hidden = commands.without_finished(rows, commands.finished_prs(listing))
    assert kept == [] and hidden == 2


@pytest.mark.parametrize(
    "pull, done",
    [
        ({"number": 1, "state": "closed", "merged_at": "2026-01-01T00:00:00Z"}, True),
        ({"number": 1, "state": "closed", "merged_at": None}, True),
        ({"number": 1, "state": "open", "merged_at": None}, False),
        # a payload that says neither is taken as open: inventing a merge would
        # hide a branch, which is the one mistake that costs something
        ({"number": 1}, False),
    ],
)
def test_only_what_the_listing_calls_done_is_treated_as_done(pull, done):
    assert commands._finished(pull) is done


def test_the_merged_prs_are_left_out_and_said_to_be(tmp_path, monkeypatch, capsys):
    _fake_purge(monkeypatch, tmp_path, ["main"], {})
    (tmp_path / "gh-stack").write_text(
        json.dumps(_with_prs(_state(names=("a1", "a2")), [(21, 22)]))
    )
    monkeypatch.setattr(gh, "git_dir", lambda runner: tmp_path)
    monkeypatch.setattr(gh, "current_branch", lambda runner: "a2")
    monkeypatch.setattr(
        gh,
        "branch_sync",
        lambda runner, names, remote, *_: dict.fromkeys(names, gh.IN_SYNC),
    )
    monkeypatch.setattr(
        gh,
        "stacks",
        lambda runner, **kw: [
            {
                "number": 34,
                "base": {"ref": "main"},
                "open": True,
                "pull_requests": [
                    _merged(21, "a1"),
                    {
                        "number": 22,
                        "state": "open",
                        "merged_at": None,
                        "head": {"ref": "a2"},
                    },
                ],
            }
        ],
    )
    assert gsx.main(["stack", "--short", "--no-fetch"]) == 0
    said = capsys.readouterr()
    assert "1 merged or closed PR(s) left out; --merged shows them" in said.err
    assert "[#34]  main <-=[a2]" in said.out and "a1" not in said.out

    assert gsx.main(["stack", "--short", "--no-fetch", "--merged"]) == 0
    said = capsys.readouterr()
    assert "=a1" in said.out and "left out" not in said.err


def test_the_legend_explains_a_mark_only_when_a_row_uses_it():
    rows = commands.stack_rows(_state(names=("a1",)), "a1", _sync(a1=gh.IN_SYNC))
    plain = commands.legend(rows, "origin")
    assert "[] current" in plain and "remote only" not in plain
    with_theirs = commands.stack_rows(
        _state(names=("a1",)),
        "a1",
        _sync(a1=gh.IN_SYNC),
        remote=[_listed(41, [(52, "c1")])],
    )
    # the two `?` are one symbol for two nearby facts, told apart by colour and
    # by the words: nothing here, versus nothing here and GitHub has it
    painted = commands.legend(
        with_theirs, "origin", lambda name, text: f"<{name or 'plain'}>{text}</>"
    )
    assert "<magenta>?</> remote only" in painted


def test_the_one_sided_views_carry_no_symbol_at_all():
    """`--local` and `--remote` show one side each, so "behind" would be a
    claim about the side they are not showing."""
    rows = commands.stack_rows(
        _state(names=("a1", "a2")), "a2", remote=[], source=commands.LOCAL
    )
    for branch in rows[0]["branches"]:
        branch["sync"] = None
    assert commands.stack_lines(rows) == "[#34]  main <- a1 <-[a2]"
    line = commands.legend(rows, "origin", marked=False)
    assert line.strip() == "[] current"  # nothing to explain but the brackets


def _with_prs(state, numbers):
    for stack, wanted in zip(state["stacks"], numbers):
        for entry, number in zip(stack["branches"], wanted):
            entry["pullRequest"] = {"number": number} if number else None
    return state


def test_summary_puts_the_pr_and_its_title_beside_each_branch():
    """One line per branch under its stack, with the same symbol, colour and
    brackets the one-line form uses -- and the columns measured across every
    stack shown, so the numbers line up down the whole page."""
    state = _with_prs(_state(names=("a1", "a2")), [(21, 22)])
    state["stacks"].append(
        {
            "number": 40,
            "trunk": {"branch": "main"},
            "branches": [
                {"branch": "b24", "pullRequest": {"number": 23}},
                # a branch with no PR yet still gets its line
                {"branch": "unpushed"},
            ],
        }
    )
    rows = commands.stack_rows(
        state,
        "a2",
        _sync(a1=gh.IN_SYNC, a2=gh.AHEAD, b24=gh.BEHIND, unpushed=gh.AHEAD),
    )
    titles = {21: "the loader", 22: "wire it up", 23: "the reader"}
    assert commands.stack_summary(rows, titles).splitlines() == [
        "[#34]  main",
        "       =a1        #21  the loader",
        "      +[a2]       #22  wire it up",
        "",
        " #40   main",
        "       -b24       #23  the reader",
        "       +unpushed  -",
    ]
    # every PR ref starts at the same column, and no line trails blanks
    lines = [
        line
        for line in commands.stack_summary(rows, titles).splitlines()
        if "#" in line and not line.startswith(("[", " #"))
    ]
    assert len({line.index("#") for line in lines}) == 1
    for line in commands.stack_summary(rows, titles).splitlines():
        assert line == line.rstrip(), line


def test_summary_keeps_the_symbols_and_brackets_of_the_one_line_form():
    rows = commands.stack_rows(
        _with_prs(_state(names=("a1", "a2")), [(21, 22)]),
        "a2",
        _sync(a1=gh.DIVERGED, a2=gh.BEHIND),
    )
    painted = commands.stack_summary(
        rows, {21: "one", 22: "two"}, lambda name, text: f"<{name or 'plain'}>{text}</>"
    ).splitlines()
    assert painted == [
        "<white>[</>#34<white>]</>  main",
        "       <red>x</><red>a1</>  #21  one",
        # the symbol hangs one column left of the plain symbols, exactly as it
        # does in the one-line form, and the bracket eats the space before the
        # PR ref -- so the NAMES line up whether they are bracketed or not
        "      <yellow>-</><white>[</><yellow>a2</><white>]</> #22  two",
    ]


def test_a_pr_title_gh_cannot_answer_is_warned_about_not_fatal(
    tmp_path, monkeypatch, capsys
):
    """The numbers are worth printing whatever gh says, so a title that cannot
    be had is named and left out rather than failing the command."""
    _fake_purge(monkeypatch, tmp_path, ["main"], {})
    (tmp_path / "gh-stack").write_text(
        json.dumps(_with_prs(_state(names=("a1", "a2")), [(21, 22)]))
    )
    monkeypatch.setattr(gh, "git_dir", lambda runner: tmp_path)
    monkeypatch.setattr(gh, "current_branch", lambda runner: "a2")
    monkeypatch.setattr(
        gh,
        "branch_sync",
        lambda runner, names, remote, *_: dict.fromkeys(names, gh.IN_SYNC),
    )
    monkeypatch.setattr(gh, "pr_titles", lambda runner, numbers: {21: "the loader"})
    assert gsx.main(["stack", "--no-fetch"]) == 0
    captured = capsys.readouterr()
    assert "could not read the title of #22" in captured.err
    assert "#21  the loader" in captured.out and "#22" in captured.out


def test_pr_titles_takes_one_listing_and_asks_only_for_what_it_missed():
    """A long-lived stack can hold a PR older than the listing's limit, and
    that is exactly the one whose branch is still lying around."""
    asked = []

    class Runner:
        dry_run = False

        def json(self, argv):
            asked.append(argv)
            if argv[:3] == ["gh", "pr", "list"]:
                return [
                    {"number": 21, "title": "the loader"},
                    {"number": 99, "title": "not asked for"},
                ]
            if argv[:3] == ["gh", "pr", "view"]:
                return {"title": "the old one"} if argv[3] == "22" else None
            return None

    assert gh.pr_titles(Runner(), [21, 22, 23]) == {
        21: "the loader",
        22: "the old one",
    }
    assert sum(1 for call in asked if call[:3] == ["gh", "pr", "list"]) == 1
    # one lookup per number the listing did not answer, and no more
    views = [call for call in asked if call[:3] == ["gh", "pr", "view"]]
    assert [call[3] for call in views] == ["22", "23"]
    assert gh.pr_titles(Runner(), []) == {}


def test_the_legend_is_one_line_and_shows_each_symbol_in_its_own_colour():
    rows = commands.stack_rows(_state(names=("a1",)), "a1", _sync(a1=gh.IN_SYNC))
    assert commands.legend(rows, "origin") == (
        "  = in sync  + ahead  - behind  x diverged  [] current"
    )
    # `?` earns its place only when a row actually uses it
    missing = commands.stack_rows(_state(names=("a1",)), "", {})
    assert "? no local branch" in commands.legend(missing, "origin")
    # ...and a branch only GitHub has is not counted as one: it has no local
    # copy by definition, and both entries wear `?`, so a listing whose only
    # `?` were remote-only ones explained the same symbol twice
    theirs = commands.stack_rows({"stacks": []}, "", remote=[_listed(41, [(52, "c1")])])
    line = commands.legend(theirs, "origin")
    assert "? remote only" in line and "no local branch" not in line
    # and each symbol demonstrates its own colour
    painted = commands.legend(rows, "up", lambda name, text: f"<{name}>{text}</>")
    assert "<green>=</> in sync" in painted and "<red>x</> diverged" in painted
    assert "<white>[]</> current" in painted
    # the remote is not named -- but not fetching first IS said, because every
    # symbol is then about the remote as it WAS
    assert commands.legend(rows, "origin", fetched=False).endswith(
        "(as of the last fetch)"
    )
    assert "origin" not in commands.legend(rows, "origin")


def test_stack_fetches_first_because_in_sync_is_a_claim_about_the_remote(
    tmp_path, monkeypatch, capsys
):
    """A branch the remote has moved on from has an up-to-date local ref and a
    STALE remote-tracking ref, so it reads `=` in green -- a confident wrong
    answer, which is worse than a slow one. Found in a real checkout: TUCU-45
    showed `=` while the server was three commits ahead of the tracking ref."""
    calls = _fake_purge(monkeypatch, tmp_path, ["main"], {})
    (tmp_path / "gh-stack").write_text(json.dumps(_state()))
    monkeypatch.setattr(gh, "git_dir", lambda runner: tmp_path)
    monkeypatch.setattr(gh, "current_branch", lambda runner: "a2")
    monkeypatch.setattr(
        gh,
        "branch_sync",
        lambda runner, names, remote, *_: {"a1": gh.IN_SYNC, "a2": gh.AHEAD},
    )
    assert gsx.main(["stack"]) == 0
    assert ["git", "fetch", "-q", "origin"] in calls
    # and it is not announced: a precondition of the answer, not a step
    captured = capsys.readouterr()
    assert "fetch" not in captured.err and "as of the last fetch" not in captured.out

    calls.clear()
    assert gsx.main(["stack", "--no-fetch"]) == 0
    assert not any(call[:2] == ["git", "fetch"] for call in calls)
    assert "(as of the last fetch)" in capsys.readouterr().out


def test_the_legend_is_set_off_by_a_blank_line_on_each_side(
    tmp_path, monkeypatch, capsys
):
    """It is a key to what is above it, not another row of it."""
    _fake_purge(monkeypatch, tmp_path, ["main"], {})
    (tmp_path / "gh-stack").write_text(json.dumps(_state()))
    monkeypatch.setattr(gh, "git_dir", lambda runner: tmp_path)
    monkeypatch.setattr(gh, "current_branch", lambda runner: "a2")
    monkeypatch.setattr(
        gh,
        "branch_sync",
        lambda runner, names, remote, *_: {"a1": gh.IN_SYNC, "a2": gh.AHEAD},
    )
    assert gsx.main(["stack", "--short"]) == 0
    lines = capsys.readouterr().out.split("\n")
    # no count line over a single stack: the row already says which one
    assert lines[0] == "[#34]  main <- =a1 <-+[a2]"
    assert lines[1] == ""
    assert lines[2].startswith("  = in sync")
    assert lines[3] == "" and lines[4] == ""  # the blank after it, then EOF


class _SyncRunner:
    """git for the sync check: `refs` are the shas, `counts` the rev-list answers."""

    dry_run = False

    def __init__(self, refs, counts=None):
        self.refs = refs
        self.counts = counts or {}
        self.calls = []

    def run(self, argv, **kwargs):
        self.calls.append(argv)
        if argv[:2] == ["git", "for-each-ref"]:
            return "\n".join(f"{ref} {sha}" for ref, sha in self.refs.items())
        if argv[:2] == ["git", "rev-list"]:
            return self.counts.get(argv[-1], "0\t0")
        return ""


def test_a_branch_the_remote_rebased_is_behind_not_diverged():
    """`gh stack` rebases everything above a branch that moved and force-pushes
    it, so the remote copy of a branch is rewritten constantly. Compared by sha
    that is divergence and nearly every branch reads `x`; compared by CHANGE
    (--cherry-pick drops a commit whose patch is already on the other side) it
    is what it is -- behind by what the remote genuinely gained.

    Real case: TUCU-47 held `[TUCU-47] x` as e8d7c6a while the remote held the
    same patch as 9d40f0d plus one more commit. Identical patch-ids; raw counts
    1/2 (diverged), cherry-picked counts 0/1 (behind)."""
    refs = {
        "refs/heads/rebased": "local",
        "refs/remotes/origin/rebased": "remote",
    }
    runner = _SyncRunner(refs, {"local...remote": "0\t1"})
    assert gh.branch_sync(runner, ["rebased"], "origin") == {"rebased": gh.BEHIND}
    # and the comparison is by change, not by sha
    revlist = next(c for c in runner.calls if c[:2] == ["git", "rev-list"])
    assert "--cherry-pick" in revlist

    # genuinely different work on each side is still divergence
    runner = _SyncRunner(refs, {"local...remote": "2\t3"})
    assert gh.branch_sync(runner, ["rebased"], "origin") == {"rebased": gh.DIVERGED}
    # the same changes under different shas is not a difference worth a symbol
    runner = _SyncRunner(refs, {"local...remote": "0\t0"})
    assert gh.branch_sync(runner, ["rebased"], "origin") == {"rebased": gh.IN_SYNC}


def test_the_trunks_commits_are_not_the_branchs():
    """A branch rebased onto a newer trunk carries commits its remote copy does
    not, and every one of them is the trunk's. Ten branches of a real stack
    (#3478 in tabsdata-os) read `+` for that reason with nothing local about
    them: the two "unpushed" commits were `[TD-3364] Edition gate` and
    `[TD-3363] New tdkserver subcommand`, both off main. `--not <trunk>` leaves
    the question the symbol is for -- this branch's own work against the copy
    on the remote."""
    refs = {
        "refs/heads/a2": "local",
        "refs/remotes/origin/a2": "remote",
        "refs/remotes/origin/main": "trunk",
    }
    # what the counts are once the trunk is out of the range
    runner = _SyncRunner(refs, {"local...remote": "0\t0"})
    assert gh.branch_sync(runner, ["a2"], "origin", {"a2": "main"}) == {
        "a2": gh.IN_SYNC
    }
    revlist = next(call for call in runner.calls if call[:2] == ["git", "rev-list"])
    assert revlist[-2:] == ["--not", "refs/remotes/origin/main"]

    # a trunk that was never pushed is compared against the local one
    del refs["refs/remotes/origin/main"]
    refs["refs/heads/main"] = "trunk"
    runner = _SyncRunner(refs, {"local...remote": "0\t0"})
    gh.branch_sync(runner, ["a2"], "origin", {"a2": "main"})
    revlist = next(call for call in runner.calls if call[:2] == ["git", "rev-list"])
    assert revlist[-2:] == ["--not", "refs/heads/main"]

    # and with no trunk to exclude, the range is the range
    runner = _SyncRunner(refs, {"local...remote": "1\t0"})
    assert gh.branch_sync(runner, ["a2"], "origin") == {"a2": gh.AHEAD}
    revlist = next(call for call in runner.calls if call[:2] == ["git", "rev-list"])
    assert "--not" not in revlist


def test_the_sync_state_of_every_branch_costs_one_call_plus_the_odd_ones_out():
    """One `for-each-ref` collects every sha; only a branch whose two shas
    differ needs a second call, and a branch with nothing on the remote needs
    none -- there is no remote copy for it to be behind."""
    refs = {
        "refs/heads/insync": "aaa",
        "refs/remotes/origin/insync": "aaa",
        "refs/heads/ahead": "bbb",
        "refs/remotes/origin/ahead": "b0",
        "refs/heads/behind": "ccc",
        "refs/remotes/origin/behind": "c0",
        "refs/heads/diverged": "ddd",
        "refs/remotes/origin/diverged": "d0",
        "refs/heads/unpushed": "eee",
    }
    counts = {"bbb...b0": "2\t0", "ccc...c0": "0\t3", "ddd...d0": "1\t1"}
    runner = _SyncRunner(refs, counts)
    names = ["insync", "ahead", "behind", "diverged", "unpushed", "gone"]
    assert gh.branch_sync(runner, names, "origin") == {
        "insync": gh.IN_SYNC,
        "ahead": gh.AHEAD,
        "behind": gh.BEHIND,
        "diverged": gh.DIVERGED,
        "unpushed": gh.AHEAD,
        "gone": gh.NO_LOCAL,
    }
    # one listing, and a rev-list only for the three whose shas differ
    assert sum(1 for call in runner.calls if call[:2] == ["git", "for-each-ref"]) == 1
    assert sum(1 for call in runner.calls if call[:2] == ["git", "rev-list"]) == 3


def test_the_remote_is_gh_stacks_own_and_git_config_reads_stay_read_only():
    """`git config KEY` reads and belongs in a dry run; `git config KEY VALUE`
    writes and does not."""
    assert gh.is_read_only(["git", "config", "gh-stack.remote"])
    assert not gh.is_read_only(["git", "config", "gh-stack.remote", "upstream"])
    assert not gh.is_read_only(["git", "config", "--unset", "gh-stack.remote"])
    assert gh.is_read_only(["git", "rev-list", "--count", "a...b"])

    class Runner:
        dry_run = False

        def run(self, argv, **kwargs):
            return "upstream" if argv[:2] == ["git", "config"] else ""

    assert gh.stack_remote(Runner()) == "upstream"

    class Empty(Runner):
        def run(self, argv, **kwargs):
            return ""

    assert gh.stack_remote(Empty()) == "origin"


def test_stack_answers_none_rather_than_failing_when_nothing_is_tracked(
    tmp_path, monkeypatch, capsys
):
    """Asked what stacks exist, "none" is an answer rather than a failure, so
    the reader reports an absent file as empty and the caller decides."""
    _fake_purge(monkeypatch, tmp_path, ["main"], {})
    monkeypatch.setattr(gh, "git_dir", lambda runner: tmp_path)
    assert gsx.main(["stack", "--format", "json"]) == 0
    last = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert last["event"] == "ok" and last["stacks"] == []
    assert "no stacks are tracked" in last["message"]


def test_only_the_stack_you_are_on_unless_all_is_asked_for(
    tmp_path, monkeypatch, capsys
):
    """`stack` answers about the one you are on; `--all` is the listing. And
    the sync check only costs what is shown -- the default does not compare
    branches it is not going to print."""
    asked = []
    _fake_purge(monkeypatch, tmp_path, ["main"], {})
    state = _state(names=("a1", "a2"))
    state["stacks"].append(
        {
            "number": 40,
            "trunk": {"branch": "main"},
            "branches": [{"branch": "b24"}],
        }
    )
    (tmp_path / "gh-stack").write_text(json.dumps(state))
    monkeypatch.setattr(gh, "git_dir", lambda runner: tmp_path)
    monkeypatch.setattr(gh, "current_branch", lambda runner: "a2")
    monkeypatch.setattr(
        gh,
        "branch_sync",
        lambda runner, names, remote, *_: (
            asked.append(list(names)) or dict.fromkeys(names, gh.IN_SYNC)
        ),
    )

    assert gsx.main(["stack", "--no-fetch"]) == 0
    out = capsys.readouterr().out
    assert "[#34]" in out and "#40" not in out
    assert asked == [["a1", "a2"]]  # b24 was never compared

    asked.clear()
    assert gsx.main(["stack", "--all", "--no-fetch"]) == 0
    out = capsys.readouterr().out
    assert "2 stack(s):" in out and "[#34]" in out and "#40" in out
    assert asked == [["a1", "a2", "b24"]]

    # standing outside every stack, the useful half of the answer is --all
    monkeypatch.setattr(gh, "current_branch", lambda runner: "main")
    assert gsx.main(["stack", "--no-fetch"]) == 0
    assert "not in a tracked stack; --all lists the 2" in capsys.readouterr().out


def test_the_default_view_is_one_line_per_pr_and_short_is_the_chain(
    tmp_path, monkeypatch, capsys
):
    """The per-PR view is what a reader wants first -- which PRs, called what,
    and where each stands. `--short` is the chain, for when the shape of the
    stack is the question."""
    _fake_purge(monkeypatch, tmp_path, ["main"], {})
    (tmp_path / "gh-stack").write_text(
        json.dumps(_with_prs(_state(names=("a1", "a2")), [(21, 22)]))
    )
    monkeypatch.setattr(gh, "git_dir", lambda runner: tmp_path)
    monkeypatch.setattr(gh, "current_branch", lambda runner: "a2")
    monkeypatch.setattr(
        gh,
        "branch_sync",
        lambda runner, names, remote, *_: dict.fromkeys(names, gh.IN_SYNC),
    )
    monkeypatch.setattr(
        gh, "pr_titles", lambda runner, numbers: {21: "the loader", 22: "wire it up"}
    )

    assert gsx.main(["stack", "--no-fetch"]) == 0
    out = capsys.readouterr().out
    assert "#21  the loader" in out and "#22  wire it up" in out
    assert "<-" not in out  # the chain is the other view

    assert gsx.main(["stack", "--short", "--no-fetch"]) == 0
    out = capsys.readouterr().out
    assert "[#34]  main <- =a1 <-=[a2]" in out
    assert "the loader" not in out  # and it asks gh for no titles

    # -a and -s are the short forms, and they bundle
    assert gsx.main(["stack", "-s", "--no-fetch"]) == 0
    assert "[#34]  main <- =a1 <-=[a2]" in capsys.readouterr().out
    assert gsx.main(["stack", "-as", "--no-fetch"]) == 0
    out = capsys.readouterr().out
    assert "1 stack(s):" in out and "<-" in out


def test_the_gh_stack_extension_is_never_needed(tmp_path, monkeypatch, capsys):
    """Requiring it would refuse a checkout that has stacks but no extension.
    `gh` itself is asked for the PR titles and for GitHub's own listing --
    `--short` skips the first and `--local` both."""
    _fake_purge(monkeypatch, tmp_path, ["main"], {})
    monkeypatch.setattr(gh, "stacks", lambda runner: [])
    for name in ("require_tools", "require_binaries"):
        monkeypatch.setattr(
            gh,
            name,
            lambda *a, **k: (_ for _ in ()).throw(ToolError("should not be called")),
        )
    (tmp_path / "gh-stack").write_text(json.dumps(_state()))
    monkeypatch.setattr(gh, "git_dir", lambda runner: tmp_path)
    monkeypatch.setattr(gh, "current_branch", lambda runner: "a2")
    monkeypatch.setattr(
        gh,
        "branch_sync",
        lambda runner, names, remote, *_: {"a1": gh.IN_SYNC, "a2": gh.AHEAD},
    )
    assert gsx.main(["stack", "--short"]) == 0
    out = capsys.readouterr().out
    assert "[#34]  main <- =a1 <-+[a2]" in out and "[] current" in out


def test_the_default_view_asks_github_and_local_asks_nobody(
    tmp_path, monkeypatch, capsys
):
    """`--local` is the offline view: no listing, no titles, no extension, and
    with `--short` no `gh` at all. The default asks for the listing, because
    what only GitHub has is half of what it is for."""
    _fake_purge(monkeypatch, tmp_path, ["main"], {})
    (tmp_path / "gh-stack").write_text(json.dumps(_state()))
    monkeypatch.setattr(gh, "git_dir", lambda runner: tmp_path)
    monkeypatch.setattr(gh, "current_branch", lambda runner: "a2")
    monkeypatch.setattr(
        gh,
        "branch_sync",
        lambda runner, names, remote, *_: dict.fromkeys(names, gh.AHEAD),
    )
    asked = []
    monkeypatch.setattr(gh, "stacks", lambda runner: asked.append("gh api") or [])
    assert gsx.main(["stack", "--short", "--no-fetch"]) == 0
    assert asked == ["gh api"]
    capsys.readouterr()

    # --local asks for none of it, and neither gh nor its extension is touched
    asked.clear()
    for name in ("require_tools", "require_binaries", "stacks", "pr_titles"):
        monkeypatch.setattr(
            gh,
            name,
            lambda *a, **k: (_ for _ in ()).throw(ToolError("should not be called")),
        )
    assert gsx.main(["stack", "--local", "--short"]) == 0
    out = capsys.readouterr().out
    assert "[#34]  main <- a1 <-[a2]" in out  # ...and so no sync symbols
    assert "in sync" not in out and "[] current" in out


def test_remote_shows_githubs_own_stacks_and_local_the_tracked_ones(
    tmp_path, monkeypatch, capsys
):
    _fake_purge(monkeypatch, tmp_path, ["main"], {})
    (tmp_path / "gh-stack").write_text(json.dumps(_state(names=("a1", "a2"))))
    monkeypatch.setattr(gh, "git_dir", lambda runner: tmp_path)
    monkeypatch.setattr(gh, "current_branch", lambda runner: "a2")
    monkeypatch.setattr(
        gh,
        "stacks",
        lambda runner: [
            _listed(34, [(21, "a1"), (22, "a2"), (29, "a3")]),
            _listed(41, [(52, "c1")]),
        ],
    )
    monkeypatch.setattr(gh, "pr_titles", lambda runner, numbers: {})

    assert gsx.main(["stack", "--remote", "--all", "--short"]) == 0
    out = capsys.readouterr().out
    assert "2 stack(s) on GitHub:" in out
    # the brackets ARE the spaces around `<-`, so a bracketed cell touches
    # what follows it
    # `a1` pads to the width of `?c1`: columns are measured across every stack
    assert " [#34]  main <- a1  <-[a2]<- ?a3" in out
    assert "? #41   main <- ?c1" in out
    assert "? remote only" in out and "in sync" not in out

    assert gsx.main(["stack", "--local", "--all", "--short"]) == 0
    out = capsys.readouterr().out
    assert "1 stack(s) tracked here:" in out and "#41" not in out


def test_a_stack_github_has_that_is_not_tracked_here_is_named_without_all(
    tmp_path, monkeypatch, capsys
):
    """The default answers about your stack, so a stack you have never checked
    out cannot appear in it -- but not being told it exists is worse."""
    _fake_purge(monkeypatch, tmp_path, ["main"], {})
    (tmp_path / "gh-stack").write_text(json.dumps(_state()))
    monkeypatch.setattr(gh, "git_dir", lambda runner: tmp_path)
    monkeypatch.setattr(gh, "current_branch", lambda runner: "a2")
    monkeypatch.setattr(
        gh,
        "branch_sync",
        lambda runner, names, remote, *_: dict.fromkeys(names, gh.AHEAD),
    )
    monkeypatch.setattr(gh, "stacks", lambda runner: [_listed(41, [(52, "c1")])])
    assert gsx.main(["stack", "--short", "--no-fetch"]) == 0
    said = capsys.readouterr()
    # an info event, so it goes to stderr; the rows on stdout are yours alone
    assert "1 stack(s) on GitHub are not tracked here; --all lists them" in said.err
    assert "#41" not in said.out


def test_a_stack_github_no_longer_has_is_marked_and_named_without_all(
    tmp_path, monkeypatch, capsys
):
    """The mirror, and the one that costs something: a stack this checkout
    still tracks that GitHub has no open stack for is a leftover, and from
    inside another stack it would otherwise be invisible."""
    state = _with_prs(_state(number=3488, names=("a1", "a2")), [(21, 22)])
    state["stacks"].append(
        {
            "number": 3478,
            "trunk": {"branch": "main"},
            "branches": [{"branch": "b1", "pullRequest": {"number": 11}}],
        }
    )
    _fake_purge(monkeypatch, tmp_path, ["main"], {})
    (tmp_path / "gh-stack").write_text(json.dumps(state))
    monkeypatch.setattr(gh, "git_dir", lambda runner: tmp_path)
    monkeypatch.setattr(gh, "current_branch", lambda runner: "a2")
    monkeypatch.setattr(
        gh,
        "branch_sync",
        lambda runner, names, remote, *_: dict.fromkeys(names, gh.IN_SYNC),
    )
    monkeypatch.setattr(
        gh, "stacks", lambda runner: [_listed(3495, [(21, "a1"), (22, "a2")])]
    )
    assert gsx.main(["stack", "--short", "--no-fetch"]) == 0
    said = capsys.readouterr()
    # the stack you are on is one of them, and it says so where it stands
    assert "![#3488]  main <- =a1 <-=[a2]" in said.out
    assert "! local only" in said.out
    # the other one is not shown at all without --all, so it is named
    assert "1 stack(s) tracked here are not open on GitHub; --all lists them" in (
        said.err
    )
    assert gsx.main(["stack", "--short", "--no-fetch", "--all"]) == 0
    out = capsys.readouterr().out
    assert "! #3478   main <- !b1" in out


def test_a_listing_github_cannot_give_is_fatal_only_for_remote(
    tmp_path, monkeypatch, capsys
):
    """For the default the local half is still an answer, and saying it may be
    incomplete is enough. For `--remote` the listing IS the answer."""
    _fake_purge(monkeypatch, tmp_path, ["main"], {})
    (tmp_path / "gh-stack").write_text(json.dumps(_state()))
    monkeypatch.setattr(gh, "git_dir", lambda runner: tmp_path)
    monkeypatch.setattr(gh, "current_branch", lambda runner: "a2")
    monkeypatch.setattr(
        gh,
        "branch_sync",
        lambda runner, names, remote, *_: dict.fromkeys(names, gh.AHEAD),
    )
    monkeypatch.setattr(
        gh,
        "stacks",
        lambda runner: (_ for _ in ()).throw(ToolError("gh: HTTP 403")),
    )
    assert gsx.main(["stack", "--short", "--no-fetch"]) == 0
    said = capsys.readouterr()
    assert "could not list the stacks on GitHub" in said.err
    assert "[#34]  main <- +a1 <-+[a2]" in said.out

    assert gsx.main(["stack", "--remote", "--short"]) == 1
    assert "could not list the stacks on GitHub" in capsys.readouterr().err


def test_remote_and_local_together_are_refused(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TDD_DIR", str(tmp_path))
    monkeypatch.setattr(gh, "require_repo", lambda runner: None)
    assert gsx.main(["stack", "-r", "-l"]) == 1
    assert "at most one of --remote and --local" in capsys.readouterr().err


def test_stack_puts_no_escape_in_the_json_message(tmp_path, monkeypatch, capsys):
    """The json message is data. How every branch stands is in the fields,
    which is what a machine reads -- an escape there would be data too."""
    _fake_purge(monkeypatch, tmp_path, ["main"], {})
    (tmp_path / "gh-stack").write_text(json.dumps(_state()))
    monkeypatch.setattr(gh, "git_dir", lambda runner: tmp_path)
    monkeypatch.setattr(gh, "current_branch", lambda runner: "a2")
    monkeypatch.setattr(
        gh,
        "branch_sync",
        lambda runner, names, remote, *_: {"a1": gh.IN_SYNC, "a2": gh.AHEAD},
    )
    assert gsx.main(["stack", "--format", "json"]) == 0
    line = capsys.readouterr().out.splitlines()[-1]
    assert "\033" not in line and "\\u001b" not in line
    event = json.loads(line)
    assert event["remote"] == "origin" and event["fetched"] is True
    assert event["stacks"][0]["branches"][1] == {
        "name": "a2",
        "pr": None,
        "sync": "ahead",
        "current": True,
        "remote_only": False,
        "local_only": False,
    }


# -------------------------------------------------------------------- sync
def _ancestor(pairs):
    """An is-ancestor oracle from the pairs that are true."""
    return lambda older, newer: (older, newer) in pairs


def test_a_branch_is_classified_by_what_the_remote_has_that_it_does_not():
    # theirs already in ours: nothing to take
    assert sync_mod.classify("a", "b", _ancestor({("b", "a")})) == sync_mod.CURRENT
    # identical without asking git at all
    assert sync_mod.classify("a", "a", _ancestor(set())) == sync_mod.CURRENT
    # ours in theirs: a fast-forward
    assert sync_mod.classify("a", "b", _ancestor({("a", "b")})) == sync_mod.BEHIND
    # neither: both added commits, which is the case the whole design is about
    assert sync_mod.classify("a", "b", _ancestor(set())) == sync_mod.DIVERGED
    # and a branch the remote has never seen is submit's business, not sync's
    assert sync_mod.classify("a", "", _ancestor(set())) == sync_mod.UNPUBLISHED


def _fake_git(monkeypatch, shas, ancestors, current="B2", window=()):
    """A runner answering rev-parse, merge-base and rev-list from fixtures."""
    calls = []

    class FakeRunner:
        def __init__(self, out=None, dry_run=False):
            self.out = out
            self.dry_run = dry_run

        def run(self, argv, **kwargs):
            calls.append(argv)
            if argv[:2] == ["git", "rev-parse"] and "--verify" in argv:
                return shas.get(argv[-1], "")
            if argv[:2] == ["git", "merge-base"]:
                return "base-sha"
            if argv[:3] == ["git", "rev-parse", "--abbrev-ref"]:
                return current
            if argv[:2] == ["git", "rev-list"]:
                return " ".join(window)
            return ""

        def json(self, argv):
            return None

    monkeypatch.setattr(
        gh, "is_ancestor", lambda runner, a, b: a == b or (a, b) in ancestors
    )
    return FakeRunner(out=None), calls


class _Say:
    def __init__(self):
        self.said = []

    def info(self, message, **fields):
        self.said.append(message)

    def warn(self, message, **fields):
        self.said.append(message)

    def debug(self, message, **fields):
        pass


def test_reconcile_touches_only_what_needs_it(monkeypatch):
    shas = {
        "refs/heads/B1": "l1",
        "refs/remotes/origin/B1": "l1",  # identical: nothing to do
        "refs/heads/B2": "l2",
        "refs/remotes/origin/B2": "r2",  # diverged
        "refs/heads/B3": "l3",
        "refs/remotes/origin/B3": "r3",  # we are behind
    }
    runner, calls = _fake_git(monkeypatch, shas, ancestors={("l3", "r3")})
    out = _Say()
    done = sync_mod.reconcile(runner, ["B1", "B2", "B3"], "origin", out)
    assert done == {
        "B1": sync_mod.CURRENT,
        "B2": sync_mod.DIVERGED,
        "B3": sync_mod.BEHIND,
    }
    rebases = [c for c in calls if c[:2] == ["git", "rebase"]]
    # one plain `git rebase <remote>/<branch>` each, and none for B1: the same
    # command fast-forwards onto an ancestor and replays onto a divergence
    assert rebases == [
        ["git", "rebase", "origin/B2"],
        ["git", "rebase", "origin/B3"],
    ]


def test_restack_skips_a_branch_a_teammate_already_restacked(monkeypatch):
    """The commonest case once reconcile has run: they pushed the answer and
    our fast-forward to it left nothing to do."""
    shas = {f"refs/heads/{b}": b for b in ("main", "B1", "B2", "B3")}
    # B1 and B2 are already on their parents; B3 is not
    runner, calls = _fake_git(
        monkeypatch, shas, ancestors={("main", "B1"), ("B1", "B2")}
    )
    out = _Say()
    assert sync_mod.restack(runner, ["B1", "B2", "B3"], "main", out) == ["B3"]
    assert [c for c in calls if c[:2] == ["git", "rebase"]] == [
        ["git", "rebase", "--onto", "B2", "base-sha", "B3"]
    ]


def test_only_a_rewritten_branch_is_pushed_with_a_lease(monkeypatch):
    shas = {
        "refs/heads/B1": "l1",
        "refs/remotes/origin/B1": "l1",  # unchanged: not pushed at all
        "refs/heads/B2": "l2",
        "refs/remotes/origin/B2": "r2",  # fast-forward
        "refs/heads/B3": "l3",
        "refs/remotes/origin/B3": "r3",  # rewritten
        "refs/heads/B4": "l4",
        "refs/remotes/origin/B4": "",  # never pushed
    }
    runner, _ = _fake_git(monkeypatch, shas, ancestors={("r2", "l2")})
    plain, forced, leases = sync_mod.push_args(
        runner, ["B1", "B2", "B3", "B4"], "origin"
    )
    assert plain == ["B2", "B4"] and forced == ["B3"]
    # the lease is pinned to the sha THIS run fetched, so a remote that moved
    # in between is a refusal rather than a loss
    assert leases == ["--force-with-lease=refs/heads/B3:r3"]


def test_unreconciled_names_exactly_what_would_be_overwritten(monkeypatch):
    shas = {
        "refs/heads/B1": "l1",
        "refs/remotes/origin/B1": "l1",
        "refs/heads/B2": "l2",
        "refs/remotes/origin/B2": "r2",  # diverged
        "refs/heads/B3": "l3",
        "refs/remotes/origin/B3": "r3",  # behind
        "refs/heads/B4": "l4",
        "refs/remotes/origin/B4": "",
    }
    runner, _ = _fake_git(monkeypatch, shas, ancestors={("l3", "r3")})
    assert sync_mod.unreconciled(runner, ["B1", "B2", "B3", "B4"], "origin") == [
        "B2",
        "B3",
    ]


# ------------------------------------------------------------------- hooks
def test_the_guard_ships_inside_the_package_and_says_what_it_refuses():
    text = hooks_mod.script()
    assert text.startswith("#!/bin/sh")
    # both rules, and the override, are in the file itself: it is read by
    # whoever is refused by it
    assert "GIT_ALLOW_OVERWRITE" in text
    assert "never reachable" in text or "never part of your local" in text
    assert "append-only" in text


def test_install_writes_an_executable_hook_and_points_git_at_it(tmp_path, monkeypatch):
    root = tmp_path / "clone"
    (root / ".git").mkdir(parents=True)
    config = {}

    class FakeRunner:
        out = None
        dry_run = False

        def run(self, argv, **kwargs):
            if argv[:3] == ["git", "rev-parse", "--show-toplevel"]:
                return str(root)
            if argv[:2] == ["git", "config"] and len(argv) == 4:
                config[argv[2]] = argv[3]
                return ""
            if argv[:2] == ["git", "config"]:
                return config.get(argv[2], "")
            return ""

    runner = FakeRunner()
    path, changed = hooks_mod.install(runner, hooks_mod.REPO, force=False)
    assert path == root / ".githooks" / "pre-push"
    assert changed is True
    assert path.read_text() == hooks_mod.script()
    assert path.stat().st_mode & 0o111  # executable, or git ignores it
    # a relative path, so the same string works in every clone -- which is what
    # makes it committable
    assert config["core.hooksPath"] == ".githooks"
    # ...and running it again changes nothing
    _, changed = hooks_mod.install(runner, hooks_mod.REPO, force=False)
    assert changed is False


def test_a_hook_gsx_did_not_write_is_not_silently_replaced(tmp_path):
    root = tmp_path / "clone"
    (root / ".githooks").mkdir(parents=True)
    theirs = root / ".githooks" / "pre-push"
    theirs.write_text("#!/bin/sh\n# somebody else's\n")

    class FakeRunner:
        out = None
        dry_run = False

        def run(self, argv, **kwargs):
            if argv[:3] == ["git", "rev-parse", "--show-toplevel"]:
                return str(root)
            return ""

    with pytest.raises(ToolError, match="already exists"):
        hooks_mod.install(FakeRunner(), hooks_mod.REPO, force=False)
    assert theirs.read_text() == "#!/bin/sh\n# somebody else's\n"
    # --force is the way through, and it says so above
    hooks_mod.install(FakeRunner(), hooks_mod.REPO, force=True)
    assert theirs.read_text() == hooks_mod.script()


def test_a_move_is_noticed_by_the_parents_NAME_not_by_ancestry():
    """The first version asked whether `<remote>/<base>` was an ancestor of the
    branch, which is also false in the commonest case there is -- a parent that
    has simply gained commits this clone has not restacked onto yet. Measured
    in tabsdata-os: OS-3508, whose local parent and whose PR base were both
    OS-3505, was reported as "moved off its base here" and cherry-picked when a
    plain fast-forward was what it needed."""
    branches = ["OS-3504", "OS-3505", "OS-3508", "OS-3510"]
    bases = {
        "OS-3504": "main",
        "OS-3505": "OS-3504",
        "OS-3508": "OS-3505",
        "OS-3510": "OS-3508",
    }
    # every base is still a branch of this stack: nothing has been moved here,
    # however far behind the branches are
    assert sync_mod.moved_branches(branches, "main", bases) == set()

    # ...and a base that has LANDED, whose local branch is gone and so is not
    # in the list any more, is not a move either: its commits are in the trunk
    # now and the ordinary reconcile drops them as already upstream
    landed = ["OS-3508", "OS-3510"]
    assert (
        sync_mod.moved_branches(
            landed, "main", bases, known={"OS-3504", "OS-3505", "OS-3508", "OS-3510"}
        )
        == set()
    )

    # the bottom of a moved slice is the one with a new parent name...
    moved_bases = {"A3": "A2"}
    assert sync_mod.moved_branches(["C2", "A3"], "main", moved_bases) == {"A3"}

    # ...and the move taints everything above it, because those keep their old
    # parent names while their remote copies still sit on the old chain
    slice_bases = {"M1": "OLD", "M2": "M1", "M3": "M2"}
    assert sync_mod.moved_branches(["C2", "M1", "M2", "M3"], "main", slice_bases) == {
        "M1",
        "M2",
        "M3",
    }

    # a branch with no PR has no recorded base to disagree with: it cannot
    # start a taint, but it inherits one
    assert sync_mod.moved_branches(["A3", "new"], "main", {"A3": "A2"}) == {
        "A3",
        "new",
    }
    assert sync_mod.moved_branches(["new"], "main", {}) == set()

    # the bottom branch's parent is the trunk
    assert sync_mod.moved_branches(["B1"], "main", {"B1": "main"}) == set()
    assert sync_mod.moved_branches(["B1"], "main", {"B1": "other"}) == {"B1"}

    # ...and a branch whose PR still targets the TRUNK while it sits on a stack
    # here is the plainest move there is: `gsx move --to <top>` on an
    # unsubmitted branch makes exactly it. An earlier version excused the trunk
    # and sent it down the ordinary path, where `git rebase <remote>/<branch>`
    # would have replayed a whole 32-branch stack onto a copy of the branch
    # that still sat on the trunk. Measured in tabsdata-os: OS-3512, PR base
    # `main`, local parent `OS-3510`.
    onto_stack = ["OS-3505", "OS-3508", "OS-3510", "OS-3512"]
    bases_onto = {
        "OS-3505": "OS-3504",
        "OS-3508": "OS-3505",
        "OS-3510": "OS-3508",
        "OS-3512": "main",
    }
    # `known` is the whole stack as gh-stack tracks it, OS-3504 included, so
    # only the branch whose base left the stack is the move
    known = set(onto_stack) | {"OS-3504"}
    assert sync_mod.moved_branches(onto_stack, "main", bases_onto, known) == {"OS-3512"}


def test_a_moved_branch_takes_only_the_remotes_OWN_commits(monkeypatch):
    """Measured on a real move: reconciling a moved branch with a plain
    `git rebase origin/<branch>` dragged the old parent chain back in -- a
    branch that should have carried three commits over its new parent came
    back carrying eight, the extra five belonging to the two PRs it had just
    been moved away from."""
    shas = {
        "refs/heads/A3": "a3",
        "refs/remotes/origin/A3": "r3",
        "refs/remotes/origin/A2": "old-parent",
    }
    runner, calls = _fake_git(
        monkeypatch, shas, ancestors=set(), window=("theirs1", "theirs2")
    )
    out = _Say()
    done = sync_mod.reconcile(runner, ["A3"], "origin", out, bases={"A3": "A2"})
    assert done == {"A3": sync_mod.DIVERGED}
    # cherry-picked onto where it now sits, NOT rebased onto its remote copy
    assert ["git", "cherry-pick", "theirs1", "theirs2"] in calls
    assert not any(c[:2] == ["git", "rebase"] for c in calls)
    # and the window is measured from the PR's base, oldest first
    window = [c for c in calls if c[:2] == ["git", "rev-list"]][0]
    assert "--reverse" in window and "--cherry-pick" in window
    assert window[-2:] == ["--not", "origin/A2"]
    assert "A3...origin/A3" in window


def test_a_moved_branch_with_nothing_new_on_the_remote_is_left_alone(monkeypatch):
    shas = {
        "refs/heads/A3": "a3",
        "refs/remotes/origin/A3": "r3",
        "refs/remotes/origin/A2": "old-parent",
    }
    runner, calls = _fake_git(monkeypatch, shas, ancestors=set(), window=())
    assert sync_mod.reconcile(runner, ["A3"], "origin", _Say(), bases={"A3": "A2"}) == {
        "A3": sync_mod.CURRENT
    }
    assert not any(c[:2] == ["git", "cherry-pick"] for c in calls)


def test_a_reconciled_move_is_not_reported_as_unreconciled(monkeypatch):
    """The cherry-pick gives those commits new shas, so `origin/<branch>` is
    deliberately not an ancestor afterwards. Asking whether it is called every
    correctly reconciled move unreconciled -- and `submit --move` refused a
    branch that was holding every commit the remote had."""
    shas = {
        "refs/heads/A3": "a3",
        "refs/remotes/origin/A3": "r3",
        "refs/remotes/origin/A2": "old-parent",
    }
    bases = {"A3": "A2"}
    # nothing of the remote's own is missing: reconciled, whatever ancestry says
    runner, _ = _fake_git(monkeypatch, shas, ancestors=set(), window=())
    assert sync_mod.unreconciled(runner, ["A3"], "origin", bases) == []
    # something IS missing: that is the refusal `submit --move` needs
    runner, _ = _fake_git(monkeypatch, shas, ancestors=set(), window=("theirs",))
    assert sync_mod.unreconciled(runner, ["A3"], "origin", bases) == ["A3"]


# -------------------------------------------------------------- the refusal
def _unprepared(monkeypatch, protected: bool):
    monkeypatch.delenv(gsx.ESCAPE, raising=False)
    monkeypatch.setattr(
        hooks_mod,
        "state",
        lambda runner: {
            "hooks_path": ".githooks" if protected else "",
            "active": "repo" if protected else "clone",
            "repo": "current" if protected else "missing",
            "clone": "missing",
            "protected": protected,
        },
    )


@pytest.mark.parametrize("subcommand", sorted(gsx.GUARDED))
def test_a_command_that_pushes_refuses_from_an_unguarded_clone(
    subcommand, monkeypatch, capsys
):
    """The one gap the design cannot close is a clone where nobody installed
    the hook: `gh stack sync` from such a clone overwrote a whole restructure,
    and the same clone with the hook was refused. So the tool that knows how
    to install it will not do the dangerous work until it has been."""
    _unprepared(monkeypatch, protected=False)
    assert gsx.main([subcommand]) == 1
    said = capsys.readouterr().err
    assert "the pre-push guard is not installed here" in said
    # the way out is in the refusal, all three of them
    assert "tdd gsx init" in said and "--clone" in said and "GSX_NO_GUARD=1" in said


@pytest.mark.parametrize("subcommand", ["stack", "checkout", "apply", "purge", "init"])
def test_a_command_that_pushes_nothing_is_not_guarded(subcommand, monkeypatch):
    """The refusal is about pushing, not about gsx. Reading the stacks from an
    unguarded clone is not dangerous, and `init` is how the guard arrives --
    guarding it would be a door locked from the inside."""
    _unprepared(monkeypatch, protected=False)
    calls = []
    monkeypatch.setitem(
        gsx.HANDLERS,
        subcommand,
        lambda *a, **k: (calls.append(subcommand), ("done", {}))[1],
    )
    assert gsx.main([subcommand]) == 0
    assert calls == [subcommand]


def test_a_guarded_clone_runs_the_command(monkeypatch):
    _unprepared(monkeypatch, protected=True)
    calls = []
    monkeypatch.setitem(
        gsx.HANDLERS, "sync", lambda *a, **k: (calls.append("sync"), ("done", {}))[1]
    )
    assert gsx.main(["sync"]) == 0
    assert calls == ["sync"]


def test_the_escape_is_an_env_var_rather_than_a_flag(monkeypatch):
    """A guard you can turn off by typing one more word on the line you were
    already typing is not a guard."""
    _unprepared(monkeypatch, protected=False)
    monkeypatch.setenv(gsx.ESCAPE, "1")
    calls = []
    monkeypatch.setitem(
        gsx.HANDLERS, "sync", lambda *a, **k: (calls.append("sync"), ("done", {}))[1]
    )
    assert gsx.main(["sync"]) == 0
    assert calls == ["sync"]
    # and there is no flag that does the same
    import argparse

    from tabsdata_dev.tool.gsx.options import configure

    parser = argparse.ArgumentParser()
    configure(parser)
    with pytest.raises(SystemExit):
        parser.parse_args(["sync", "--no-guard"])


def test_a_checkout_the_guard_cannot_be_read_in_is_not_this_checks_business(
    monkeypatch,
):
    """Not a git repository, no git at all: an error of the command that was
    asked for, reported by it, rather than a confusing word about hooks."""
    monkeypatch.delenv(gsx.ESCAPE, raising=False)

    def explode(runner):
        raise ToolError("not a git repository")

    monkeypatch.setattr(hooks_mod, "state", explode)
    calls = []
    monkeypatch.setitem(
        gsx.HANDLERS, "sync", lambda *a, **k: (calls.append("sync"), ("done", {}))[1]
    )
    assert gsx.main(["sync"]) == 0
    assert calls == ["sync"]


def test_init_reports_the_missing_extension_as_well_as_the_guard():
    assert "extension is missing" in commands._init_line(
        {"protected": True, "active": "repo", "hooks_path": ".githooks"}, False
    )
    assert "installed and active (repo)" in commands._init_line(
        {"protected": True, "active": "repo", "hooks_path": ".githooks"}, True
    )
    # a hooksPath somebody else set is neither installed nor simply missing
    assert "which gsx did not set" in commands._init_line(
        {"protected": False, "active": "elsewhere", "hooks_path": ".husky"}, True
    )


# ------------------------------------------------------- checkout --force
def test_a_local_stack_holding_the_targets_branches_another_way_is_in_the_way():
    target = _listed(7, [(5, "C1"), (6, "C2"), (3, "A3")])
    # exactly this stack, tracked as it is: nothing in the way
    same = {
        "stacks": [
            {"number": 7, "branches": [{"branch": b} for b in ("C1", "C2", "A3")]}
        ]
    }
    assert commands.stale_tracking(same, target) == []
    # ...and its merged branches are not a difference: a tracked stack keeps
    # every branch it ever had
    with_history = {
        "stacks": [
            {
                "number": 7,
                "branches": [{"branch": b} for b in ("OLD-1", "C1", "C2", "A3")],
            }
        ]
    }
    assert commands.stale_tracking(with_history, target) == []
    # the same branches under another number -- what somebody else's move
    # leaves in every clone
    stale = {
        "stacks": [{"number": 4, "branches": [{"branch": b} for b in ("A1", "A3")]}]
    }
    assert commands.stale_tracking(stale, target) == [
        {"number": 4, "branches": ["A1", "A3"]}
    ]
    # a rebuilt stack has no number at all
    rebuilt = {"stacks": [{"number": None, "branches": [{"branch": "A3"}]}]}
    assert commands.stale_tracking(rebuilt, target) == [
        {"number": None, "branches": ["A3"]}
    ]
    # a stack sharing nothing is somebody else's business
    other = {"stacks": [{"number": 9, "branches": [{"branch": "Z1"}]}]}
    assert commands.stale_tracking(other, target) == []


def test_a_restructured_stack_is_refused_and_names_the_way_through(
    tmp_path, monkeypatch, capsys
):
    """gh's own prompt for this offers to dissolve the stack on GitHub, which
    is the last thing an adopting clone means to do. gsx decides it first."""
    calls = _fake_checkout(
        monkeypatch, tmp_path, stacks=[_listed(7, [(5, "C1"), (3, "A3")])]
    )
    (tmp_path / "gh-stack").write_text(
        json.dumps({"stacks": [{"number": 4, "branches": [{"branch": "A3"}]}]})
    )
    assert gsx.main(["checkout", "#7"]) == 1
    said = capsys.readouterr().err
    assert "has been restructured since this checkout last saw it" in said
    assert "#4" in said and "--adopt" in said
    # nothing was touched: not the tracking, not gh
    assert not any(c[:3] == ["gh", "stack", "checkout"] for c in calls)
    assert not any(c[:3] == ["gh", "stack", "unstack"] for c in calls)


def test_adopt_drops_the_tracking_in_the_way_and_then_checks_the_stack_out(
    tmp_path, monkeypatch, capsys
):
    calls = _fake_checkout(
        monkeypatch, tmp_path, stacks=[_listed(7, [(5, "C1"), (3, "A3")])]
    )
    (tmp_path / "gh-stack").write_text(
        json.dumps({"stacks": [{"number": 4, "branches": [{"branch": "A3"}]}]})
    )
    monkeypatch.setattr(gh, "sha", lambda runner, ref: "sha" if "heads" in ref else "")
    monkeypatch.setattr(gh, "is_ancestor", lambda runner, a, b: True)
    assert gsx.main(["checkout", "#7", "--adopt"]) == 0
    # the stale tracking first -- gh would otherwise prompt -- and only local
    assert ["gh", "stack", "unstack", "4", "--local"] in calls
    # then the stack itself, by number
    assert ["gh", "stack", "checkout", "7"] in calls
    assert calls.index(["gh", "stack", "unstack", "4", "--local"]) < calls.index(
        ["gh", "stack", "checkout", "7"]
    )


def test_a_number_is_a_stack_or_a_pr_and_the_repository_says_which(
    tmp_path, monkeypatch
):
    """GitHub numbers stacks and PRs from one counter, so a number is one or
    the other and never both -- verified against two repositories. That is
    what lets `#N` mean either without bringing back the ambiguity a bare
    `42` is refused for: it is read off the repository, not guessed."""
    calls = _fake_checkout(
        monkeypatch, tmp_path, stacks=[_listed(7, [(5, "C1"), (3, "A3")])]
    )
    assert gsx.main(["checkout", "#7"]) == 0
    assert ["gh", "stack", "checkout", "7"] in calls

    calls = _fake_checkout(
        monkeypatch, tmp_path, stacks=[_listed(7, [(5, "C1"), (3, "A3")])]
    )
    # 3 is a PR of that stack, not a stack: the URL form, as before
    assert gsx.main(["checkout", "#3"]) == 0
    assert ["gh", "stack", "checkout", "https://github.com/o/n/pull/3"] in calls


def test_a_listing_that_cannot_be_had_checks_out_the_way_gh_alone_would(
    tmp_path, monkeypatch, capsys
):
    """A repository whose stacks API is unreachable can still be worked in;
    what is lost is the restructure check, and that is said."""
    calls = _fake_checkout(monkeypatch, tmp_path)

    def explode(runner, **kw):
        raise ToolError("no network")

    monkeypatch.setattr(gh, "stacks", explode)
    assert gsx.main(["checkout", "#42"]) == 0
    assert "without the restructure check" in capsys.readouterr().err
    assert ["gh", "stack", "checkout", "https://github.com/o/n/pull/42"] in calls


# --------------------------------------------------------------- quick ref
def test_the_card_and_the_guide_are_the_same_bytes():
    """`tdd gsx --quick-ref` and section 5 of docs/stack-workflow.md print the
    same thing, because a card that has drifted from the guide is worse than
    no card. The asset is the one copy; the guide embeds it."""
    root = pathlib.Path(__file__).resolve().parents[5]
    guide = (root / "docs" / "stack-workflow.md").read_text(encoding="utf-8")
    card = hooks_mod.quick_ref().rstrip("\n")
    assert card in guide, "docs/stack-workflow.md no longer embeds the shipped card"


def test_the_card_answers_before_a_subcommand_is_asked_for(capsys):
    """ "what are the commands" is what it answers, so it cannot require one."""
    assert gsx.main(["--quick-ref"]) == 0
    said = capsys.readouterr().out
    assert "tdd gsx move --to" in said and "tdd gsx sync" in said
    # one row per task, with the housekeeping pair on one of them
    assert "tdd gsx purge" in said and "tdd gsx prune" in said
    # `stack` spells its options out: `-as` is unreadable on a card whose job
    # is to be read. (`create -s` keeps its short form, which is the spelling
    # the tool's own synopsis uses.)
    assert "[--all] [--short] [--remote | --local]" in said
    assert "gsx stack -" not in said
    assert "gsx sync [--all] [--no-push]" in said
    # a move takes a stack OR its top branch, and the card shows both
    assert "--to '#41'" in said and "--to FOO-16" in said
    # and the label/reviewer grammar is the real one
    assert "--label:<scope>[:<mode>] LIST" in said
    assert "--reviewer:<scope>[:<mode>] LIST" in said
    assert "new (default) | top | all | mine" in said
    assert "replace (default) | add" in said


def test_the_card_is_the_ok_message_so_it_pipes(capsys):
    assert gsx.main(["--quick-ref", "--format", "json"]) == 0
    last = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert last["event"] == "ok" and last["quick_ref"] is True
    assert "tdd gsx init" in last["message"]


def test_the_cascade_replays_a_branchs_OWN_commits_after_its_parent_was_rewritten(
    monkeypatch,
):
    """Measured in tabsdata-os. Restacking OS-3482 after OS-3481 had been
    rewritten in the same run took `git merge-base OS-3481 OS-3482` back to the
    tip of TD-3329, three branches below -- so the rebase replayed OS-3481's
    own commits onto the new OS-3481, which already had them, and conflicted
    add/add on a file neither side had really touched twice. The upstream has
    to be the parent's tip from BEFORE the run."""
    shas = {f"refs/heads/{b}": b for b in ("TD-3329", "OS-3481", "OS-3482")}
    # OS-3481 is on its parent; OS-3482 is not on the rewritten OS-3481. The
    # snapshot's OS-3481 is still in OS-3482's history, which is what makes it
    # the right range.
    runner, calls = _fake_git(
        monkeypatch,
        shas,
        ancestors={("TD-3329", "OS-3481"), ("OS-3481-old", "OS-3482")},
    )
    before = {"TD-3329": "TD-3329-old", "OS-3481": "OS-3481-old"}
    assert sync_mod.restack(
        runner, ["OS-3481", "OS-3482"], "TD-3329", _Say(), before
    ) == ["OS-3482"]
    rebases = [c for c in calls if c[:2] == ["git", "rebase"]]
    # the parent's PRE-RUN tip, never the merge-base
    assert rebases == [["git", "rebase", "--onto", "OS-3481", "OS-3481-old", "OS-3482"]]
    assert not any(c[:2] == ["git", "merge-base"] for c in calls)


def test_the_cascade_falls_back_to_the_merge_base_when_the_snapshot_is_no_use(
    monkeypatch,
):
    """A branch built somewhere else entirely: the recorded tip is not in its
    history, so it would name the wrong range."""
    shas = {f"refs/heads/{b}": b for b in ("B1", "B2")}
    runner, calls = _fake_git(monkeypatch, shas, ancestors=set())
    sync_mod.restack(runner, ["B1", "B2"], "main", _Say(), {"B1": "elsewhere"})
    assert any(c[:2] == ["git", "merge-base"] for c in calls)
    assert ["git", "rebase", "--onto", "B1", "base-sha", "B2"] in calls


def test_tips_are_taken_before_anything_is_touched(monkeypatch):
    shas = {"refs/heads/B1": "s1", "refs/heads/B2": "s2", "refs/heads/gone": ""}
    runner, _ = _fake_git(monkeypatch, shas, ancestors=set())
    assert sync_mod.tips(runner, ["B1", "B2", "gone"]) == {"B1": "s1", "B2": "s2"}


def test_clone_mode_refuses_where_core_hookspath_would_hide_it(tmp_path):
    """`core.hooksPath` replaces .git/hooks rather than adding to it, so
    installing there while it is set writes a file git will never read. Seen in
    a real checkout whose .githooks had been removed but whose config still
    named it: `--clone` said "installed", `--check` said "NOT active", and only
    the second was right."""
    root = tmp_path / "clone"
    (root / ".git" / "hooks").mkdir(parents=True)

    class FakeRunner:
        out = None
        dry_run = False

        def run(self, argv, **kwargs):
            if argv[:3] == ["git", "rev-parse", "--show-toplevel"]:
                return str(root)
            if argv[:2] == ["git", "config"] and argv[2] == "core.hooksPath":
                return ".githooks"
            if argv[:3] == ["git", "rev-parse", "--git-dir"]:
                return str(root / ".git")
            return ""

    with pytest.raises(ToolError, match="core.hooksPath"):
        hooks_mod.install(FakeRunner(), hooks_mod.CLONE, force=False)
    assert not (root / ".git" / "hooks" / "pre-push").exists()


# ------------------------------------------------- standing on the trunk
def test_standing_on_the_trunk_brackets_the_trunk():
    """The brackets are what answer "where am I", and on the trunk they
    answered nothing: no stack holds you, so no cell was marked and the legend
    explained a symbol the page did not use."""
    rows = commands.stack_rows(_state(names=("a1", "a2")), "main")
    assert rows[0]["trunk_current"] is True
    # ...and the STACK is still not current: `submit` acts on neither
    assert rows[0]["current"] is False
    line = commands.stack_lines(rows)
    assert line == " #34  [main]<- ?a1 <- ?a2"
    # the tag is unbracketed, the trunk is not
    assert "[#34]" not in line and "[main]" in line


def test_the_trunk_keeps_the_column_whether_it_is_bracketed_or_not():
    """The same rule every other cell follows: the brackets cost the column
    nothing, so `main` sits at one offset however the rows differ."""
    state = _state(number=34, names=("a1",))
    state["stacks"].append(
        {"number": 40, "trunk": {"branch": "other"}, "branches": [{"branch": "b1"}]}
    )
    lines = commands.stack_lines(commands.stack_rows(state, "main")).splitlines()
    # row 1's trunk IS where we stand, row 2's is not
    assert lines[0].index("main") == lines[1].index("other")
    for line in lines:
        assert line == line.rstrip(), line


def test_a_branch_of_a_stack_still_brackets_the_branch_and_the_stack():
    rows = commands.stack_rows(_state(names=("a1", "a2")), "a2")
    assert rows[0]["current"] is True and rows[0]["trunk_current"] is False
    assert commands.stack_lines(rows) == "[#34]  main <- ?a1 <-?[a2]"


def test_the_summary_brackets_the_trunk_on_the_stacks_own_line():
    rows = commands.stack_rows(_with_prs(_state(names=("a1",)), [(21,)]), "main")
    first = commands.stack_summary(rows, {21: "the loader"}).splitlines()[0]
    assert first == " #34  [main]"
    # and not when you are somewhere else
    rows = commands.stack_rows(_with_prs(_state(names=("a1",)), [(21,)]), "a1")
    assert commands.stack_summary(rows, {21: "the loader"}).splitlines()[0] == (
        "[#34]  main"
    )


def test_where_you_are_is_said_when_no_cell_can_say_it(tmp_path, monkeypatch, capsys):
    """A branch in no stack and not a trunk either: nothing is bracketed, so
    the one thing the reader wants is said instead of drawn."""
    _fake_purge(monkeypatch, tmp_path, ["main"], {})
    (tmp_path / "gh-stack").write_text(json.dumps(_state(names=("a1", "a2"))))
    monkeypatch.setattr(gh, "git_dir", lambda runner: tmp_path)
    monkeypatch.setattr(gh, "current_branch", lambda runner: "scratch")
    monkeypatch.setattr(
        gh,
        "branch_sync",
        lambda runner, names, remote, *_: dict.fromkeys(names, gh.IN_SYNC),
    )
    monkeypatch.setattr(gh, "stacks", lambda runner, **kw: [])
    assert gsx.main(["stack", "--all", "--short", "--no-fetch"]) == 0
    assert (
        "on 'scratch', which is in none of the stacks below" in capsys.readouterr().err
    )

    # ...and not said when a bracket already says it
    monkeypatch.setattr(gh, "current_branch", lambda runner: "main")
    assert gsx.main(["stack", "--all", "--short", "--no-fetch"]) == 0
    assert "is in none of the stacks below" not in capsys.readouterr().err


def test_a_commit_whose_patch_a_resolution_changed_is_matched_by_subject(monkeypatch):
    """Measured in tabsdata-os: OS-3512 was moved onto a stack and its one
    commit resolved against newer work, so the two copies of the same commit
    came out with different patch-ids (d11fc7bb9716 against 48d95e6c9bd3). By
    patch alone the remote's copy reads as a commit we are missing, and
    reconciling would have re-applied the superseded version on top of the
    resolved one."""
    calls = []

    class FakeRunner:
        out = None
        dry_run = False

        def run(self, argv, **kwargs):
            calls.append(argv)
            if argv[:2] == ["git", "rev-list"]:
                return "remote-sha"
            if argv[:2] == ["git", "log"] and "--format=%s" in argv and "-1" in argv:
                return "[OS-3512] Add _api.validate_call"
            if argv[:2] == ["git", "log"] and "--format=%s" in argv:
                # the branch's own commits here, after the resolution
                return "[OS-3512] Add _api.validate_call\n"
            return ""

    runner = FakeRunner()
    # with the parent known, the subject matches and nothing is taken
    assert (
        sync_mod.own_commits(runner, "OS-3512", "origin", "origin/main", "OS-3510")
        == []
    )
    # without it, patch-matching alone still reports the superseded commit
    assert sync_mod.own_commits(runner, "OS-3512", "origin", "origin/main") == [
        "remote-sha"
    ]


def test_a_genuinely_new_commit_is_still_taken(monkeypatch):
    class FakeRunner:
        out = None
        dry_run = False

        def run(self, argv, **kwargs):
            if argv[:2] == ["git", "rev-list"]:
                return "theirs"
            if argv[:2] == ["git", "log"] and "-1" in argv:
                return "[A3] a teammate's new commit"
            if argv[:2] == ["git", "log"]:
                return "[A3] something else entirely"
            return ""

    assert sync_mod.own_commits(FakeRunner(), "A3", "origin", "origin/A2", "C2") == [
        "theirs"
    ]
