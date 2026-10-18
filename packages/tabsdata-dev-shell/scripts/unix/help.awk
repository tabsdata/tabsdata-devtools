#
# Copyright 2026 Tabsdata Inc.
#
# The argparse-style help layout of the POSIX shell commands, run by
# common.sh's _tdd_help_text on a help declaration (its comment says the
# shape). Values: width (the terminal's columns), and bold, termcol and off,
# the escapes it paints with -- empty when stdout is not a terminal.

function paintline(l,   m, start, stop) {
    if (bold == "") return l
    if (l ~ /^[a-z][a-z0-9 \/_-]*:$/) return bold l off
    if (l ~ /^(usage|examples?):( |$)/) {
        m = index(l, ":")
        return bold substr(l, 1, m) off substr(l, m + 1)
    }
    if (match(l, /^  \* [^ ]/) || match(l, /^ {1,6}[^ ]/)) {
        start = RSTART + RLENGTH - 1
        stop = start
        while (stop < length(l) && substr(l, stop + 1, 2) != "  ") stop++
        if (stop < length(l))
            return substr(l, 1, start - 1) termcol substr(l, start, stop - start + 1) off substr(l, stop + 1)
    }
    return l
}
function paint(s,   parts, np, i, out) {
    if (bold == "") return s
    np = split(s, parts, "\n")
    out = ""
    for (i = 1; i <= np; i++) out = out (i > 1 ? "\n" : "") paintline(parts[i])
    return out
}
function sp(n) { return sprintf("%" n "s", "") }
function wrap(text, first, rest, w,   words, nw, i, line, out, ind) {
    nw = split(text, words, / +/); line = ""; out = ""; ind = first
    for (i = 1; i <= nw; i++) {
        if (words[i] == "") continue
        if (line == "") line = words[i]
        else if (length(ind) + length(line) + 1 + length(words[i]) <= w) line = line " " words[i]
        else { out = out ind line "\n"; line = words[i]; ind = rest }
    }
    return out ind line
}
function entry(term, help,   pad) { indented(2, term, help) }
# argparse indents a subcommand four and keeps the description column, so
# `positional arguments:` reads as a list under its SUBCOMMAND heading.
function entry4(term, help,   pad) { indented(4, term, help) }
# `pre` replaces the plain indent for an entry that carries a marker. It has
# to be exactly n wide, so the names stay in one column whether or not they
# are marked -- the marker sits in the margin, not in the name.
function indented(n, term, help, pre,   pad) {
    if (pre == "") pre = sp(n)
    if (help == "") { print paint(pre term); return }
    if (length(term) <= HC - n - 2) {
        pad = sprintf("%-" (HC - n) "s", term)
        print paint(wrap(help, pre pad, sp(HC), W))
    } else {
        print pre term
        print wrap(help, sp(HC), sp(HC), W)
    }
}
function newblock(type, text, gap) { btype[nb] = type; btext[nb] = text; bgap[nb] = gap; return nb++ }
function flushpara() { if (para != "") { newblock("para", para, paragap); para = "" } }
function common() {
    entry("--help, -h", "show this help message and exit")
    entry("--verbose, -v", "show debug events too")
    entry("--format {json,view}", "json is JSON Lines, one event per line (default: view)")
}
function section(b,   k) {
    print ""; print paint(btext[b])
    if (btext[b] == "options:") common()
    for (k = 0; k < nent[b]; k++) {
        if (edeep[b, k]) indented(4, eterm[b, k], ehelp[b, k], emark[b, k])
        else entry(eterm[b, k], ehelp[b, k])
    }
}
BEGIN { W = width - 2; if (W < 40) W = 40; HC = 24; n = 0; nb = 0; para = "" }
{ lines[n++] = $0 }
END {
    i = 0
    while (i < n && lines[i] != "") { print paint(lines[i]); i++ }
    cur = -1; gap = 1; hasopts = 0; lastsec = -1
    for (; i < n; i++) {
        l = lines[i]
        if (l == "") { flushpara(); gap = 1; continue }
        if (l ~ /^[a-z][a-z0-9 -]*:$/) {
            flushpara(); cur = newblock("sec", l, 1); nent[cur] = 0; lastsec = cur
            if (l == "options:") hasopts = 1
            gap = 0; continue
        }
        if (cur >= 0 && l ~ /^ /) {
            if (l ~ /^  [^ ]/ || l ~ /^    [^ ]/) {
                # `  * name` is a four-column entry whose first two columns
                # hold the marker: same name column as `    name`
                mark = (l ~ /^  \* [^ ]/) ? "  * " : ""
                deep = (mark != "" || l ~ /^    [^ ]/)
                t = substr(l, deep ? 5 : 3)
                if (match(t, /  +/)) { term = substr(t, 1, RSTART - 1); help = substr(t, RSTART + RLENGTH) }
                else { term = t; help = "" }
                k = nent[cur]++; eterm[cur, k] = term; ehelp[cur, k] = help
                edeep[cur, k] = deep; emark[cur, k] = mark
            } else if (nent[cur] > 0) {
                k = nent[cur] - 1; sub(/^ +/, "", l)
                ehelp[cur, k] = (ehelp[cur, k] == "" ? l : ehelp[cur, k] " " l)
            }
            gap = 0; continue
        }
        cur = -1
        if (l ~ /^    /) {
            flushpara()
            if (nb > 0 && btype[nb - 1] == "pre") btext[nb - 1] = btext[nb - 1] (gap ? "\n\n" : "\n") l
            else newblock("pre", l, gap)
            gap = 0; continue
        }
        sub(/^ +/, "", l); sub(/ +$/, "", l)
        if (para == "") paragap = gap
        para = (para == "" ? l : para " " l)
        gap = 0
    }
    flushpara()
    optafter = hasopts ? -2 : (lastsec >= 0 ? lastsec : (nb > 0 ? 0 : -1))
    if (optafter == -1) { print ""; print paint("options:"); common() }
    for (b = 0; b < nb; b++) {
        if (btype[b] == "sec") section(b)
        else { if (bgap[b]) print ""; print (btype[b] == "para") ? wrap(btext[b], "", "", W) : paint(btext[b]) }
        if (b == optafter) { print ""; print paint("options:"); common() }
    }
}
