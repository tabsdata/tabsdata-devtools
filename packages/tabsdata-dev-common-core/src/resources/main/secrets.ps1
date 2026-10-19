{#-
  Copyright 2026 Tabsdata Inc.

  `tdd _1p fetch --platform windows`: the fetched variables as a PowerShell file, for
  a machine without 1Password (Windows) to dot-source. It travels as a file, so
  it says what it is. Values: variables, (name, value) pairs, each value already
  a PowerShell single-quoted string (secrets._ps_quote).
-#}
# Secrets exported by `tdd _1p fetch --platform windows`, for a machine without
# 1Password (Windows). Load them into a PowerShell 7 session with
#     . .\secrets.ps1
# then delete this file: it holds the values in clear.
{% for name, value in variables -%}
$env:{{ name }} = {{ value }}
{% endfor -%}
