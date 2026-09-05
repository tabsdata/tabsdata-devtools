#
# Copyright 2026 Tabsdata Inc.
#

"""`gsx approve`: approve PRs as one or more people, the way `gtx approve` does.

An approver is impersonated with their own review token, read from 1Password
by **GitHub username**: vault `dev_ci`, item `GitHub`, field
`<login>.review.pat` by default -- all three live in the config's `[gsx]`
table. A `[reviewer-aliases]` name is resolved to that login first, so your own
name for someone works here as it does for `--reviewer:`. One fetch per
approver serves every PR of the run, and a PR the token's owner wrote is
skipped rather than failed: GitHub refuses a self-approval, and refusing it is
not the run's problem.

Which PRs: `--pr` names them, `--down-stack` takes the current PR and the ones
it sits on down to main, `--stack` takes the whole stack. Downstack and upstack
are the usual stacking words -- downstack is towards the trunk -- and downstack
is the set that has to be approved for the current PR to merge.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from tabsdata_dev.common.core import secrets_1p
from tabsdata_dev.common.core.errors import ToolError

from . import gh

# What gh says when a token's owner is the PR's author.
SELF_APPROVAL = "Can not approve your own pull request"


@dataclass
class Approver:
    """One impersonated approver: the name typed, and the login it stands for."""

    name: str  # the 1Password field's name, and gtx's short name
    login: str  # the GitHub login, when an alias names it


def resolve(names: list[str], aliases: dict[str, str]) -> list[Approver]:
    """Each name as (as typed, GitHub login), through `[reviewer-aliases]`.

    An alias is `<name> = "<login>"`: your own name for a person. The login is
    what everything downstream needs -- 1Password holds a PAT per GitHub
    username, and a self-approval is one where the author is that login -- so
    the alias is resolved once, here. A name that is not an alias is taken as
    a login already.
    """
    return [Approver(name, aliases.get(name, name)) for name in names]


def token(runner: gh.Runner, approver: Approver, settings: dict) -> str:
    """The approver's review token, by GitHub username. One fetch per approver,
    per run: every PR of the run is approved with it."""
    field = f"{approver.login}{settings['approve_pat_suffix']}"
    ref = f"op://{settings['approve_vault']}/{settings['approve_item']}/{field}"
    runner.out.info(f"reading {ref}")
    if runner.dry_run:
        return ""
    return secrets_1p.read_field(
        settings["approve_vault"], settings["approve_item"], field
    )


APPROVED = "approved"
SKIPPED = "skipped"


def approve(
    runner: gh.Runner,
    slug: str,
    pull: dict,
    approver: Approver,
    pat: str,
) -> str:
    """Approve one PR as one approver.

    Returns APPROVED, SKIPPED (theirs to write, not to approve), or the reason
    it failed -- every PR is attempted, as everywhere else in gsx.
    """
    number = str(pull["number"])
    who = approver.login + (
        f" ({approver.name})" if approver.name != approver.login else ""
    )
    if pull.get("author") and pull["author"] == approver.login:
        runner.out.info(f"skipping PR #{number}: {approver.login} wrote it")
        return SKIPPED
    argv = ["gh", "pr", "review", "--approve", "--repo", slug, number]
    if runner.dry_run:
        runner.out.info(f"[dry-run] {gh.join(argv)}", dry_run=True, approver=who)
        return APPROVED
    try:
        # The token is the impersonation: everything else about the environment
        # is this shell's.
        runner.run(argv, env={**os.environ, "GITHUB_TOKEN": pat})
    except ToolError as error:
        if SELF_APPROVAL in str(error):
            runner.out.info(f"skipping PR #{number}: it is {approver.login}'s own")
            return SKIPPED
        return f"PR #{number} as {who}: {str(error).splitlines()[-1]}"
    return APPROVED
