#
# Copyright 2026 Tabsdata Inc.
#

"""What a smoke run reads about a project's workers (`tdd _smoke
finished-workers`, `tdd _smoke worker-pods-gone`, `tdd _smoke archived-logs`)."""

import io

import pytest
from tabsdata_dev.tool.smoke import engine, workers


def test_only_the_workers_that_finished_are_picked(resource_folder):
    listing = (resource_folder / "workers.json").read_text()
    assert workers.finished(listing) == [
        "wkr20261030-11",
        "wkr20261030-12",
        "wkr20261030-14",
    ]


def test_an_empty_listing_has_no_worker():
    assert workers.finished("") == []
    assert workers.finished("[]") == []
    assert workers.finished('{"data": []}') == []


def test_a_pod_runner_log_names_its_containers_in_order(resource_folder):
    text = (resource_folder / "archived.txt").read_text()
    assert workers.containers(text, workers.POD_RUNNER) == [
        "0000-inspect-function",
        "0090-function",
        "1000-end-execution",
    ]
    assert workers.judge(text, workers.POD_RUNNER).problems == []


@pytest.mark.parametrize(
    "fixture, expected",
    [
        # the pod still existed: Kubernetes served it, not the archive
        ("live.txt", "no POD STARTED line"),
        # the last container never reached the archive
        ("cut.txt", f"no {workers.LAST_CONTAINER}* container"),
        ("refused.txt", "the reader answered: no logs kept for worker"),
    ],
)
def test_a_log_the_archive_did_not_keep_whole_says_why(
    resource_folder, fixture, expected
):
    found = workers.judge(
        (resource_folder / fixture).read_text(), workers.POD_RUNNER
    ).problems
    assert any(expected in problem for problem in found), found


RULE = "=" * 50


def _log(*held):
    return "".join(
        f"{RULE}\ncontainer: {name}\n{RULE}\n" + "".join(f"{line}\n" for line in lines)
        for name, lines in held
    )


VENV = ("0010-venvloader", ["environment ready"])
BEGIN = ("0040-begin-execution", ["started"])
FUNCTION = ("0090-function", ["one", "two"])
END = ("1000-end-execution", ["finished"])
LIVE = _log(VENV, BEGIN, FUNCTION, END)


def test_a_cloudwatch_log_names_its_containers_by_the_live_log_s_headers(
    resource_folder,
):
    text = (resource_folder / "cloudwatch.txt").read_text()
    live = (resource_folder / "live-cloud.txt").read_text()
    assert workers.containers(text, workers.CLOUDWATCH) == [
        "0010-venvloader",
        "0040-begin-execution",
        "0090-function",
        "1000-end-execution",
    ]
    assert workers.judge(text, workers.CLOUDWATCH, live).problems == []


@pytest.mark.parametrize(
    "fixture, expected",
    [
        ("cloudwatch-cut.txt", "1 live line(s) not in the archive"),
        ("cloudwatch-refused.txt", "the reader answered: no logs found for worker"),
        # another archive's shape: the instance did not read from CloudWatch
        ("archived.txt", "a POD STARTED line"),
    ],
)
def test_a_log_cloudwatch_did_not_keep_whole_says_why(
    resource_folder, fixture, expected
):
    live = (resource_folder / "live-cloud.txt").read_text()
    found = workers.judge(
        (resource_folder / fixture).read_text(), workers.CLOUDWATCH, live
    ).problems
    assert any(expected in problem for problem in found), found


def test_a_cloud_archive_is_judged_against_a_live_log_only():
    with pytest.raises(ValueError, match="judged against the live log"):
        workers.judge(LIVE, workers.CLOUDWATCH)


def test_a_cloudwatch_log_is_told_from_the_live_one_only_by_the_pod_being_gone(
    resource_folder,
):
    """Both write `container: <name>` headers: the shape cannot tell them apart,
    which is why the script waits for the pods to go before it reads."""
    live = (resource_folder / "live-cloud.txt").read_text()
    assert workers.judge(live, workers.CLOUDWATCH, live).problems == []


@pytest.mark.parametrize("archive", workers.HEADED)
def test_every_cloud_archive_may_start_at_the_execution(resource_folder, archive):
    """One rule for every reader: Cloud Logging's and Log Analytics' read from
    30s before `started_on`, which `0040-begin-execution` reports, so the setup
    containers may be gone -- and the JSON line comes back respelled."""
    live = (resource_folder / "live-cloud.txt").read_text()
    for fixture in ("cloud-logging.txt", "log-analytics.txt", "cloudwatch.txt"):
        text = (resource_folder / fixture).read_text()
        assert workers.judge(text, archive, live).problems == [], fixture
    assert workers.containers(
        (resource_folder / "cloud-logging.txt").read_text(), archive
    )[0] == ("0040-begin-execution")


@pytest.mark.parametrize(
    "fixture, archive, expected",
    [
        (
            "cloud-logging-refused.txt",
            workers.CLOUD_LOGGING,
            "no logs found for worker",
        ),
        (
            "log-analytics-no-metadata.txt",
            workers.LOG_ANALYTICS,
            "has no kubernetes metadata",
        ),
    ],
)
def test_a_refusal_is_named(resource_folder, fixture, archive, expected):
    live = (resource_folder / "live-cloud.txt").read_text()
    found = workers.judge(
        (resource_folder / fixture).read_text(), archive, live
    ).problems
    assert any(expected in problem for problem in found), found


@pytest.mark.parametrize(
    "archived",
    [
        LIVE,
        _log(BEGIN, FUNCTION, END),
        # the window may cut into a setup container
        _log(("0010-venvloader", []), BEGIN, FUNCTION, END),
        # a container that printed nothing has a live header and no archived one
        _log(VENV, ("0020-inspect-function", []), BEGIN, FUNCTION, END),
    ],
)
def test_the_archive_matches_the_live_log_from_where_it_starts(archived):
    assert workers.mismatches(LIVE, archived).problems == []


@pytest.mark.parametrize(
    "archived, expected, lasting",
    [
        # the window ends at the execution's first line: none of it may go
        (_log(FUNCTION, END), "1 live line(s) not in the archive", False),
        (_log(VENV, BEGIN, FUNCTION), "1 live line(s) not in the archive", False),
        (_log(VENV, BEGIN, ("0090-function", ["one"]), END), "1 live line(s)", False),
        (
            _log(VENV, BEGIN, ("0090-function", ["one", "one", "two"]), END),
            "1 line(s) not in the live log",
            True,
        ),
        # unstamped lines keep their order
        (
            _log(VENV, BEGIN, ("0090-function", ["two", "one"]), END),
            "1 line pair(s) in another order",
            True,
        ),
        (
            _log(
                VENV, BEGIN, ("0090-function", ["one"]), ("0090-function", ["two"]), END
            ),
            "container 0090-function appears 2 times",
            True,
        ),
        ("", "the archive holds no line yet", False),
    ],
)
def test_what_the_archive_lost_or_added_is_named(archived, expected, lasting):
    """Lines the archive lacks may still arrive; anything else is there to stay."""
    verdict = workers.mismatches(LIVE, archived)
    assert any(expected in problem for problem in verdict.problems), verdict.problems
    assert verdict.lasting is lasting


def _stamped(*held):
    return _log(
        *((name, [f"{at} {text}" for at, text in lines]) for name, lines in held)
    )


def test_lines_written_together_may_come_back_in_either_order(resource_folder):
    """Log Analytics orders by time, then by a random row id: the WARNING a
    source plugin wrote to stderr came back among the stdout lines of the same
    millisecond, three lines before where Kubernetes had it."""
    live = (resource_folder / "reorder-live.txt").read_text()
    archived = (resource_folder / "reorder-log-analytics.txt").read_text()
    assert live != archived
    assert workers.mismatches(live, archived) == workers.Verdict([])


@pytest.mark.parametrize(
    "first, second, swaps",
    [
        ("2026-11-03T20:26:38.673Z", "2026-11-03T20:26:38.683Z", True),
        ("2026-11-03T20:26:38.673Z", "2026-11-03T20:26:38.684Z", False),
        ("2026-11-03T20:26:38.673+00:00", "2026-11-03T20:26:38.675Z", True),
    ],
)
def test_only_lines_stamped_within_the_tolerance_may_swap(first, second, swaps):
    live = _stamped(("0090-function", [(first, "a"), (second, "b")]))
    archived = _stamped(("0090-function", [(second, "b"), (first, "a")]))
    verdict = workers.mismatches(live, archived)
    assert (verdict.problems == []) is swaps, verdict.problems
    assert verdict.lasting is not swaps


def test_lines_of_two_containers_never_swap():
    at = "2026-11-03T20:26:38.673Z"
    live = _stamped(("0090-function", [(at, "a")]), ("1000-end-execution", [(at, "b")]))
    archived = _stamped(
        ("1000-end-execution", [(at, "b")]), ("0090-function", [(at, "a")])
    )
    verdict = workers.mismatches(live, archived)
    assert verdict.lasting, verdict.problems
    assert any("in another order" in problem for problem in verdict.problems)


@pytest.mark.parametrize(
    "refusal, lasting",
    [
        ("cloud-logging-refused.txt", False),
        ("log-analytics-no-metadata.txt", True),
    ],
)
def test_a_refusal_is_lasting_unless_waiting_can_clear_it(
    resource_folder, refusal, lasting
):
    live = (resource_folder / "live-cloud.txt").read_text()
    text = (resource_folder / refusal).read_text()
    assert workers.judge(text, workers.LOG_ANALYTICS, live).lasting is lasting
    pending = "no access to the Log Analytics workspace 'x' (403)"
    assert not workers.judge(pending, workers.LOG_ANALYTICS, live).lasting
    gone = "no pod found for worker 'wkr20261030-11': its logs are no longer retained"
    assert workers.judge(gone, workers.CLOUDWATCH, live).lasting


def test_the_pod_runner_check_keeps_its_wait(resource_folder):
    cut = (resource_folder / "cut.txt").read_text()
    verdict = workers.judge(cut, workers.POD_RUNNER)
    assert verdict.problems and not verdict.lasting


def test_a_mismatch_shows_a_bounded_diff():
    many = ("0090-function", [f"line {n}" for n in range(100)])
    found = workers.mismatches(_log(BEGIN, many, END), _log(BEGIN, END)).problems
    shown = [line for line in found if line.startswith("  ")]
    assert "  --- live" in shown and "  +++ archived" in shown
    assert len(shown) == workers.DIFF_LINES + 1
    assert shown[-1].startswith("  ... ")


def test_a_header_may_close_a_line_without_its_newline():
    """A container's last line may lack a newline: the next header's rule
    then follows it on the same line."""
    glued = f"{RULE}\ncontainer: 0090-function\n{RULE}\none\ntwo{RULE}\ncontainer: 1000-end-execution\n{RULE}\nfinished\n"
    assert workers.sections(glued) == [
        ("0090-function", ["one", "two"]),
        ("1000-end-execution", ["finished"]),
    ]


def test_lines_are_compared_as_every_reader_agrees_on_them():
    live = _log(
        ("0090-function", ['{"b": 1, "a": [1, 2]}', "plain\r", "", "{not json"])
    )
    archived = _log(("0090-function", ['{"a":[1,2],"b":1}', "plain", "{not json"]))
    assert workers.mismatches(live, archived).problems == []


def test_a_live_log_is_a_reference_once_the_pod_ran_to_its_end(resource_folder):
    assert workers.live_problems((resource_folder / "live-cloud.txt").read_text()) == []
    found = workers.live_problems(_log(VENV, BEGIN, FUNCTION))
    assert any("had not finished" in problem for problem in found), found
    found = workers.live_problems(
        (resource_folder / "cloudwatch-refused.txt").read_text()
    )
    assert any("no logs found for worker" in problem for problem in found), found


@pytest.mark.parametrize(
    "last", ["1000-end-execution", "1000-cron-publisher", "1000-stream-source-plugin"]
)
def test_a_live_log_ran_to_its_end_at_the_container_numbered_1000(last):
    """Each kind of worker pod ends in its own container, all numbered 1000."""
    assert workers.live_problems(_log(VENV, FUNCTION, (last, ["finished"]))) == []


def test_the_live_workers_are_those_whose_pod_ended(resource_folder):
    listing = (resource_folder / "pods-phases.json").read_text()
    wanted = [
        "wkr20261030-11",
        "wkr20261030-12",
        "wkr20261030-0000015",
        "wkr20261030-14",
    ]
    assert workers.terminal(listing, wanted) == [
        "wkr20261030-11",
        "wkr20261030-0000015",
    ]
    assert workers.terminal("", wanted) == []


def test_the_pods_left_are_those_labelled_with_a_listed_worker(resource_folder):
    listing = (resource_folder / "pods.json").read_text()
    assert workers.pods_left(listing, ["wkr20261030-11", "wkr20261030-12"]) == [
        "pub-wkr20261030-11-5rt89"
    ]
    assert workers.pods_left(listing, ["wkr20261030-12"]) == []
    assert workers.pods_left("", ["wkr20261030-11"]) == []


def test_a_padded_worker_id_finds_the_pod_its_unpadded_label_names(resource_folder):
    """The pods carry the id without the counter's padding."""
    listing = (resource_folder / "pods.json").read_text()
    assert workers.pods_left(listing, ["wkr20261030-0000015"]) == [
        "pub-wkr20261030-15-x2b7q"
    ]


def _answer(monkeypatch, capsys, argv, text):
    monkeypatch.setattr("sys.argv", ["_smoke", *argv])
    monkeypatch.setattr("sys.stdin", io.StringIO(text))
    capsys.readouterr()
    code = engine.main()
    return code, capsys.readouterr().out.strip()


def test_the_helpers_answer_and_the_script_judges(resource_folder, monkeypatch, capsys):
    """The log check is retried until the pod is gone and the archive holds the
    log, so a no is an answer, exit 0 -- an error would leave a failure log
    behind on every attempt."""
    listing = (resource_folder / "workers.json").read_text()
    picked = ["finished-workers", "--max", "2"]
    assert _answer(monkeypatch, capsys, picked, listing) == (
        0,
        "wkr20261030-11\nwkr20261030-12",
    )

    kept = ["archived-logs", "--worker", "wkr20261030-11", "--archive", "pod-runner"]
    archived = (resource_folder / "archived.txt").read_text()
    live = (resource_folder / "live.txt").read_text()
    assert _answer(monkeypatch, capsys, kept, archived) == (0, engine.READY)
    assert _answer(monkeypatch, capsys, kept, live) == (0, engine.NOT_READY)


def test_the_pods_check_answers_too(resource_folder, monkeypatch, capsys):
    listing = (resource_folder / "pods.json").read_text()
    left = ["worker-pods-gone", "--workers", "wkr20261030-11 wkr20261030-12"]
    gone = ["worker-pods-gone", "--workers", "wkr20261030-12 wkr20261030-14"]
    assert _answer(monkeypatch, capsys, left, listing) == (0, engine.NOT_READY)
    assert _answer(monkeypatch, capsys, gone, listing) == (0, engine.READY)

    live = str(resource_folder / "live-cloud.txt")
    kept = ["archived-logs", "--worker", "wkr20261030-11", "--archive", "cloudwatch"]
    archived = (resource_folder / "cloudwatch.txt").read_text()
    refused = (resource_folder / "cloudwatch-refused.txt").read_text()
    cut = (resource_folder / "cloudwatch-cut.txt").read_text()
    compared = [*kept, "--live", live]
    assert _answer(monkeypatch, capsys, compared, archived) == (0, engine.READY)
    assert _answer(monkeypatch, capsys, compared, refused) == (0, engine.NOT_READY)
    assert _answer(monkeypatch, capsys, compared, cut) == (0, engine.NOT_READY)
    # a line the live log lacks will not go away: the script stops retrying
    extra = archived.replace("done\n", "done\nnot in the live log\n", 1)
    assert _answer(monkeypatch, capsys, compared, extra) == (0, engine.FAILED)
    # no live log to judge a cloud archive against is the caller's error
    assert _answer(monkeypatch, capsys, kept, archived)[0] == 1


def test_the_live_checks_answer_too(resource_folder, monkeypatch, capsys):
    listing = (resource_folder / "pods-phases.json").read_text()
    ended = ["live-workers", "--workers", "wkr20261030-11 wkr20261030-12"]
    assert _answer(monkeypatch, capsys, ended, listing) == (0, "wkr20261030-11")

    whole = ["live-log", "--worker", "wkr20261030-11"]
    live = (resource_folder / "live-cloud.txt").read_text()
    cut = (resource_folder / "cloudwatch-cut.txt").read_text()
    assert _answer(monkeypatch, capsys, whole, live) == (0, engine.READY)
    assert _answer(monkeypatch, capsys, whole, cut) == (0, engine.NOT_READY)
