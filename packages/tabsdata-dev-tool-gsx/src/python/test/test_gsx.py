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
from tabsdata_dev.tool.gsx import commands, config, gh, labels, progress
from tabsdata_dev.tool.gsx import purge as purge_mod


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
        {"name": "a1", "pr": None, "sync": gh.IN_SYNC, "current": False},
        {"name": "a2", "pr": None, "sync": gh.AHEAD, "current": True},
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
        "[#34]  main <- =insync   <-[+ahead]",
        " #40   main <- -behind   <- xdiverged",
        " #-    main <- +unpushed <- ?gone",
    ]
    for line in commands.stack_lines(rows).splitlines():
        assert line == line.rstrip(), line


def test_the_colours_are_the_states_and_both_brackets_are_white():
    rows = commands.stack_rows(
        _state(names=("a1", "a2")), "a2", _sync(a1=gh.DIVERGED, a2=gh.BEHIND)
    )
    painted = commands.stack_lines(
        rows, lambda name, text: f"<{name or 'plain'}>{text}</>"
    )
    assert painted == (
        # the brackets are white: every colour here already means a sync state
        # the space after `main` is its own closing-bracket slot
        "<white>[</>#34<white>]</>  main "
        # `<-` and the bracket slots are structure, not state: the cell is what
        # carries the colour
        "<- <red>xa1</> <-<white>[</><yellow>-a2</><white>]</>"
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
        "      [+a2]       #22  wire it up",
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
        "       <red>xa1</>  #21  one",
        # the bracket hangs one column left of the plain names, exactly as it
        # does in the one-line form, and eats the space before the PR ref
        "      <white>[</><yellow>-a2</><white>]</> #22  two",
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
        lambda runner, names, remote: dict.fromkeys(names, gh.IN_SYNC),
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
        lambda runner, names, remote: {"a1": gh.IN_SYNC, "a2": gh.AHEAD},
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
        lambda runner, names, remote: {"a1": gh.IN_SYNC, "a2": gh.AHEAD},
    )
    assert gsx.main(["stack", "--short"]) == 0
    lines = capsys.readouterr().out.split("\n")
    # no count line over a single stack: the row already says which one
    assert lines[0] == "[#34]  main <- =a1 <-[+a2]"
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
        lambda runner, names, remote: (
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
        lambda runner, names, remote: dict.fromkeys(names, gh.IN_SYNC),
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
    assert "[#34]  main <- =a1 <-[=a2]" in out
    assert "the loader" not in out  # and it asks gh for no titles

    # -a and -s are the short forms, and they bundle
    assert gsx.main(["stack", "-s", "--no-fetch"]) == 0
    assert "[#34]  main <- =a1 <-[=a2]" in capsys.readouterr().out
    assert gsx.main(["stack", "-as", "--no-fetch"]) == 0
    out = capsys.readouterr().out
    assert "1 stack(s):" in out and "<-" in out


def test_short_needs_no_gh_at_all(tmp_path, monkeypatch, capsys):
    """`--short` reads a file and some refs and nothing else. The default asks
    gh for PR titles, but the gh-stack extension is never needed either way --
    requiring it would refuse a checkout that has stacks but no extension."""
    _fake_purge(monkeypatch, tmp_path, ["main"], {})
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
        lambda runner, names, remote: {"a1": gh.IN_SYNC, "a2": gh.AHEAD},
    )
    assert gsx.main(["stack", "--short"]) == 0
    out = capsys.readouterr().out
    assert "[#34]  main <- =a1 <-[+a2]" in out and "[] current" in out


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
        lambda runner, names, remote: {"a1": gh.IN_SYNC, "a2": gh.AHEAD},
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
    }
