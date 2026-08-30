<!--
Copyright 2026 Tabsdata Inc.
-->

# domain-sf

The `domain` tool running in the `salesforce` toolset, where cumulusci-plus and snowfakery live
(`sqlalchemy<2`, which the `systems` driver set contradicts). Hidden: `domain` dispatches to it
for salesforce data-plane verbs; nobody types it.

## Shape

- Toolset `salesforce` (Python 3.12); depends on `deps-salesforce`, `common-core`,
  `common-systems`; `[tool.tdd] hidden = true` keeps it out of `tdd help` only.
- Same entry point as `domain` (`common.systems.main.run("domain")`), so options, state dir and
  descriptors are identical; no `bin-reqs` of its own.
