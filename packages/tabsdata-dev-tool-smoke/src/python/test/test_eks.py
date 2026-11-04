#
# Copyright 2026 Tabsdata Inc.
#

"""What the EKS smoke reads and writes to give its apiserver the role that
reads worker logs from CloudWatch (`tdd _smoke eks-cluster`, `tdd _smoke
eks-role-documents`)."""

import io
import json

import pytest
from tabsdata_dev.tool.smoke import eks, engine

CALLER = "arn:aws:iam::123456789012:user/shreyas"
ISSUER = "https://oidc.eks.eu-west-1.amazonaws.com/id/0123456789ABCDEF"
PROVIDER = "oidc.eks.eu-west-1.amazonaws.com/id/0123456789ABCDEF"


def test_the_cluster_and_region_come_from_the_aws_cli_s_arguments(resource_folder):
    view = (resource_folder / "aws-cli.json").read_text()
    assert eks.cluster(view) == ("tabsdata-eks-dev", "eu-west-1")


def test_without_a_region_argument_the_server_s_host_names_it(resource_folder):
    view = (resource_folder / "no-region.json").read_text()
    assert eks.cluster(view) == ("tabsdata-eks-ohio", "us-east-2")


def test_a_context_that_is_not_eks_is_refused(resource_folder):
    with pytest.raises(ValueError, match="not an EKS context"):
        eks.cluster((resource_folder / "not-eks.json").read_text())


def test_the_role_trusts_only_the_instance_s_apiserver_service_account():
    trust, _ = eks.role_documents(CALLER, ISSUER, "sm-fixture", "eu-west-1")
    (statement,) = trust["Statement"]
    assert statement["Principal"]["Federated"] == (
        f"arn:aws:iam::123456789012:oidc-provider/{PROVIDER}"
    )
    assert statement["Action"] == "sts:AssumeRoleWithWebIdentity"
    assert statement["Condition"]["StringEquals"] == {
        f"{PROVIDER}:sub": "system:serviceaccount:sm-fixture:aut-apiserver",
        f"{PROVIDER}:aud": "sts.amazonaws.com",
    }


def test_the_role_reads_only_the_instance_s_log_group():
    _, permissions = eks.role_documents(CALLER, ISSUER, "sm-fixture", "eu-west-1")
    (statement,) = permissions["Statement"]
    assert statement["Action"] == ["logs:GetLogEvents"]
    assert statement["Resource"] == (
        "arn:aws:logs:eu-west-1:123456789012:log-group:/tabsdata/sm-fixture:*"
    )


def test_the_role_is_in_the_caller_s_partition():
    gov = "arn:aws-us-gov:sts::123456789012:assumed-role/admin/session"
    trust, permissions = eks.role_documents(gov, ISSUER, "sm-fixture", "us-gov-west-1")
    assert trust["Statement"][0]["Principal"]["Federated"].startswith(
        "arn:aws-us-gov:iam::"
    )
    assert permissions["Statement"][0]["Resource"].startswith("arn:aws-us-gov:logs:")


def test_a_caller_that_is_not_an_arn_is_refused():
    with pytest.raises(ValueError, match="not an AWS ARN"):
        eks.role_documents("shreyas", ISSUER, "sm-fixture", "eu-west-1")


def _run(monkeypatch, capsys, argv, text=""):
    monkeypatch.setattr("sys.argv", ["_smoke", *argv])
    monkeypatch.setattr("sys.stdin", io.StringIO(text))
    capsys.readouterr()
    code = engine.main()
    return code, capsys.readouterr().out.strip()


def test_the_helpers_answer_on_stdout_and_write_the_documents(
    resource_folder, tmp_path, monkeypatch, capsys
):
    view = (resource_folder / "aws-cli.json").read_text()
    assert _run(monkeypatch, capsys, ["eks-cluster"], view) == (
        0,
        "tabsdata-eks-dev eu-west-1",
    )

    trust, permissions = tmp_path / "trust.json", tmp_path / "permissions.json"
    argv = [
        "eks-role-documents",
        "--caller-arn",
        CALLER,
        "--issuer",
        ISSUER,
        "--namespace",
        "sm-fixture",
        "--region",
        "eu-west-1",
        "--trust",
        str(trust),
        "--permissions",
        str(permissions),
    ]
    assert _run(monkeypatch, capsys, argv)[0] == 0
    assert (json.loads(trust.read_text()), json.loads(permissions.read_text())) == (
        eks.role_documents(CALLER, ISSUER, "sm-fixture", "eu-west-1")
    )


def test_a_context_that_is_not_eks_fails_the_helper(
    resource_folder, monkeypatch, capsys
):
    view = (resource_folder / "not-eks.json").read_text()
    code, out = _run(monkeypatch, capsys, ["eks-cluster"], view)
    assert code == 1 and out == ""
