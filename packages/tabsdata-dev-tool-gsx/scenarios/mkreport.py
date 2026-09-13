#
# Copyright 2026 Tabsdata Inc.
#

"""Build docs/gsx-scenario-report.md from the batches' report_*.json."""

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
OUT = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "report.md"

entries = []
for name in ("scen_ab", "scen_c", "scen_def"):
    p = ROOT / f"report_{name}.json"
    if p.is_file():
        entries.extend(json.loads(p.read_text()))

groups = {
    "A": "Baseline collaboration",
    "B": "Cascades: the trunk moves, parents grow, several users",
    "C": "Moves: local until published, then published",
    "D": "The guard",
    "E": "Landed history",
    "F": "Edges and the create path",
}

lines = []
total = len(entries)
passed = sum(1 for e in entries if e["result"] == "PASS")
lines.append(f"**{passed} of {total} scenarios pass.**\n")
lines.append("| # | scenario | result | time |")
lines.append("|---|---|---|---|")
for e in entries:
    tag, _, title = e["name"].partition(": ")
    lines.append(f"| {tag} | {title} | **{e['result']}** | {e['secs']}s |")
lines.append("")

current = None
for e in entries:
    tag, _, title = e["name"].partition(": ")
    g = tag[0]
    if g != current:
        current = g
        lines.append(f"\n### {g}. {groups.get(g, g)}\n")
    lines.append(f"**{tag} — {title}** · {e['result']}\n")
    for step in e.get("steps") or []:
        lines.append(f"- {step}")
    if e["result"] != "PASS":
        detail = (e.get("detail") or "").strip().splitlines()
        lines.append("")
        lines.append("```")
        lines.extend(line[:160] for line in detail[:12])
        lines.append("```")
    lines.append("")

OUT.write_text("\n".join(lines) + "\n")
print(f"wrote {OUT}: {passed}/{total}")
