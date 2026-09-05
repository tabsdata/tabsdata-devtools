#
# Copyright 2026 Tabsdata Inc.
#

import json

import pytest
from tabsdata_dev.common.core.errors import ToolError
from tabsdata_dev.tool import gsx
from tabsdata_dev.tool.gsx import args as args_mod
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
def test_the_config_round_trips_through_its_own_writer(tmp_path, monkeypatch):
    monkeypatch.setenv("TDD_DIR", str(tmp_path))
    assert config.path() == tmp_path / "gsx.toml"
    assert config.read() == {"version": config.VERSION, "repos": {}}  # no file yet
    written = {
        "version": config.VERSION,
        "repos": {
            "o/n": {
                "fetched": "2026-09-05T00:00:00-03:00",
                "labels": ["bug", "run-ci"],
                "reviewers": ["tucu0"],
                "defaults": {"labels": ["skip-ci"], "reviewers": []},
            }
        },
    }
    config.write(written)
    assert config.read() == written
    text = config.path().read_text()
    assert text.startswith("#\n# Copyright")  # the house header, and the comments
    assert 'default_labels = ["skip-ci"]' in text


def test_an_unreadable_config_says_so_instead_of_crashing(tmp_path, monkeypatch):
    monkeypatch.setenv("TDD_DIR", str(tmp_path))
    config.path().write_text("this is not toml =\n")
    with pytest.raises(ToolError, match="not readable"):
        config.read()


# ------------------------------------------------------------------ engine
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
    changed, failures = labels.apply(FakeRunner(), None, ops, [], _Out())
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
    changed, failures = labels.apply(FakeRunner(), None, ops, [], _Out())
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
    changed, failures = labels.apply(FailingRunner(), None, ops, [], _Out())
    assert changed == 1 and failures == ["PR #6: gh said no"]


def test_a_value_missing_from_the_config_stops_everything(tmp_path, monkeypatch):
    monkeypatch.setenv("TDD_DIR", str(tmp_path))

    class Repo:
        def entry(self):
            return ({"labels": ["bug"], "reviewers": []}, True)  # just fetched

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
