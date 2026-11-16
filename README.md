<!--
Copyright 2026 Tabsdata Inc.
-->

<div align="center">
    <img src="assets/images/tabsdata-logo-for-light-theme.svg#gh-light-mode-only" alt="Tabsdata" width="500">
    <img src="assets/images/tabsdata-logo-for-dark-theme.svg#gh-dark-mode-only" alt="Tabsdata" width="500">
</div>

<div align="center">
    <a href="https://tabsdata.com">Tabsdata</a> |
    <a href="https://github.com/tabsdata/tabsdata">tabsdata</a> |
    <a href="https://github.com/tabsdata/tabsdata-devtools">GitHub Repository</a>
</div>

# Tabsdata DevTools

**One command, `tdd`, in front of every Tabsdata developer tool, each tool in its own isolated
environment, so that tool dependencies never touch a project's dependencies.**

It holds the developer tools of [tabsdata](https://github.com/tabsdata/tabsdata): setup, build
and test (`tdd`). Among them is the tool that creates the databases and storage the tests of
tabsdata run against.

Python tools live in per-toolset virtual environments, and **tdd** dispatches each command into
its own. Shell commands, the ones that must change *your* shell, like entering a virtual
environment, are functions loaded into it. Nothing is installed globally, and nothing has to be
active.

# Installing tdd

The **tdd** tool is meant to be used together with
[tabsdata](https://github.com/tabsdata/tabsdata), checked out side by side. Clone this
repository into a folder named `tabsdata-dt`, and install **tdd** as steps 2 and 4 of
[Developing Tabsdata](https://github.com/tabsdata/tabsdata/blob/main/DEVELOPING.md#contents)
describe.

# Using tdd

List every command:

```bash
tdd --help
```

## Smoke tests

The smoke-test scripts run tabsdata end to end: a fresh virtual environment, tabsdata,
`tdkserver` and the XP test suites. The script for `km` runs on every platform, while the scripts for `eks`, `gke`
and `aks` run against a cloud Kubernetes cluster from macOS or Linux.

List the scripts, with what each one does:

```bash
tdd smoke list
```

Show how to run the `km` script:

```bash
tdd smoke run --script km --help
```

Export the scripts, to read and edit your own copies.

macOS and Linux:

```bash
tdd smoke export-scripts --dir ~/smoke
```

Windows:

```powershell
tdd smoke export-scripts --dir $HOME\smoke
```

## API description

The **tdd apidoc** command reads the public API of tabsdata statically, and writes it as one
structured JSON document. [Tabsdata DevTools: API Description](packages/tabsdata-dev-tool-apidoc/README.md) explains
the format. Run it in a virtual environment that has tabsdata installed:

```bash
tdd apidoc generate --out api.json
```

# Developing tdd

[Developing Tabsdata DevTools](DEVELOPING.md) covers the tasks, the tests and how to add a
command.

# License

Licensed under the [Apache License, Version 2.0](LICENSE).
