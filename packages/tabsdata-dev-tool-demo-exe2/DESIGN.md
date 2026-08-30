<!--
Copyright 2026 Tabsdata Inc.
-->

# demo-exe2

A sample Python tool: prints its own name. It exists to show the shape of a tool and to exercise
the machinery -- toolset `demo-env2` pins `packaging` differently from the other demo toolset on
purpose, proving that two toolsets resolve independently.

## Shape

- Toolset `demo-env2`; depends on `deps-demo-env2`, `common-core`; `[tool.tdd] demo = true`
  keeps it out of `tdd help` unless `--demo` is given. No `bin-reqs`: it shells out to nothing.
- Dispatches, tests and reports requirements like any real tool. Copy it to start a new tool
  (and drop the `demo` flag).
