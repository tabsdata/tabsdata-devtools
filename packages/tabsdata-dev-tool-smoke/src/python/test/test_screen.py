#
# Copyright 2026 Tabsdata Inc.
#

"""What a smoke run draws beyond its stage lines (`tdd _smoke window`,
`pointers`, `paint-help`)."""

import os
import threading

from tabsdata_dev.tool.smoke import screen

BOLD, CYAN, RED, OFF = screen.BOLD, screen.CYAN, screen.RED, screen.OFF


def test_a_help_page_is_painted_and_nothing_moves(resource_folder):
    """A heading bold, a term cyan, a required option red; and the closing
    prose block -- "The drivers added ...", whose indented line lists packages
    -- is a paragraph, not a term list: painting its first package cyan said it
    was an option."""
    page = (resource_folder / "page.txt").read_text()
    painted = screen.paint_help(page, {"--name", "--td-version"}, tty=True).split("\n")
    assert painted[0] == f"{BOLD}usage:{OFF} smoke-x.sh --name NAME [--force]"
    assert painted[4] == f"{BOLD}options:{OFF}"
    assert painted[5] == f"  {RED}--name NAME{OFF}         REQUIRED: the run's name"
    # a long term sits on its own line, its description on the next
    assert painted[6] == f"  {RED}--td-version VERSION{OFF}"
    assert painted[8] == f"  {CYAN}--force, -f{OFF}         replace what exists"
    assert painted[11] == "The drivers added to the instance's fn and ag venvs:"
    assert painted[12] == "  pymysql==1.2.3  psycopg2-binary==2.9.12"
    # stripped of its colour, the page is the page
    assert screen.ANSI.sub("", "\n".join(painted)) == page


def test_a_page_is_left_plain_off_a_terminal_and_under_no_color(
    resource_folder, monkeypatch
):
    page = (resource_folder / "page.txt").read_text()
    assert screen.paint_help(page, {"--name"}, tty=False) == page
    monkeypatch.setenv("NO_COLOR", "1")
    assert screen.paint_help(page, {"--name"}, tty=True) == page


def test_the_pointers_are_the_last_distinct_log_files_a_command_named():
    lines = [
        "\x1b[31mdetails: /tmp/tdd-xp-1.log\x1b[0m",
        "  errors:   /tmp/e1.log and more",
        "lane log: C:\\Users\\u\\AppData\\Local\\Temp\\lane.log",
        "it failed, full output in D:/logs/out.txt (see)",
        "details: /tmp/tdd-xp-1.log",
        "log: relative/is/not/a/path",
    ]
    text = "\n".join(lines)
    assert screen.pointers(text) == [
        "details /tmp/tdd-xp-1.log",
        "errors /tmp/e1.log",
        "lane log C:\\Users\\u\\AppData\\Local\\Temp\\lane.log",
        "output D:/logs/out.txt",
    ]
    many = "\n".join(f"log: /tmp/l{i}" for i in range(9))
    assert screen.pointers(many) == [f"log /tmp/l{i}" for i in range(3, 9)]


def test_the_window_shows_only_what_the_running_command_wrote(tmp_path):
    log = tmp_path / "log"
    log.write_text("==> [1] a stage\n    ok (1s)\n")
    offset = log.stat().st_size
    with log.open("a") as fh:
        fh.write("one\r\n\x1b[2Ktwo\nthree\n")
    assert screen.window_lines(screen.written_since(log, offset), 2) == ["two", "three"]
    assert screen.window_lines(screen.written_since(log, 0), 0) == []


def test_the_window_ends_on_its_stop_file_and_erases_itself(tmp_path, monkeypatch):
    monkeypatch.setattr(screen, "WINDOW_PERIOD", 0.05)
    monkeypatch.setattr(screen, "WINDOW_POLL", 0.01)
    log = tmp_path / "log"
    log.write_text("a\nb\n")
    stop = tmp_path / "stop"
    drawn = []
    threading.Timer(0.3, stop.touch).start()
    screen.window(log, 0, 4, stop, os.getpid(), drawn.append, ("<", ">"))
    # always the window's full height: what there is, then blank rows
    assert drawn[0] == [
        f"{screen.WINDOW_INDENT}<a>",
        f"{screen.WINDOW_INDENT}<b>",
        "",
        "",
    ]
    assert drawn[-1] == []
    assert not stop.exists()


def test_the_window_ends_with_its_parent(tmp_path):
    """A run killed outright never says stop; the window must not outlive it."""
    import subprocess
    import sys

    gone = subprocess.Popen([sys.executable, "--version"], stdout=subprocess.DEVNULL)
    gone.wait()
    drawn = []
    screen.window(tmp_path / "log", 0, 10, tmp_path / "stop", gone.pid, drawn.append)
    assert drawn == [[]]
