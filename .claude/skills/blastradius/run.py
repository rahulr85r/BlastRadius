#!/usr/bin/env python3
"""BlastRadius — one-shot pipeline: index → graph → report.

    python3 .claude/skills/blastradius/run.py            # incremental
    python3 .claude/skills/blastradius/run.py --force    # full rebuild

Writes:
    .claude/skills/blastradius/index/facts.json   (parse facts, hash-cached)
    .claude/skills/blastradius/index/graph.json   (the dependency graph)
    blastradius.md                                (the committed report, repo root)
"""

import argparse
import json
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from indexer import build_facts, find_repo_root, INDEX_REL  # noqa: E402
from graph import build_graph  # noqa: E402
from report import render  # noqa: E402
from adapters import availability_report  # noqa: E402


def main():
    p = argparse.ArgumentParser(description="BlastRadius pipeline")
    p.add_argument("--root", type=Path, default=None,
                   help="Repo root (default: detect from cwd via .git)")
    p.add_argument("--force", action="store_true",
                   help="Full re-parse (ignore the incremental hash cache)")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--include-self", action="store_true",
                   help="Include `.claude/` (only for the BlastRadius repo itself)")
    p.add_argument("--no-report", action="store_true",
                   help="Rebuild the graph but skip writing blastradius.md")
    args = p.parse_args()

    root = find_repo_root(args.root or Path.cwd())

    # Guard: if no tree-sitter grammar is installed, we can't parse anything.
    # Bail BEFORE build_facts writes, so a grammar-less machine (e.g. a dev
    # who skipped `pip install`) never overwrites a good committed report with
    # an empty one, nor poisons the incremental cache. CI, which has the
    # grammars, keeps the report correct. Silent exit 0 — never blocks a commit.
    if not any(availability_report().values()):
        print("[blastradius] no tree-sitter grammars installed — skipping "
              "(existing report left untouched). Install: pip install -r "
              ".claude/skills/blastradius/requirements.txt", file=sys.stderr)
        return

    facts = build_facts(root, force=args.force, verbose=args.verbose,
                        include_self=args.include_self)
    graph = build_graph(facts, verbose=args.verbose)

    graph_path = root / INDEX_REL / "graph.json"
    graph_path.write_text(
        json.dumps(graph, indent=1, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    if not args.no_report:
        report_path = root / "blastradius.md"
        report_path.write_text(render(graph), encoding="utf-8")
        print(f"[blastradius] report written to {report_path}", file=sys.stderr)

    ranked = sorted(graph["files"].items(), key=lambda kv: (-kv[1]["score"], kv[0]))
    top = [(rel, m) for rel, m in ranked if m["transitive"] > 0][:3]
    if top:
        print("[blastradius] top hotspots:", file=sys.stderr)
        for rel, m in top:
            print(f"    {m['pct']:>5.1f}%  {rel}", file=sys.stderr)


if __name__ == "__main__":
    main()
