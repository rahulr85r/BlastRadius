#!/usr/bin/env python3
"""BlastRadius query tool — pure stdlib, reads graph.json only.

Invoked by the /blastradius skill:

    python3 .claude/skills/blastradius/query.py                 # repo overview
    python3 .claude/skills/blastradius/query.py src/core/auth.py
    python3 .claude/skills/blastradius/query.py AuthManager     # class/function

Prints a compact "blast card": what depends on the target (direct +
transitive, by depth), what it depends on, per-symbol breakdown, and the
tier — everything Claude needs to answer "what breaks if I change this?"
without reading any dependent file.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

MAX_LIST = 25


def find_graph() -> Path:
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        cand = parent / ".claude" / "skills" / "blastradius" / "index" / "graph.json"
        if cand.exists():
            return cand
    return Path(__file__).resolve().parent / "index" / "graph.json"


def load_graph():
    path = find_graph()
    if not path.exists():
        return None, path
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), path
    except Exception:
        return None, path


def adjacency(graph):
    fwd, rdep = defaultdict(set), defaultdict(set)
    via_map = defaultdict(lambda: defaultdict(set))  # dst → name → {src}
    for e in graph["edges"]:
        fwd[e["src"]].add(e["dst"])
        rdep[e["dst"]].add(e["src"])
        for v in e["via"]:
            via_map[e["dst"]][v].add(e["src"])
    return fwd, rdep, via_map


def closure_by_depth(start, rdep):
    seen = {start: 0}
    frontier = [start]
    depth = 0
    by_depth = defaultdict(list)
    while frontier:
        depth += 1
        nxt = []
        for f in frontier:
            for parent in sorted(rdep.get(f, ())):
                if parent not in seen:
                    seen[parent] = depth
                    by_depth[depth].append(parent)
                    nxt.append(parent)
        frontier = nxt
    return by_depth


def resolve_target(arg, graph):
    """Resolve arg to ('file', rel) or ('symbol', (rel, symdict)) or (None, matches)."""
    files = graph["files"]
    if arg in files:
        return "file", arg
    # unique path suffix / substring
    suffix = [r for r in files if r.endswith(arg) or r.endswith(arg + ".py")
              or ("/" + arg) in r]
    sub = [r for r in files if arg.lower() in r.lower()]
    for cands in (suffix, sub):
        if len(cands) == 1:
            return "file", cands[0]
    # symbol name (exact, case-sensitive first, then insensitive)
    sym_hits = []
    for rel, m in sorted(files.items()):
        for s in m["symbols"]:
            if s["name"] == arg:
                sym_hits.append((rel, s))
    if not sym_hits:
        for rel, m in sorted(files.items()):
            for s in m["symbols"]:
                if s["name"].lower() == arg.lower():
                    sym_hits.append((rel, s))
    if len(sym_hits) == 1:
        return "symbol", sym_hits[0]
    if sym_hits:
        return None, [f"{rel} → {s['name']} (L{s['line']})" for rel, s in sym_hits[:10]]
    if len(sub) > 1:
        return None, sub[:10]
    return None, []


def _fmt_list(items, cap=MAX_LIST):
    shown = items[:cap]
    out = [f"  - {i}" for i in shown]
    if len(items) > cap:
        out.append(f"  … +{len(items) - cap} more")
    return out


def print_overview(graph):
    files = graph["files"]
    ranked = sorted(files.items(), key=lambda kv: (-kv[1]["score"], kv[0]))
    hotspots = [(r, m) for r, m in ranked if m["transitive"] > 0][:10]
    print(f"[blastradius: graph at commit {graph.get('built_at_commit', '?')[:12]} — "
          f"{graph['n_files']} files, {graph['n_edges']} edges]")
    print()
    print("Top hotspots (highest blast radius):")
    for rel, m in hotspots:
        syms = [s for s in m["symbols"] if s["attributed_direct"] > 0][:2]
        sym_txt = (" — via " + ", ".join(s["name"] for s in syms)) if syms else ""
        print(f"  {m['pct']:>5.1f}%  [{m['tier']:>8}]  {rel}{sym_txt}")
    if graph["hubs"]:
        print()
        print(f"Hubs ({len(graph['hubs'])}): " + ", ".join(graph["hubs"][:5])
              + (" …" if len(graph["hubs"]) > 5 else ""))
    if graph["cycles"]:
        print(f"Circular dependency groups: {len(graph['cycles'])}")
    print()
    print("Full report: blastradius.md (repo root). "
          "Query a file or class: /blastradius <target>")


def print_file_card(rel, graph, fwd, rdep, via_map):
    m = graph["files"][rel]
    hubs = set(graph["hubs"])
    print(f"💥 {rel} — {m['tier'].upper()} ({m['pct']}% of repo)"
          + ("  ⚠️ HUB" if rel in hubs else ""))
    print()
    by_depth = closure_by_depth(rel, rdep)
    direct = by_depth.get(1, [])
    total = sum(len(v) for v in by_depth.values())
    print(f"Dependents: {len(direct)} direct, {total} transitive, "
          f"max depth {max(by_depth, default=0)}")
    if direct:
        print("Direct dependents (these break first):")
        print("\n".join(_fmt_list(direct)))
    deeper = sum(len(v) for d, v in by_depth.items() if d >= 2)
    if deeper:
        print(f"  …then {deeper} more at depth ≥2")
    print()

    load_bearing = [s for s in m["symbols"] if s["attributed_direct"] > 0]
    if load_bearing:
        print("Per-symbol breakdown (where the radius actually enters):")
        for s in load_bearing[:8]:
            srcs = sorted(via_map.get(rel, {}).get(s["name"], set()))
            src_txt = ", ".join(srcs[:3]) + (" …" if len(srcs) > 3 else "")
            print(f"  - {s['name']} ({s['kind']}, L{s['line']}-{s['end_line']}): "
                  f"{s['attributed_direct']} direct → {s['transitive']} transitive "
                  f"[{s['tier']}]  ← {src_txt}")
        isolated = [s for s in m["symbols"] if s["attributed_direct"] == 0]
        if isolated and m.get("attribution_coverage", 0) >= 0.5:
            names = ", ".join(s["name"] for s in isolated[:6])
            print(f"  - lower-risk symbols (no attributed dependents): {names}"
                  + (" …" if len(isolated) > 6 else ""))
    cov = m.get("attribution_coverage", 0)
    if m["direct"] and cov < 0.5:
        print(f"  (note: only {cov:.0%} of dependents are symbol-attributable — "
              f"the rest import the whole module, so treat the file-level "
              f"radius as the real one)")
    print()
    deps = sorted(fwd.get(rel, ()))
    if deps:
        print(f"This file depends on ({len(deps)}):")
        print("\n".join(_fmt_list(deps, 10)))


def print_symbol_card(rel, sym, graph, rdep, via_map):
    files = graph["files"]
    s = next((x for x in files[rel]["symbols"] if x["name"] == sym["name"]), sym)
    print(f"💥 {s['name']} ({s['kind']}) — defined in {rel}:L{s['line']}-{s['end_line']}")
    print(f"   {s['tier'].upper()} — {s['pct']}% of repo depends on this symbol")
    print()
    srcs = sorted(via_map.get(rel, {}).get(s["name"], set()))
    if srcs:
        print(f"Direct dependents via `{s['name']}` ({len(srcs)}):")
        print("\n".join(_fmt_list(srcs)))
        print(f"Transitive: {s['transitive']} files")
    else:
        file_m = files[rel]
        if file_m["direct"]:
            print("No dependents attribute to this symbol by name — but "
                  f"{file_m['direct']} file(s) import the whole module, so "
                  "changes here may still reach them.")
        else:
            print("Nothing in the repo depends on this symbol. Low blast risk.")
    print()
    print(f"Containing file overall: {files[rel]['tier']} "
          f"({files[rel]['pct']}% of repo)")


def main():
    arg = " ".join(sys.argv[1:]).strip().strip("'\"")
    graph, path = load_graph()
    if graph is None:
        print(f"[blastradius: no graph found at {path}]")
        print("Build it first:  python3 .claude/skills/blastradius/run.py")
        return 0

    if not arg or arg.lower() in ("report", "overview", "top"):
        print_overview(graph)
        return 0

    fwd, rdep, via_map = adjacency(graph)
    kind, target = resolve_target(arg, graph)
    if kind == "file":
        print_file_card(target, graph, fwd, rdep, via_map)
    elif kind == "symbol":
        rel, sym = target
        print_symbol_card(rel, sym, graph, rdep, via_map)
    else:
        print(f"[blastradius: '{arg}' did not resolve to a unique file or symbol]")
        if target:
            print("Candidates:")
            print("\n".join(f"  - {t}" for t in target))
        else:
            print("No match in the graph. Check the spelling, or rebuild the "
                  "graph if the code is new: python3 .claude/skills/blastradius/run.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
