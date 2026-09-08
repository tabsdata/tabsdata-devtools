#
# Copyright 2026 Tabsdata Inc.
#

"""The label/reviewer engine: config lookups, validation, and one edit per PR.

Ops fold into one desired set per PR and a single `gh pr edit` carries the
difference, which has three consequences worth keeping: a PR already in the
desired state gets no call at all, two ops touching one PR cost one call, and
every PR is attempted even when one fails (the failures are collected, not
raised, because aborting at the first left stacks half-labelled).

Each PR of the snapshot is one numbered unit of progress -- see `progress`.
"""

from __future__ import annotations

from . import config as config_mod
from . import gh
from . import progress
from .args import LrOp
from .version import VERSION

FIELD = {"label": "labels", "reviewer": "reviewers"}


class Repo:
    """This repository's config entry, fetched at most once per run.

    Several callers need it and none should re-warn or re-fetch, so the entry
    and whether it was just fetched are remembered here.
    """

    def __init__(self, runner: gh.Runner, out) -> None:
        self.runner = runner
        self.out = out
        self._entry: dict | None = None
        self._fetched = False
        self._slug: str | None = None
        self._aliases: dict[str, str] | None = None

    @property
    def slug(self) -> str:
        if self._slug is None:
            self._slug = gh.repo_slug(self.runner)
        return self._slug

    def aliases(self) -> dict[str, str]:
        """The file's `[reviewer-aliases]`: a name of your own for a login."""
        if self._aliases is None:
            self._aliases = config_mod.read().get("aliases") or {}
        return self._aliases

    def entry(self) -> tuple[dict, bool]:
        if self._entry is None:
            self._entry, self._fetched = self._resolve()
        return self._entry, self._fetched

    def _resolve(self) -> tuple[dict, bool]:
        config = config_mod.read()
        if config.get("version") != VERSION:
            if config.get("repos"):
                self.out.warn(
                    f"the tables in {config_mod.path()} were written by gsx "
                    f"{config.get('version') or '(unversioned)'}, this is "
                    f"{VERSION}; refreshing them"
                )
            return (self.refresh(), True)
        entry = config.get("repos", {}).get(self.slug)
        if not entry or (not entry.get("labels") and not entry.get("reviewers")):
            return (self.refresh(), True)
        return (entry, False)

    def refresh(self) -> dict:
        """This repo's valid labels and reviewers, refreshed from GitHub.

        Called when the file has nothing for this repository, when it was
        written by another gsx, and once more when a value is missing -- the
        list may simply be stale. There is no verb for it: the reader never
        has to remember to run one."""
        slug = self.slug
        self.out.info(f"fetching the valid labels and reviewers of {slug}")
        labels = gh.fetch_labels(self.runner)
        reviewers = gh.fetch_reviewers(self.runner, slug)
        config = config_mod.read()
        # Per repository, always: labels and collaborators are the repository's,
        # and so are the defaults `submit`/`apply` put on its unlabelled PRs.
        entry = config.setdefault("repos", {}).setdefault(slug, {})
        entry["labels"] = labels
        entry["reviewers"] = reviewers
        entry["fetched"] = config_mod.now()
        # Refreshing the valid lists must never clobber the user's defaults.
        defaults = entry.setdefault("defaults", {})
        defaults.setdefault("labels", [])
        defaults.setdefault("reviewers", [])
        if self.runner.dry_run:
            self.out.info(f"[dry-run] write {config_mod.path()}", dry_run=True)
        else:
            config_mod.write(config)
        self._entry, self._fetched = entry, True
        return entry


def with_defaults(repo: Repo, ops: list[LrOp], disabled: bool) -> list[LrOp]:
    """Prepend the repo's defaults as `new`-scope ops.

    Defaults are for PRs that have none yet, which is exactly the `new` scope;
    putting them first means an explicit op still wins on a PR both touch.
    """
    if disabled:
        return ops
    entry, _ = repo.entry()
    defaults = entry.get("defaults") or {}
    implicit = [
        LrOp(
            kind,
            "new",
            "replace",
            list(defaults.get(f"{kind}s") or []),
            f"<default {kind}s>",
        )
        for kind in ("label", "reviewer")
        if defaults.get(f"{kind}s")
    ]
    return implicit + ops


def resolve_aliases(repo: Repo, ops: list[LrOp]) -> list[LrOp]:
    """Swap every reviewer alias for the login it names, before validation.

    An alias is the reader's own name for a person (`dimas = "aoinokimi"`), so
    it is resolved once here and everything downstream -- validation, the
    desired state, the `gh pr edit` argument -- sees the login.
    """
    table = repo.aliases()
    if not table:
        return ops
    resolved = []
    for op in ops:
        if op.kind != "reviewer":
            resolved.append(op)
            continue
        values = [table.get(value, value) for value in op.values]
        resolved.append(LrOp(op.kind, op.scope, op.mode, values, op.token))
    return resolved


def _unvalidatable(kind: str, value: str) -> bool:
    """Reviewers that are never in a collaborator list: Copilot, @me, and
    teams, which are `org/team-slug` rather than a login."""
    return kind == "reviewer" and (value.startswith("@") or "/" in value)


def check_values(repo: Repo, ops: list[LrOp]) -> None:
    """Validate every value against the config, refreshing it once when one is
    missing -- the list may simply be stale.

    `gh pr edit` is not atomic: given a bad add and a good remove, the remove
    lands and the add fails, so a `replace` with a typo would destroy the
    labels it meant to overwrite. Hence: validate first, write nothing.
    """
    wanted: dict[str, set[str]] = {"label": set(), "reviewer": set()}
    for op in ops:
        for value in op.values:
            if not _unvalidatable(op.kind, value):
                wanted[op.kind].add(value)
    if not wanted["label"] and not wanted["reviewer"]:
        return

    entry, fetched = repo.entry()

    def missing(entry: dict) -> dict[str, list[str]]:
        return {
            kind: sorted(values - set(entry.get(f"{kind}s", [])))
            for kind, values in wanted.items()
        }

    gaps = missing(entry)
    if any(gaps.values()) and not fetched:
        # The config may predate a label or collaborator that now exists.
        entry = repo.refresh()
        gaps = missing(entry)
    if any(gaps.values()):
        from tabsdata_dev.common.core.errors import ToolError

        lines = []
        for kind, values in gaps.items():
            if not values:
                continue
            valid = entry.get(f"{kind}s") or []
            lines.append(
                f"unknown {kind}(s): {', '.join(values)}\n"
                f"  valid {kind}s: {', '.join(valid) if valid else '(none)'}"
            )
        aliases = repo.aliases()
        if gaps.get("reviewer") and aliases:
            lines.append(
                "  reviewer aliases: "
                + ", ".join(f"{name} -> {aliases[name]}" for name in sorted(aliases))
            )
        raise ToolError(
            "not valid for this repository, even after refreshing "
            f"{config_mod.path()} -- nothing was changed:\n"
            + "\n".join(lines)
            + "\nCreate them on GitHub, fix the spelling, or edit the config; a "
            "replace with a bad name would strip the values it was meant to overwrite"
        )


def targets(op: LrOp, snapshot: list[dict], login: str) -> list[dict]:
    """The PRs an op applies to. `new` is judged on the pre-command snapshot,
    so an earlier op cannot erase a later one's targets."""
    if op.scope == "all":
        return list(snapshot)
    if op.scope == "top":
        return snapshot[-1:] if snapshot else []
    if op.scope == "mine":
        return [pull for pull in snapshot if pull["author"] == login]
    return [pull for pull in snapshot if not pull[FIELD[op.kind]]]


def apply(
    runner: gh.Runner,
    repo: Repo,
    ops: list[LrOp],
    extra: list[str],
    out,
    counter: progress.Counter | None = None,
) -> tuple[int, list[str]]:
    """Fold the ops into a desired state per PR and write the difference.

    Returns (changed, failures); the caller decides what a failure means.

    Every PR of the snapshot is one counted unit, the ones needing no call
    included -- `submit` hands in the counter it has been using since the push
    (open-ended, since the PRs did not exist when it started), and `apply`,
    which knows the snapshot is the whole of the work, gets a counter with the
    total in it.
    """
    snapshot = gh.stack_pr_snapshot(runner)
    if not snapshot:
        out.warn("no open PRs on this stack; nothing to label or assign")
        return (0, [])
    ops = resolve_aliases(repo, ops)
    check_values(repo, ops)
    login = gh.me(runner) if any(op.scope == "mine" for op in ops) else ""

    desired = {
        pull["number"]: {
            "labels": list(pull["labels"]),
            "reviewers": list(pull["reviewers"]),
        }
        for pull in snapshot
    }
    for op in ops:
        field = FIELD[op.kind]
        for pull in targets(op, snapshot, login):
            current = desired[pull["number"]][field]
            if op.mode == "replace":
                desired[pull["number"]][field] = list(op.values)
            else:
                desired[pull["number"]][field] = current + [
                    value for value in op.values if value not in current
                ]

    steps = counter or progress.Counter(out, total=len(snapshot))
    changed = 0
    failures: list[str] = []
    for pull in snapshot:
        number = pull["number"]
        argv = ["gh", "pr", "edit", str(number)]
        edits: list[str] = []
        for kind in ("label", "reviewer"):
            field = FIELD[kind]
            before, after = set(pull[field]), set(desired[number][field])
            for value in sorted(after - before):
                argv.extend([f"--add-{kind}", value])
                edits.append(f"+{kind} {value}")
            for value in sorted(before - after):
                argv.extend([f"--remove-{kind}", value])
                edits.append(f"-{kind} {value}")
        if not edits and not extra:
            # A PR in the desired state costs no call, but it still costs a
            # number: the reader is told it was looked at, and the last line
            # reaches the total.
            steps.step(
                f"#{number} already as asked", pr=number, outcome="unchanged", edits=[]
            )
            continue
        argv.extend(extra)
        detail = f": {', '.join(edits)}" if edits else ""
        try:
            runner.run(argv)
            changed += 1
            steps.step(
                f"updated #{number}{detail}",
                pr=number,
                outcome="updated",
                edits=edits,
            )
        except Exception as error:  # noqa: BLE001 -- every PR is attempted
            reason = str(error).splitlines()[-1]
            failures.append(f"PR #{number}: {reason}")
            steps.failed(
                f"#{number} could not be updated: {reason}",
                pr=number,
                outcome="failed",
                edits=edits,
            )
    return (changed, failures)
