#
# Copyright 2026 Tabsdata Inc.
#

"""`aws-check` against a stubbed AWS.

The case that matters most is the third one: when the simulator is itself
denied, its sections must read as SKIPPED, never as passed. A check that cannot
run and a check that succeeded look the same to a reader who is only watching
the exit code, and that is exactly the reader this command has.
"""

from __future__ import annotations

import pytest
from conftest import make_cfg
from tabsdata_dev.common.core.errors import ToolError
from tabsdata_dev.tool.pypi import aws_check as mod

ACCOUNT = "123456789012"
ARN = f"arn:aws:sts::{ACCOUNT}:assumed-role/AdminRole/tucu"


class FakeIam:
    """simulate_principal_policy, answering from a set of denied actions."""

    def __init__(self, denied=(), broken=False):
        self.denied, self.broken = set(denied), broken
        self.asked = []

    def simulate_principal_policy(self, *, PolicySourceArn, ActionNames, ResourceArns):
        if self.broken:
            raise mod.ClientError(
                {"Error": {"Code": "AccessDenied", "Message": "no"}},
                "SimulatePrincipalPolicy",
            )
        self.asked.append((ResourceArns[0], tuple(ActionNames)))
        return {
            "EvaluationResults": [
                {
                    "EvalActionName": a,
                    "EvalDecision": "implicitDeny" if a in self.denied else "allowed",
                }
                for a in ActionNames
            ]
        }

    def list_roles(self, **_kw):
        return {"Roles": []}


class FakeS3:
    def __init__(self, sse="AES256", missing=()):
        self.sse, self.missing = sse, set(missing)

    def list_buckets(self):
        return {"Buckets": []}

    def head_bucket(self, Bucket):
        if Bucket in self.missing:
            raise mod.ClientError({"Error": {"Code": "404"}}, "HeadBucket")

    def get_bucket_encryption(self, Bucket):
        return {
            "ServerSideEncryptionConfiguration": {
                "Rules": [
                    {"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": self.sse}}
                ]
            }
        }


class FakeOther:
    """cloudfront / acm / route53 / sts, none of which this test varies."""

    def get_caller_identity(self):
        return {"Account": ACCOUNT, "Arn": ARN}

    def list_distributions(self):
        return {}

    def list_certificates(self):
        return {}

    def list_hosted_zones(self, **_kw):
        return {}


@pytest.fixture
def aws(monkeypatch):
    """Point every boto3.client at a fake, and make the binaries look present."""
    state = {"iam": FakeIam(), "s3": FakeS3()}

    def client(name, **_kw):
        return state.get(name, FakeOther())

    monkeypatch.setattr(mod.boto3, "client", client)
    monkeypatch.setattr(mod.shutil, "which", lambda _n: "/usr/bin/x")
    monkeypatch.setattr(mod, "_version", lambda _argv: "1.2.3")
    return state


def test_everything_allowed_reports_ok(aws, events, out):
    assert mod.aws_check(make_cfg(), out) == 0
    said = events.text
    assert "0 failed" in said and "[FAIL]" not in said
    # the sections a reader looks for, in order
    for section in ("tooling", "identity", "read access", "provisioning", "runtime"):
        assert section in said


def test_a_denied_action_fails_and_names_it(aws, events, out):
    aws["iam"] = FakeIam(denied={"s3:PutObject"})
    with pytest.raises(ToolError) as exc:
        mod.aws_check(make_cfg(), out)
    assert "s3:PutObject" in str(exc.value)
    # and it still says what a simulation cannot prove
    assert "resource policy" in str(exc.value)


def test_a_denied_simulator_skips_and_never_passes(aws, events, out):
    """The whole point: `iam:SimulatePrincipalPolicy` being denied must not read
    as the permissions being fine."""
    aws["iam"] = FakeIam(broken=True)
    mod.aws_check(make_cfg(), out)
    said = events.text
    assert "simulator unavailable" in said
    assert "SKIPPED, not passed" in said
    # every simulated section skipped, none of them counted as a pass
    assert said.count("[skip]") >= len(mod.PROVISIONING)


def test_the_simulator_is_asked_once_then_left_alone(aws, out):
    """A denial is permanent for the run: re-asking would bury the one line that
    matters under a wall of identical failures."""
    iam = FakeIam(broken=True)
    aws["iam"] = iam
    mod.aws_check(make_cfg(), out)
    assert iam.asked == []


def test_wrong_account_is_a_failure(aws, out):
    cfg = make_cfg()
    object.__setattr__(cfg, "account", "999999999999")
    with pytest.raises(ToolError, match="999999999999"):
        mod.aws_check(cfg, out)


def test_a_bucket_that_is_not_sse_s3_fails(aws, out):
    """push's change detection trusts the ETag, which only holds for SSE-S3."""
    aws["s3"] = FakeS3(sse="aws:kms")
    with pytest.raises(ToolError, match="AES256"):
        mod.aws_check(make_cfg(), out)


def test_a_missing_bucket_is_skipped_not_failed(aws, events, out):
    """Before the first apply there is nothing to check, which is not a fault."""
    aws["s3"] = FakeS3(missing={"td-raw-wheels", "td-pypi-staging", "td-pypi-prod"})
    assert mod.aws_check(make_cfg(), out) == 0
    assert "does not exist yet" in events.text


def test_no_credentials_is_one_error_not_a_traceback(aws, monkeypatch, out):
    class NoCreds(FakeOther):
        def get_caller_identity(self):
            raise mod.ClientError(
                {"Error": {"Code": "InvalidClientTokenId"}}, "GetCallerIdentity"
            )

    monkeypatch.setattr(
        mod.boto3,
        "client",
        lambda name, **_k: NoCreds() if name == "sts" else FakeOther(),
    )
    with pytest.raises(ToolError, match="no usable credentials"):
        mod.aws_check(make_cfg(), out)


def test_the_role_arn_is_what_the_simulator_is_given(aws, out):
    """get-caller-identity returns the assumed-role *session*; the simulator
    wants the role."""
    assert mod._principal(ARN, ACCOUNT) == f"arn:aws:iam::{ACCOUNT}:role/AdminRole"
    # a plain user ARN is already what it wants
    user = f"arn:aws:iam::{ACCOUNT}:user/tucu"
    assert mod._principal(user, ACCOUNT) == user


def test_a_placeholder_distribution_is_skipped(aws, events, out):
    cfg = make_cfg()
    object.__setattr__(cfg.lanes["staging"], "distribution", mod.PLACEHOLDERS[0])
    mod.aws_check(cfg, out)
    assert "still a placeholder" in events.text
