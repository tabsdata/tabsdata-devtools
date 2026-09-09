#
# Copyright 2026 Tabsdata Inc.
#

"""Which local branches `gsx purge` may delete, and why it keeps the rest.

A stacking workflow leaves branches behind, and every one of them was a PR --
so GitHub already knows which are finished. A branch is worth keeping while its
PR is open; once that PR is merged or closed the branch is a leftover. purge
asks GitHub for the state of each local branch's PRs and deletes the ones that
came back done with.

The verdict for one branch is reached here so it can be read and tested without
a repository; `commands.purge` does the asking and the deleting and numbers the
units. Four rules keep it from taking something wanted:

* the **trunk** is never a candidate, and neither are `main`/`master` whatever
  the trunk turns out to be;
* a branch with **any** open PR is kept, even when an older PR of its own was
  merged -- a reopened or second-attempt branch is exactly what a
  one-PR-per-branch assumption gets wrong, and it is the case where guessing
  wrong costs live work;
* a branch GitHub has **no** PR for is kept. Local-only work is not this
  command's business, and it is indistinguishable from work not yet pushed;
* the branch that is **checked out** is kept whatever its PR says. git would
  refuse to delete it anyway, and saying which branch to switch off is more use
  than git's message.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Never candidates, whatever the trunk turns out to be: a repository whose
#: default branch is `develop` still should not lose `main`.
ALWAYS_KEPT = ("main", "master")

#: What GitHub calls a PR that is done with. `OPEN` is the only other state.
FINISHED = ("MERGED", "CLOSED")

DELETED = "deleted"
KEPT = "kept"
FAILED = "failed"


@dataclass
class Verdict:
    """One branch, what is to become of it, and the reason in the words the
    progress line and the `--format json` fields both use."""

    branch: str
    outcome: str  # deleted | kept | failed
    reason: str
    pr: int | None = None
    state: str = ""

    def line(self) -> str:
        """The progress line for this branch."""
        if self.outcome == FAILED:
            return f"could not delete {self.branch}: {self.reason}"
        return f"{self.outcome} {self.branch}: {self.reason}"


def candidates(
    branches: list[str], trunk: str, protected: tuple[str, ...] = ALWAYS_KEPT
) -> list[str]:
    """The branches purge is allowed to have an opinion about."""
    off_limits = {trunk, *protected} - {""}
    return [branch for branch in branches if branch not in off_limits]


def newest(pulls: list[dict]) -> dict | None:
    """The branch's most recent PR: GitHub numbers them in order, so the
    highest number is the last thing that happened to this branch."""
    numbered = [pull for pull in pulls if isinstance(pull.get("number"), int)]
    return max(numbered, key=lambda pull: pull["number"]) if numbered else None


def classify(
    branch: str, pulls: list[dict], *, merged_only: bool, checked_out: bool
) -> Verdict:
    """What is to become of `branch`, given every PR GitHub has for it."""
    states = {(pull.get("state") or "").upper() for pull in pulls}
    latest = newest(pulls)

    if not pulls:
        return Verdict(branch, KEPT, "no PR")
    if "OPEN" in states:
        open_pr = newest([p for p in pulls if (p.get("state") or "").upper() == "OPEN"])
        number = (open_pr or {}).get("number")
        return Verdict(branch, KEPT, f"open PR #{number}", number, "OPEN")

    number = (latest or {}).get("number")
    state = ((latest or {}).get("state") or "").upper()
    if state not in FINISHED:
        # A state gh has that gsx does not know is a reason to do nothing.
        return Verdict(
            branch, KEPT, f"PR #{number} is {state or 'unknown'}", number, state
        )
    if state == "CLOSED" and merged_only:
        return Verdict(
            branch, KEPT, f"closed PR #{number}, --merged-only", number, state
        )
    done = f"{state.lower()} #{number}"
    if checked_out:
        return Verdict(
            branch,
            KEPT,
            f"{done}, but checked out -- switch away to delete it",
            number,
            state,
        )
    return Verdict(branch, DELETED, done, number, state)
