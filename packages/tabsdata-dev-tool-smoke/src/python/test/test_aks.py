#
# Copyright 2026 Tabsdata Inc.
#

"""What the AKS smoke reads to give its apiserver the managed identity that
reads worker logs from Log Analytics (`tdd _smoke aks-cluster`,
`aks-condition`, `aks-has-assignment`)."""

import io

import pytest
from tabsdata_dev.tool.smoke import aks, engine

SUBSCRIPTION = "9dd049b8-201a-41da-88e5-d6123d9f157a"
WORKSPACE = (
    f"/subscriptions/{SUBSCRIPTION}/resourceGroups/tabsdata-dev/providers/"
    "Microsoft.OperationalInsights/workspaces/tabsdata-aks-dev-logs"
)
PRINCIPAL = "22222222-2222-2222-2222-222222222222"


def test_the_cluster_is_the_one_whose_api_server_the_context_names(resource_folder):
    view = (resource_folder / "get-credentials.json").read_text()
    clusters = (resource_folder / "clusters.json").read_text()
    assert aks.cluster(view, clusters) == [
        SUBSCRIPTION,
        "tabsdata-dev",
        "tabsdata-aks-dev",
        "https://spaincentral.oic.prod-aks.azure.com/00000000-0000-0000-0000-000000000000/11111111-1111-1111-1111-111111111111/",
        "true",
        WORKSPACE,
    ]


def test_a_private_cluster_is_found_by_its_private_name_and_says_what_it_lacks(
    resource_folder,
):
    """No issuer, no Workload Identity, and a monitoring addon that is off
    names no workspace, whatever its config still holds."""
    view = (resource_folder / "private.json").read_text()
    clusters = (resource_folder / "clusters.json").read_text()
    assert aks.cluster(view, clusters) == [
        SUBSCRIPTION,
        "tabsdata-dev",
        "tabsdata-private",
        "-",
        "false",
        "-",
    ]


def test_another_subscription_s_clusters_do_not_match(resource_folder):
    view = (resource_folder / "get-credentials.json").read_text()
    assert aks.cluster(view, "[]") is None


def test_the_condition_names_the_table_and_the_namespace():
    found = aks.condition("sm-fixture")
    assert "StringEquals 'ContainerLogV2'" in found
    assert "PodNamespace<$key_case_sensitive$>] StringEquals 'sm-fixture'" in found
    assert found.startswith("((!(ActionMatches{") and found.endswith("))")


def test_an_assignment_is_present_only_under_this_namespace_s_condition(
    resource_folder,
):
    listing = (resource_folder / "assignments.json").read_text()
    state, found = aks.assignment(listing, PRINCIPAL, "sm-fixture")
    assert state == aks.PRESENT and found.endswith("000000000001")
    # the same identity under another namespace's condition is not added to
    assert aks.assignment(listing, PRINCIPAL, "sm-other") == (aks.DIFFERENT, "")
    assert aks.assignment(listing, "55555555-5555-5555-5555-555555555555", "sm-x") == (
        aks.ABSENT,
        "",
    )
    # another role is no Data Reader assignment at all
    other = "44444444-4444-4444-4444-444444444444"
    assert aks.assignment(listing, other, "sm-fixture") == (aks.ABSENT, "")


def test_a_condition_is_compared_with_its_spacing_squeezed(resource_folder):
    listing = (resource_folder / "assignments.json").read_text()
    spaced = listing.replace(" OR (", "  OR\\n (")
    assert aks.assignment(spaced, PRINCIPAL, "sm-fixture")[0] == aks.PRESENT


def _run(monkeypatch, capsys, argv, text=""):
    monkeypatch.setattr("sys.argv", ["_smoke", *argv])
    monkeypatch.setattr("sys.stdin", io.StringIO(text))
    capsys.readouterr()
    code = engine.main()
    return code, capsys.readouterr().out.strip()


def test_the_helpers_answer_on_stdout(resource_folder, monkeypatch, capsys):
    view = (resource_folder / "get-credentials.json").read_text()
    clusters = ["aks-cluster", "--clusters", str(resource_folder / "clusters.json")]
    code, out = _run(monkeypatch, capsys, clusters, view)
    assert code == 0 and out.split()[:3] == [
        SUBSCRIPTION,
        "tabsdata-dev",
        "tabsdata-aks-dev",
    ]
    none = ["aks-cluster", "--clusters", str(resource_folder / "assignments.json")]
    assert _run(monkeypatch, capsys, none, view) == (0, "")

    cond = ["aks-condition", "--namespace", "sm-fixture"]
    assert _run(monkeypatch, capsys, cond) == (0, aks.condition("sm-fixture"))

    listing = (resource_folder / "assignments.json").read_text()
    held = ["aks-has-assignment", "--principal", PRINCIPAL, "--namespace"]
    code, out = _run(monkeypatch, capsys, [*held, "sm-fixture"], listing)
    assert code == 0 and out.startswith("present /subscriptions/")
    assert _run(monkeypatch, capsys, [*held, "sm-other"], listing) == (0, "different")


@pytest.mark.parametrize("fixture", ["get-credentials.json", "private.json"])
def test_the_host_is_read_without_scheme_or_port(resource_folder, fixture):
    host = aks._host((resource_folder / fixture).read_text())
    assert host.endswith(".azmk8s.io") and ":" not in host
