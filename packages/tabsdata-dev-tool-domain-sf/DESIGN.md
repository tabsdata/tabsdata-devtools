<!--
Copyright 2026 Tabsdata Inc.
-->

# domain-sf

The `domain` tool running in the `salesforce` toolset, where cumulusci-plus and snowfakery live
(`sqlalchemy<2`, which the `systems` driver set contradicts). Hidden: `domain` dispatches to it
for salesforce data-plane verbs; nobody types it.

## Shape

- Toolset `salesforce` (Python 3.12); depends on `deps-salesforce`, `common-core`,
  `common-systems`; `[tool.tdd] hidden = true` keeps it out of `tdd help` only -- it still
  dispatches, which is the whole point.
- Same entry point as `domain` (`common.systems.main.run("domain")`), so options, state dir and
  descriptors are identical; no `bin-reqs` of its own.

## Why a second tool rather than a second env

`DOMAIN_TOOL_BY_TOOLSET` maps a toolset to the tool that runs the domain family in it, and
`_reroute` uses it: a verb whose backend or model needs `salesforce` is handed to `domain-sf`
with its arguments unchanged. The alternative -- one tool reaching into another venv -- would
mean importing across resolutions that deliberately disagree. Adding a third data-plane toolset
is a package like this one plus a line in that map.
