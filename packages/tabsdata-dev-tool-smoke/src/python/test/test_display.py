#
# Copyright 2026 Tabsdata Inc.
#

"""The masking of a smoke run's command lines (`tdd _smoke display`)."""

import pytest
from tabsdata_dev.tool.smoke import display, engine


@pytest.mark.parametrize(
    "words, shown",
    [
        (
            ["tdk", "login", "--password", "tabsdata", "--user", "admin"],
            "tdk login --password *** --user admin",
        ),
        (["tdk", "login", "-p", "s3cr3t"], "tdk login -p ***"),
        (
            ["x", "--token=a", "--secret=b", "--pat=c"],
            "x --token=*** --secret=*** --pat=***",
        ),
        (
            ["x", "--anthropic-key", "K", "--openai-key=K", "--db-password", "p"],
            "x --anthropic-key *** --openai-key=*** --db-password ***",
        ),
        (
            ["https://u:p@host/path", "postgres://u:p@h:5432/db", "https://host/x"],
            "https://***@host/path postgres://***@h:5432/db https://host/x",
        ),
        (
            ["AWS_SECRET_ACCESS_KEY=a", "DB_PASSWORD=b", "GH_PAT=c", "GH_PAT_2=d"],
            "AWS_SECRET_ACCESS_KEY=*** DB_PASSWORD=*** GH_PAT=*** GH_PAT_2=***",
        ),
        # case-sensitive, and only a NAME=value: what the engine always matched
        (["PLAIN=ok", "lower_key=k", "=x", "9KEY=v"], "PLAIN=ok lower_key=k =x 9KEY=v"),
        # a URL's user:password is masked before the NAME=value rule is asked
        (["URL=https://u:p@h"], "URL=https://***@h"),
        # nothing after the option: nothing to mask
        (["x", "-p"], "x -p"),
    ],
)
def test_every_credential_is_masked_and_nothing_else(words, shown):
    assert display.display(words) == shown


def test_the_words_after_a_double_dash_are_the_command_s_own(monkeypatch, capsys):
    """The masked command may carry `--format json` or `--verbose` of its own:
    they are words to show, not options of `_smoke` -- answered as JSON, the
    stage line would be an event."""
    words = [
        "tdd",
        "xp",
        "list-suites",
        "--format",
        "json",
        "--verbose",
        "--token",
        "t",
    ]
    monkeypatch.setattr("sys.argv", ["_smoke", "display", "--", *words])
    assert engine.main() == 0
    assert (
        capsys.readouterr().out
        == "tdd xp list-suites --format json --verbose --token ***\n"
    )
