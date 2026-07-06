#!/usr/bin/env python3
"""BlastRadius PR impact scorer — Phase 2. Pure stdlib, no tree-sitter.

Reads the committed baseline graph (graph.json from the PR's merge-base)
plus the PR's unified diff, and prints a markdown comment scoring the PR's
blast radius — at SYMBOL granularity:

  * Changed lines are mapped to the symbols whose spans they fall in.
  * Only the dependents of the *changed symbols* count toward the score —
    editing an isolated helper in a hotspot file scores LOW; touching the
    one load-bearing class scores HIGH. (Whole-module importers can't be
    attributed to a symbol and always count, conservatively.)
  * Changes outside any known symbol span (top-level code, config blocks)
    fall back to the file's whole-module dependents only.

Usage (in CI — see the workflow template in the README):

    git diff -U0 --no-color $BASE...$HEAD > pr.diff
    git show $BASE:.claude/skills/blastradius/index/graph.json > baseline.json
    python3 .claude/skills/blastradius/pr_impact.py \
        --graph baseline.json --diff pr.diff > comment.md

The diff's OLD-side line numbers are used, because the baseline graph's
symbol spans were computed on the old (merge-base) revision.
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

MARKER = "<!-- blastradius-pr-comment -->"
MAX_FILE_ROWS = 15

TIER_BADGE = {
    "critical": "🔴 critical",
    "high": "🟠 high",
    "medium": "🟡 medium",
    "low": "🟢 low",
    "none": "⚪ none",
}
TIER_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}

_DIFF_FILE_RE = re.compile(r"^--- (?:a/)?(.+)$")
_DIFF_NEWFILE_RE = re.compile(r"^\+\+\+ (?:b/)?(.+)$")
_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def parse_diff(text: str):
    """Return {old_path: [(start, end), ...]} of OLD-side changed ranges,
    plus the set of new-file paths (no old side to map)."""
    ranges = defaultdict(list)
    new_files = set()
    old_path = None
    new_path = None
    for line in text.splitlines():
        m = _DIFF_FILE_RE.match(line)
        if m:
            old_path = None if m.group(1) == "/dev/null" else m.group(1)
            continue
        m = _DIFF_NEWFILE_RE.match(line)
        if m:
            new_path = None if m.group(1) == "/dev/null" else m.group(1)
            if old_path is None and new_path:
                new_files.add(new_path)
            continue
        m = _HUNK_RE.match(line)
        if m and old_path:
            start = int(m.group(1))
            count = int(m.group(2)) if m.group(2) is not None else 1
            if count == 0:
                # pure insertion — attribute to the insertion point
                ranges[old_path].append((max(1, start), max(1, start) + 1))
            else:
                ranges[old_path].append((start, start + count - 1))
    return dict(ranges), new_files


def adjacency(graph):
    rdep = defaultdict(set)
    via_map = defaultdict(lambda: defaultdict(set))
    for e in graph["edges"]:
        rdep[e["dst"]].add(e["src"])
        for v in e["via"]:
            via_map[e["dst"]][v].add(e["src"])
    return rdep, via_map


def reverse_closure(start_set, rdep):
    seen = set(start_set)
    frontier = list(start_set)
    while frontier:
        nxt = []
        for f in frontier:
            for parent in rdep.get(f, ()):
                if parent not in seen:
                    seen.add(parent)
                    nxt.append(parent)
        frontier = nxt
    return seen - set(start_set)


def overlaps(span, ranges):
    lo, hi = span
    if hi <= 0:
        hi = lo
    return any(not (b < lo or a > hi) for a, b in ranges)


def analyze(graph, diff_ranges, new_files):
    files = graph["files"]
    rdep, via_map = adjacency(graph)
    n_files = max(1, graph["n_files"])

    rows = []
    impacted = set()
    changed_in_graph = []
    hubs_touched = []
    unknown = sorted(set(new_files) | {p for p in diff_ranges if p not in files})
    unknown = [p for p in unknown if p not in files]

    for path in sorted(diff_ranges):
        if path not in files:
            continue
        changed_in_graph.append(path)
        m = files[path]
        ranges = diff_ranges[path]
        whole_file_deps = set(rdep.get(path, set()))

        # Which symbols did the diff touch?
        touched = [s for s in m["symbols"]
                   if overlaps((s["line"], s.get("end_line", s["line"])), ranges)]

        # Dependents through touched symbols + unattributable (whole-module)
        # dependents, which we can never rule out.
        attr_srcs = set()
        for v, srcs in via_map.get(path, {}).items():
            if any(s["name"] == v for s in touched):
                attr_srcs |= srcs
        all_attr_srcs = set()
        for srcs in via_map.get(path, {}).values():
            all_attr_srcs |= srcs
        unattr_srcs = whole_file_deps - all_attr_srcs

        direct = attr_srcs | unattr_srcs
        # Closure climbs from the dependents of the TOUCHED symbols only —
        # never seeded with the file itself, or an edit to isolated code
        # would inherit the whole file's radius.
        closure = (direct | reverse_closure(direct, rdep)) - {path} if direct else set()
        impacted |= closure

        pct = round(100.0 * len(closure) / max(1, n_files - 1), 1)
        touched_load_bearing = [s for s in touched if s["attributed_direct"] > 0]
        if touched_load_bearing:
            tier = max((s["tier"] for s in touched_load_bearing),
                       key=lambda t: TIER_ORDER[t])
            what = ", ".join(f"`{s['name']}`" for s in touched_load_bearing[:3])
        elif touched:
            tier = "low" if not unattr_srcs else tier_from_pct(pct, len(closure))
            what = ", ".join(f"`{s['name']}`" for s in touched[:3]) + " (no attributed dependents)"
        else:
            tier = "low" if not unattr_srcs else tier_from_pct(pct, len(closure))
            what = "top-level / isolated code"
        # An edit that misses every load-bearing symbol in a hotspot file is
        # exactly the case symbol-level analysis exists for: cap it at medium
        # unless whole-module importers keep it hot.
        if not touched_load_bearing and TIER_ORDER[tier] > TIER_ORDER["medium"] \
                and len(unattr_srcs) < len(all_attr_srcs):
            tier = "medium"

        if path in set(graph.get("hubs", [])):
            hubs_touched.append(path)
        rows.append({
            "path": path, "what": what, "tier": tier,
            "direct": len(direct), "reach": len(closure), "pct": pct,
            "file_tier": m["tier"], "file_pct": m["pct"],
        })

    total_pct = round(100.0 * len(impacted) / max(1, n_files - 1), 1)
    overall = max((r["tier"] for r in rows), key=lambda t: TIER_ORDER[t]) \
        if rows else ("none" if not unknown else "low")
    return {
        "rows": sorted(rows, key=lambda r: (-TIER_ORDER[r["tier"]], -r["reach"], r["path"])),
        "impacted": len(impacted),
        "total_pct": total_pct,
        "overall": overall,
        "hubs_touched": hubs_touched,
        "unknown": unknown,
        "changed_in_graph": changed_in_graph,
    }


def tier_from_pct(pct, reach):
    if reach <= 0:
        return "none"
    if pct >= 25:
        return "critical"
    if pct >= 10:
        return "high"
    if pct >= 3:
        return "medium"
    return "low"


def render_comment(result, graph, base_sha=""):
    lines = [MARKER, ""]
    add = lines.append
    badge = TIER_BADGE[result["overall"]]
    add(f"## 💥 BlastRadius: {badge} — "
        f"**{result['total_pct']}%** of the repo depends on code changed in this PR")
    add("")
    if result["rows"]:
        add("| Changed file | What was touched | Risk | Direct dependents | Reach | % of repo |")
        add("|---|---|---|---:|---:|---:|")
        for r in result["rows"][:MAX_FILE_ROWS]:
            add(f"| `{r['path']}` | {r['what']} | {TIER_BADGE[r['tier']]} | "
                f"{r['direct']} | {r['reach']} | {r['pct']}% |")
        if len(result["rows"]) > MAX_FILE_ROWS:
            add(f"| _…{len(result['rows']) - MAX_FILE_ROWS} more files_ | | | | | |")
        add("")
    if result["hubs_touched"]:
        add("> ⚠️ **Hub touched**: "
            + ", ".join(f"`{h}`" for h in result["hubs_touched"])
            + " — these are depended on across the repo; review with extra care.")
        add("")
    if result["unknown"]:
        shown = ", ".join(f"`{u}`" for u in result["unknown"][:8])
        more = f" (+{len(result['unknown']) - 8} more)" if len(result["unknown"]) > 8 else ""
        add(f"> ℹ️ New or unindexed files (radius unknown until the next graph "
            f"build): {shown}{more}")
        add("")
    add("<sub>Risk is scored per **symbol**, not per file — touching an "
        "isolated helper in a hotspot file scores lower than touching its "
        "load-bearing class. Baseline graph: "
        f"commit `{(base_sha or graph.get('built_at_commit', ''))[:12]}` · "
        "static import/type analysis (runtime wiring not visible) · "
        "[BlastRadius](https://github.com/rahulr85r/blastradius)</sub>")
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description="BlastRadius PR impact scorer")
    p.add_argument("--graph", type=Path, required=True,
                   help="Baseline graph.json (from the PR's merge-base)")
    p.add_argument("--diff", type=Path, default=None,
                   help="Unified diff file (git diff -U0 base...head); '-' or omit for stdin")
    p.add_argument("--base-sha", default="", help="Merge-base SHA for the footer")
    args = p.parse_args()

    try:
        with open(args.graph, encoding="utf-8") as f:
            graph = json.load(f)
    except Exception as exc:
        print(MARKER)
        print(f"## 💥 BlastRadius: no baseline graph available ({exc.__class__.__name__})")
        print("")
        print("Run the report workflow on the base branch first "
              "(`python3 .claude/skills/blastradius/run.py`) so PRs have a "
              "committed graph to score against.")
        return 0

    if args.diff and str(args.diff) != "-":
        diff_text = args.diff.read_text(encoding="utf-8", errors="replace")
    else:
        diff_text = sys.stdin.read()

    diff_ranges, new_files = parse_diff(diff_text)
    result = analyze(graph, diff_ranges, new_files)
    print(render_comment(result, graph, args.base_sha))
    return 0


if __name__ == "__main__":
    sys.exit(main())
