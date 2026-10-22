#
# Copyright 2026 Tabsdata Inc.
#

"""``aws-check``: are these credentials able to provision and publish?

``aws-verify.sh`` as a subcommand, over boto3 rather than the ``aws`` CLI. The
tool already talks to AWS through boto3, so asking the same client the same
questions means the answers here and the calls a push makes cannot disagree --
a check that passed through a different code path would be worth less than it
looks.

Five sections, in the order a reader needs them:

1. **identity** -- whose credentials these are, and which account.
2. **read access** -- real calls that change nothing, so a denial is a fact
   rather than a prediction.
3. **provisioning** -- what ``tofu apply`` would need, simulated.
4. **runtime** -- what ``push`` needs on the buckets and distributions the
   config names, simulated.
5. **existing resources** -- what is already there, and whether the serving
   buckets are SSE-S3, which push's ETag change detection depends on.

**What a simulation does not prove.** ``iam:SimulatePrincipalPolicy`` evaluates
identity policies and SCPs. A resource policy, a permission boundary or a
session policy can still deny the same call for real. And the simulator needs a
permission of its own: when it is denied, its sections are *skipped*, never
passed -- a check that cannot run must not read like one that succeeded.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from tabsdata_dev.common.core import proc
from tabsdata_dev.common.core.errors import ToolError
from tabsdata_dev.common.core.render import Renderer

from .config import Config

#: CloudFront is global and signed for us-east-1 whatever the shell says.
CLOUDFRONT_REGION = "us-east-1"

#: What `tofu apply` needs, by the resource it creates.
PROVISIONING = (
    (
        "s3 bucket creation and settings",
        (
            "s3:CreateBucket",
            "s3:PutBucketVersioning",
            "s3:PutEncryptionConfiguration",
            "s3:PutBucketPublicAccessBlock",
            "s3:PutBucketPolicy",
            "s3:GetBucketPolicy",
            "s3:GetEncryptionConfiguration",
        ),
    ),
    (
        "cloudfront distribution and function",
        (
            "cloudfront:CreateDistribution",
            "cloudfront:UpdateDistribution",
            "cloudfront:CreateOriginAccessControl",
            "cloudfront:CreateFunction",
            "cloudfront:PublishFunction",
            "cloudfront:TagResource",
        ),
    ),
    (
        "iam roles and inline policies",
        (
            "iam:CreateRole",
            "iam:GetRole",
            "iam:PutRolePolicy",
            "iam:GetRolePolicy",
            "iam:TagRole",
        ),
    ),
    (
        "acm certificate (domain_enabled)",
        ("acm:RequestCertificate", "acm:DescribeCertificate", "acm:ListCertificates"),
    ),
    (
        "route53 records (domain_enabled)",
        (
            "route53:ChangeResourceRecordSets",
            "route53:ListHostedZones",
            "route53:GetChange",
        ),
    ),
    # Only needed to delegate pypi.tabsdata.com to Route 53, which is a one-off.
    # It is in the group policy, so a denial here means the policy has not been
    # rolled out -- exactly the case that fails halfway through the domain setup.
    ("route53 zone creation (delegated subdomain)", ("route53:CreateHostedZone",)),
)

#: Distribution ids lanes.yaml ships with before the first apply.
PLACEHOLDERS = ("EXXXXXXXXXXXXX", "EYYYYYYYYYYYYY")

#: The binaries `tools-verify.sh` checked. bin-reqs already refuses to dispatch
#: without them, so reaching here means they exist; their versions are still
#: worth reporting, since "installed" and "usable" are not the same thing.
TOOLING = (
    ("aws", ("aws", "--version")),
    ("tofu", ("tofu", "version")),
    ("uv", ("uv", "--version")),
    ("git", ("git", "--version")),
    ("curl", ("curl", "--version")),
    ("jq", ("jq", "--version")),
    ("openssl", ("openssl", "version")),
    ("dig", ("dig", "-v")),
)


@dataclass
class Findings:
    """What the run saw. `failed` decides the exit code; `skipped` is the
    simulator's own denial, which must not read as a pass."""

    passed: int = 0
    failed: list[str] = field(default_factory=list)
    warned: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def ok(self, out: Renderer, label: str) -> None:
        self.passed += 1
        out.info(f"  [ ok ]  {label}")

    def bad(self, out: Renderer, label: str) -> None:
        self.failed.append(label)
        out.warn(f"[FAIL]  {label}")

    def warn(self, out: Renderer, label: str) -> None:
        self.warned.append(label)
        out.warn(f"[warn]  {label}")

    def skip(self, out: Renderer, label: str) -> None:
        self.skipped.append(label)
        out.info(f"  [skip]  {label}")


def _version(argv: tuple[str, ...]) -> str:
    try:
        r = proc.run(list(argv), capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    first = (r.stdout or r.stderr or "").splitlines()
    return first[0].strip() if first else ""


def _tooling(out: Renderer, f: Findings) -> None:
    out.info("tooling")
    for name, argv in TOOLING:
        if shutil.which(name) is None:
            # bin-reqs should have refused before this, so a miss here means the
            # declaration and the list below have drifted apart.
            f.bad(out, f"{name} — not on PATH (bin-reqs.txt should have refused)")
            continue
        f.ok(out, f"{name:<8} {_version(argv)}")


def _principal(arn: str, account: str) -> str:
    """The ARN the simulator wants: the *role*, not the assumed-role session
    that get-caller-identity returns for SSO or an assumed role."""
    if ":assumed-role/" in arn:
        role = arn.split(":assumed-role/", 1)[1].split("/")[0]
        return f"arn:aws:iam::{account}:role/{role}"
    return arn


def _identity(out: Renderer, f: Findings, cfg: Config) -> tuple[str, str]:
    out.info("identity")
    try:
        caller = boto3.client("sts").get_caller_identity()
    except (ClientError, BotoCoreError) as exc:
        raise ToolError(
            f"no usable credentials ({exc}) — try: aws sso login --profile <name>.\n"
            "Nothing else can be checked without them."
        ) from exc
    account, arn = caller["Account"], caller["Arn"]
    f.ok(out, f"credentials resolve   {arn}")
    f.ok(out, f"account               {account}")
    if cfg.account == account:
        f.ok(out, "config/lanes.yaml     account matches")
    else:
        f.bad(
            out,
            f"config/lanes.yaml says account {cfg.account}, but you are in {account}",
        )
    return account, _principal(arn, account)


def _read_probes(out: Renderer, f: Findings, cfg: Config) -> None:
    """Real calls that change nothing: a denial here is a fact, not a
    prediction, which is why they run before anything is simulated."""
    out.info("read access (live calls, no changes made)")
    probes = (
        ("s3:ListAllMyBuckets", lambda: boto3.client("s3").list_buckets()),
        (
            "cloudfront:ListDistributions",
            lambda: boto3.client(
                "cloudfront", region_name=CLOUDFRONT_REGION
            ).list_distributions(),
        ),
        ("iam:ListRoles", lambda: boto3.client("iam").list_roles(MaxItems=1)),
        (
            "acm:ListCertificates",
            lambda: boto3.client(
                "acm", region_name=CLOUDFRONT_REGION
            ).list_certificates(),
        ),
        (
            "route53:ListHostedZones",
            lambda: boto3.client("route53").list_hosted_zones(MaxItems="1"),
        ),
    )
    for label, call in probes:
        try:
            call()
        except (ClientError, BotoCoreError):
            f.bad(out, label)
        else:
            f.ok(out, label)


class _Simulator:
    """`iam:SimulatePrincipalPolicy`, and whether it is available at all.

    Once the simulator itself is denied, every later section is skipped rather
    than re-asking: the answer will not change, and a wall of identical
    denials hides the one line that matters.
    """

    def __init__(self, principal: str) -> None:
        self.principal = principal
        self.available = True
        self._iam = boto3.client("iam")

    def check(
        self, out: Renderer, f: Findings, label: str, resource: str, actions
    ) -> None:
        if not self.available:
            f.skip(out, f"{label} (simulator unavailable)")
            return
        try:
            res = self._iam.simulate_principal_policy(
                PolicySourceArn=self.principal,
                ActionNames=list(actions),
                ResourceArns=[resource],
            )
        except (ClientError, BotoCoreError):
            self.available = False
            f.skip(out, f"{label} (simulator unavailable)")
            return
        denied = [
            r["EvalActionName"]
            for r in res["EvaluationResults"]
            if r["EvalDecision"] != "allowed"
        ]
        if denied:
            f.bad(out, f"{label} — denied: {' '.join(denied)}")
        else:
            f.ok(out, label)


def _provisioning(out: Renderer, f: Findings, sim: _Simulator) -> None:
    out.info("provisioning permissions (simulated — tofu apply)")
    for label, actions in PROVISIONING:
        sim.check(out, f, label, "*", actions)


def _runtime(
    out: Renderer, f: Findings, sim: _Simulator, cfg: Config, account: str
) -> None:
    out.info("runtime permissions (simulated — tdd pypi push, raw and serving lanes)")
    archive = cfg.archive.bucket
    sim.check(
        out,
        f,
        f"archive: write {archive}",
        f"arn:aws:s3:::{archive}/*",
        ("s3:PutObject", "s3:GetObject"),
    )
    sim.check(
        out,
        f,
        f"archive: list {archive}",
        f"arn:aws:s3:::{archive}",
        ("s3:ListBucket",),
    )
    for lane in cfg.lanes.values():
        sim.check(
            out,
            f,
            f"serving: write {lane.bucket}/files, {lane.bucket}/simple",
            f"arn:aws:s3:::{lane.bucket}/*",
            ("s3:PutObject", "s3:GetObject", "s3:DeleteObject"),
        )
        # push asserts the bucket is SSE-S3 before trusting ETag change
        # detection, and fails closed without this permission.
        sim.check(
            out,
            f,
            f"serving: list + encryption config {lane.bucket}",
            f"arn:aws:s3:::{lane.bucket}",
            ("s3:ListBucket", "s3:GetEncryptionConfiguration"),
        )
    for lane in cfg.lanes.values():
        if lane.distribution in PLACEHOLDERS:
            f.skip(out, f"invalidation on {lane.distribution} (still a placeholder)")
            continue
        sim.check(
            out,
            f,
            f"cloudfront:CreateInvalidation on {lane.distribution}",
            f"arn:aws:cloudfront::{account}:distribution/{lane.distribution}",
            ("cloudfront:CreateInvalidation",),
        )


def _existing(out: Renderer, f: Findings, cfg: Config) -> None:
    out.info("existing resources")
    s3 = boto3.client("s3", region_name=cfg.region)
    buckets = [cfg.archive.bucket, *(lane.bucket for lane in cfg.lanes.values())]
    for bucket in buckets:
        try:
            s3.head_bucket(Bucket=bucket)
        except (ClientError, BotoCoreError):
            f.skip(out, f"s3://{bucket} does not exist yet")
            continue
        try:
            enc = s3.get_bucket_encryption(Bucket=bucket)
            algo = enc["ServerSideEncryptionConfiguration"]["Rules"][0][
                "ApplyServerSideEncryptionByDefault"
            ]["SSEAlgorithm"]
        except (ClientError, BotoCoreError, KeyError, IndexError):
            f.warn(
                out,
                f"s3://{bucket} reachable, but its encryption config could not be read",
            )
            continue
        if algo == "AES256":
            f.ok(out, f"s3://{bucket} reachable, SSE-S3")
        else:
            f.bad(
                out,
                f"s3://{bucket} uses {algo}; push needs AES256 for ETag change detection",
            )


def aws_check(cfg: Config, out: Renderer) -> int:
    """Every section, then one line saying whether to trust the result."""
    f = Findings()
    _tooling(out, f)
    account, principal = _identity(out, f, cfg)
    _read_probes(out, f, cfg)
    sim = _Simulator(principal)
    _provisioning(out, f, sim)
    _runtime(out, f, sim, cfg, account)
    _existing(out, f, cfg)

    if not sim.available:
        f.warn(
            out,
            "iam:SimulatePrincipalPolicy is denied — the simulated sections were "
            "SKIPPED, not passed",
        )
    summary = (
        f"{f.passed} ok, {len(f.failed)} failed, "
        f"{len(f.warned)} warning(s), {len(f.skipped)} skipped"
    )
    if f.failed:
        raise ToolError(
            f"{summary}\n  "
            + "\n  ".join(f.failed[:10])
            + "\n\nA simulation reflects identity policies and SCPs only: a resource "
            "policy,\na permission boundary or a session policy can still deny at "
            "call time."
        )
    return out.ok(
        summary,
        account=account,
        principal=principal,
        passed=f.passed,
        warned=f.warned,
        skipped=f.skipped,
        simulated=sim.available,
    )
