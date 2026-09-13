<!--
Copyright 2026 Tabsdata Inc.
-->

# gsx scenario harness

Multi-clone scenarios against a real GitHub repository: several users creating, syncing,
modifying and moving PRs and stacks from different clones, with the outcome asserted in every
clone and on GitHub. The report of the last campaign is `docs/gsx-scenario-report.md`.

Not part of the gsx package and not run by `cargo make test`: it needs a throwaway repository,
network, and some twenty minutes per batch.

```bash
# once: a private throwaway repo with the trunk ruleset and branch deletion on merge,
# then three clones under GSX_SCENARIOS_DIR named alice, bob, carol, each `tdd gsx init`ed,
# with .githooks/pre-push committed to main (see docs/stack-workflow.md §1-2)
export GSX_SCENARIOS_DIR=/tmp/gsx-scenarios GSX_SCENARIOS_REPO=tabsdata/gsx-scenarios
python3 scen_ab.py            # baseline collaboration and cascades
python3 scen_c.py             # moves
python3 scen_def.py           # the guard, landed history, edges
python3 scen_c.py C3 C6       # a subset, by prefix
python3 mkreport.py out.md    # the results table and each scenario's steps
```

Each scenario uses its own branch prefix and cleans up before and after itself -- closing PRs,
deleting branches, dropping tracking -- so batches can be replayed in any order. Full command
transcripts land in `$GSX_SCENARIOS_DIR/logs/<prefix>.log`.
