#
# Copyright 2026 Tabsdata Inc.
#

from tabsdata_dev.common.core import parallel, proc, report


def test_map_bounded_preserves_order():
    assert parallel.map_bounded(lambda n: n * 2, range(6)) == [0, 2, 4, 6, 8, 10]


def test_map_bounded_handles_empty():
    assert parallel.map_bounded(str, []) == []


def test_report_tracks_failures():
    r = report.Report()
    r.ok("fine")
    assert r.exit_code == 0
    r.fail("broken")
    assert r.exit_code == 1


def test_run_allows_anything_outside_a_tdd_dispatch(monkeypatch):
    monkeypatch.delenv("TDD_TOOL", raising=False)
    proc._declared.cache_clear()
    proc._toolset_bin.cache_clear()
    assert proc.run(["true"]).returncode == 0


def test_run_refuses_an_undeclared_binary(monkeypatch, tmp_path):
    (tmp_path / "catalog.json").write_text(
        '{"tools": {"demo-exe1": {"toolset": "demo-env1", "reqs": ["git"]}}}'
    )
    monkeypatch.setenv("TDD_DIR", str(tmp_path))
    monkeypatch.setenv("TDD_TOOL", "demo-exe1")
    proc._declared.cache_clear()
    proc._toolset_bin.cache_clear()
    try:
        proc.run(["jq", "."])
    except proc.UndeclaredRequirement as exc:
        assert "bin-reqs.txt" in str(exc)
        return
    raise AssertionError("expected UndeclaredRequirement")
