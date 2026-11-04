#
# Copyright 2026 Tabsdata Inc.
#

"""What the GKE smoke reads to give its apiserver the service account and view
that read worker logs from Cloud Logging (`tdd _smoke gke-cluster`,
`gke-log-bucket`, `gke-service-account`, `gke-has-binding`)."""

import io
import re

import pytest
from tabsdata_dev.tool.smoke import engine, gke

GSA = "serviceAccount:td-sm-fixture-apiserver@tabsdata-dev.iam.gserviceaccount.com"
VIEW = (
    "projects/tabsdata-dev/locations/global/buckets/_Default/views/tabsdata-sm-fixture"
)
WORKLOAD = "serviceAccount:tabsdata-dev.svc.id.goog[sm-fixture/aut-apiserver]"


def test_the_project_location_and_cluster_come_from_the_context_name(resource_folder):
    view = (resource_folder / "get-credentials.json").read_text()
    assert gke.cluster(view) == ("tabsdata-dev", "europe-west1", "tabsdata-gke-dev")


def test_a_renamed_context_is_read_by_its_cluster_entry(resource_folder):
    view = (resource_folder / "renamed.json").read_text()
    assert gke.cluster(view) == ("tabsdata-dev", "europe-west1-b", "tabsdata-gke-zonal")


def test_a_context_that_is_not_gke_is_refused(resource_folder):
    with pytest.raises(ValueError, match="gke_<project>_<location>_<cluster>"):
        gke.cluster((resource_folder / "not-gke.json").read_text())


@pytest.mark.parametrize(
    "sinks, buckets, expected",
    [
        ("sinks-default.json", "buckets-global.json", ("_Default", "global")),
        # a project with a default storage location keeps _Default there
        ("sinks-default.json", "buckets-regional.json", ("_Default", "europe-west1")),
        # the dguide's own sink, enabled, wins over a disabled one and _Default
        (
            "sinks-tabsdata.json",
            "buckets-global.json",
            ("tabsdata-logs", "europe-west1"),
        ),
    ],
)
def test_the_view_goes_where_the_tabsdata_logs_land(
    resource_folder, sinks, buckets, expected
):
    found = gke.log_bucket(
        (resource_folder / sinks).read_text(), (resource_folder / buckets).read_text()
    )
    assert found == expected


def test_nothing_listed_means_default_in_global():
    assert gke.log_bucket("", "") == ("_Default", "global")


ID = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")


def test_the_service_account_is_named_after_the_namespace_while_it_fits():
    assert gke.service_account("sm-fixture") == "td-sm-fixture-apiserver"
    assert len(gke.service_account("sm-abcdefghijklmn")) == 30


@pytest.mark.parametrize(
    "namespace", ["sm-abcdefghijklmno", "sm-" + "a" * 60, "sm-abcdefghijklmnopq-r"]
)
def test_a_long_namespace_gets_a_short_valid_id_of_its_own(namespace):
    found = gke.service_account(namespace)
    assert ID.match(found), found
    assert found == gke.service_account(namespace)
    assert found != gke.service_account(namespace + "x")


def test_a_binding_is_present_only_under_its_own_condition(resource_folder):
    policy = (resource_folder / "project-policy.json").read_text()
    role = "roles/logging.viewAccessor"
    assert gke.has_binding(policy, role, GSA, f'resource.name == "{VIEW}"')
    # another view's condition, or none, is not this grant
    other = VIEW.replace("sm-fixture", "sm-other")
    assert not gke.has_binding(policy, role, GSA, f'resource.name == "{other}"')
    assert not gke.has_binding(policy, role, GSA)
    assert not gke.has_binding(policy, "roles/logging.viewer", GSA)


def test_an_unconditional_binding_is_read_as_such(resource_folder):
    policy = (resource_folder / "gsa-policy.json").read_text()
    assert gke.has_binding(policy, "roles/iam.workloadIdentityUser", WORKLOAD)
    other = WORKLOAD.replace("sm-fixture", "sm-other")
    assert not gke.has_binding(policy, "roles/iam.workloadIdentityUser", other)
    assert not gke.has_binding("{}", "roles/iam.workloadIdentityUser", WORKLOAD)


def _run(monkeypatch, capsys, argv, text=""):
    monkeypatch.setattr("sys.argv", ["_smoke", *argv])
    monkeypatch.setattr("sys.stdin", io.StringIO(text))
    capsys.readouterr()
    code = engine.main()
    return code, capsys.readouterr().out.strip()


def test_the_helpers_answer_on_stdout(resource_folder, monkeypatch, capsys):
    view = (resource_folder / "get-credentials.json").read_text()
    assert _run(monkeypatch, capsys, ["gke-cluster"], view) == (
        0,
        "tabsdata-dev europe-west1 tabsdata-gke-dev",
    )
    bucket = [
        "gke-log-bucket",
        "--sinks",
        str(resource_folder / "sinks-tabsdata.json"),
        "--buckets",
        str(resource_folder / "buckets-global.json"),
    ]
    assert _run(monkeypatch, capsys, bucket) == (0, "tabsdata-logs europe-west1")
    account = ["gke-service-account", "--namespace", "sm-fixture"]
    assert _run(monkeypatch, capsys, account) == (0, "td-sm-fixture-apiserver")


def test_a_missing_binding_is_an_answer_not_an_error(
    resource_folder, monkeypatch, capsys
):
    """The script adds what is absent: a no is exit 0."""
    policy = (resource_folder / "gsa-policy.json").read_text()
    held = ["gke-has-binding", "--role", "roles/iam.workloadIdentityUser"]
    assert _run(monkeypatch, capsys, [*held, "--member", WORKLOAD], policy) == (
        0,
        engine.PRESENT,
    )
    other = WORKLOAD.replace("sm-fixture", "sm-other")
    assert _run(monkeypatch, capsys, [*held, "--member", other], policy) == (
        0,
        engine.ABSENT,
    )


def test_a_context_that_is_not_gke_fails_the_helper(
    resource_folder, monkeypatch, capsys
):
    view = (resource_folder / "not-gke.json").read_text()
    code, out = _run(monkeypatch, capsys, ["gke-cluster"], view)
    assert code == 1 and out == ""
