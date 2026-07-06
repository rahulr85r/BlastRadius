#!/usr/bin/env python3
"""BlastRadius graph builder — phase 2 of the pipeline. Pure stdlib.

Consumes facts.json (from indexer.py) and produces graph.json: a precise,
bidirectional dependency graph with per-FILE and per-SYMBOL blast metrics.

Design principles (the "no false edges" contract):

  * Path-aware import resolution per language — never basename guessing.
    An import that cannot be resolved unambiguously creates NO edge; it is
    counted in the resolution stats instead. Precision over recall: a graph
    that is the product cannot afford edges that are lies.

  * Symbol-level attribution. Every edge records the symbol names it enters
    the target file through (`via`) — the imported names, the referenced
    types. Blast radius is then computed per symbol, not just per file:
    a file whose entire radius flows through one class is only critical
    where that class is; the rest of the file is isolated, low-risk code.
    Edges that import a whole module (no names) are "unattributed" and
    conservatively count against every symbol in the target.

  * Depth-decayed scoring. A dependent 4 hops away matters less than a
    direct importer: score = Σ dependents_at_depth_d × DECAY^(d-1).

Resolution rules per language:
  python  — absolute imports matched as path suffixes of module paths
            (a.b.c → **/a/b/c.py | **/a/b/c/__init__.py, longest match
            first, ties broken by shared path prefix with the importer,
            unresolvable ties skipped); relative imports resolved exactly
            against the importer's package; `from pkg import name` also
            tries pkg/name.py (submodule imports).
  js      — relative specifiers resolved exactly with extension/index
            candidates; bare specifiers = external (no edge, ever).
  jvm     — file's declared `package` + top-level type names form FQNs;
            imports match (package, ClassName) exactly; wildcard imports
            resolve only through type references actually used; same-package
            type references link without imports (Java visibility rules).
  swift   — no file-level imports in-module; type references resolve only
            when the type is defined in exactly one file repo-wide.
"""

import argparse
import json
import posixpath
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Top-level module names that are never repo files. Used to reject the
# classic Python false edge: `import json` (stdlib) matching a deep local
# `.../json.py`. sys.stdlib_module_names exists on 3.10+; the fallback keeps
# the guard meaningful on older interpreters. Third-party top-level names
# aren't enumerable, but single-segment imports also require an *exact
# top-level* file match (see resolve_python_import), which covers the rest.
_STDLIB_FALLBACK = frozenset("""
abc argparse ast asyncio base64 bisect builtins calendar collections
concurrent configparser contextlib copy csv ctypes datetime decimal difflib
dis email enum errno functools gc getpass glob gzip hashlib heapq hmac html
http importlib inspect io ipaddress itertools json logging math mimetypes
multiprocessing operator os pathlib pickle platform pprint queue random re
select shlex shutil signal socket sqlite3 ssl stat string struct subprocess
sys tarfile tempfile textwrap threading time timeit token tokenize traceback
types typing unicodedata unittest urllib uuid warnings weakref xml zipfile zlib
""".split())
PY_STDLIB = frozenset(getattr(sys, "stdlib_module_names", ())) | _STDLIB_FALLBACK

# Swift has no import paths to disambiguate types, so a repo-unique LOCAL type
# whose name collides with a ubiquitous framework type (SwiftUI.Button,
# Foundation.Notification, …) would otherwise collect every use of that name
# as a false dependent. When a referenced name is one of these, we can't tell
# the local type from the framework one, so we treat it as ambiguous and
# create no edge — same "under-claim rather than lie" contract as everywhere
# else. Curated to high-frequency, high-collision framework type names.
# Deliberately excludes generic English words that are commonly *legitimate*
# unique local types (Event, Name, Configuration, Type, Model, Item, …) —
# suppressing those would hide real hotspots. Only names with a genuinely
# ubiquitous framework type competing for the reference are listed.
SWIFT_FRAMEWORK_TYPES = frozenset("""
View Button Text Image EmptyView AnyView Group Section List Form
VStack HStack ZStack LazyVStack LazyHStack Grid Spacer Divider
ForEach ScrollView NavigationView NavigationStack NavigationLink
Toggle Picker Slider Stepper TextField SecureField TextEditor Label Menu
Link ProgressView Gauge DisclosureGroup GroupBox TabView Table
Color Font Gradient LinearGradient Angle Animation Transition
Circle Rectangle RoundedRectangle Capsule Ellipse Path Shape Edge
Alignment GeometryReader GeometryProxy ViewBuilder ViewModifier
PreferenceKey Namespace Environment EnvironmentObject EnvironmentValues
State StateObject ObservedObject Published Binding FetchRequest
Alert ActionSheet Toolbar ToolbarItem
Notification Data Date URL URLRequest URLResponse UUID Task Operation
Timer Bundle Locale Calendar TimeZone Measurement Progress Result Error
""".split())

TOOL_VERSION = "0.1.0"
GRAPH_VERSION = 1

DECAY = 0.6                 # per-hop score decay
HUB_FRACTION = 0.10         # depended on by >10% of files (min 5) → hub
MAX_SYMBOLS_PER_FILE = 200  # span map cap in graph.json
MAX_CYCLES = 25

# pct-of-repo thresholds → tier
TIERS = (("critical", 25.0), ("high", 10.0), ("medium", 3.0), ("low", 0.0))

# Symbol kinds that can carry attributed dependencies (edges arrive "via"
# these). Methods/properties are excluded — their names are too generic to
# attribute reliably; a change inside a method still maps to its enclosing
# class through the class's line span.
ATTRIBUTABLE_KINDS = {
    "class", "interface", "struct", "enum", "record", "annotation",
    "protocol", "object", "actor", "function", "def",
}
TYPE_KINDS = {"class", "interface", "struct", "enum", "record",
              "annotation", "protocol", "object", "actor"}

_JS_EXTS = (".js", ".jsx", ".mjs", ".cjs")


def tier_of(pct: float, transitive: int) -> str:
    if transitive <= 0:
        return "none"
    for name, threshold in TIERS:
        if pct >= threshold:
            return name
    return "low"


# ----------------------------------------------------------------------
# Edge collection
# ----------------------------------------------------------------------

class EdgeSet:
    """Accumulates deduplicated directed edges src → dst with via-symbol
    labels and a confidence level ('high' = resolved import / same-package
    type, 'medium' = uniqueness-gated type reference)."""

    def __init__(self):
        self.edges = {}

    def add(self, src, dst, kind, via=None, confidence="high"):
        if src == dst or dst is None:
            return
        e = self.edges.setdefault((src, dst), {
            "kinds": set(), "via": set(), "confidence": confidence,
        })
        e["kinds"].add(kind)
        if via:
            e["via"].update([via] if isinstance(via, str) else via)
        if confidence == "high":
            e["confidence"] = "high"

    def to_list(self):
        out = []
        for (src, dst), e in sorted(self.edges.items()):
            out.append({
                "src": src, "dst": dst,
                "kinds": sorted(e["kinds"]),
                "via": sorted(v for v in e["via"] if v and v != "*"),
                "confidence": e["confidence"],
            })
        return out


# ----------------------------------------------------------------------
# Python resolution
# ----------------------------------------------------------------------

def _py_module_parts(rel):
    parts = rel[:-len(".py")].split("/")
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return tuple(parts)


def build_python_resolver(files):
    """Build (match_suffix, top_level).

    match_suffix — files whose module path *ends with* a multi-segment path.
    top_level    — {name: [rel]} for files importable as a bare top-level
                   module (module path is exactly one segment). Single-segment
                   imports resolve ONLY through this exact map, never by deep
                   suffix, so `import json` can't match `a/b/json.py`.
    """
    by_last = defaultdict(list)
    top_level = defaultdict(list)
    for rel, entry in files.items():
        if entry["lang"] != "python":
            continue
        parts = _py_module_parts(rel)
        if parts:
            by_last[parts[-1]].append((parts, rel))
            if len(parts) == 1:
                top_level[parts[0]].append(rel)

    def match_suffix(parts, importer_rel):
        """Files whose module path ends with `parts`. Unique → rel;
        ambiguous → tie-break by longest shared dir prefix with importer;
        still tied → None (ambiguous, no edge)."""
        tp = tuple(parts)
        cands = [rel for (mp, rel) in by_last.get(tp[-1], ())
                 if len(mp) >= len(tp) and mp[-len(tp):] == tp]
        if not cands:
            return None, "none"
        if len(cands) == 1:
            return cands[0], "ok"
        imp_dirs = importer_rel.split("/")[:-1]

        def shared(rel):
            dirs = rel.split("/")[:-1]
            n = 0
            for a, b in zip(imp_dirs, dirs):
                if a != b:
                    break
                n += 1
            return n

        scored = sorted(((shared(r), r) for r in cands), reverse=True)
        if len(scored) > 1 and scored[0][0] == scored[1][0]:
            return None, "ambiguous"
        return scored[0][1], "ok"

    return match_suffix, dict(top_level)


def resolve_python_import(imp, importer_rel, fileset, match_suffix, top_level,
                          edges, stats):
    path, names = imp["path"], imp.get("names", [])
    real_names = [n for n in names if n != "*"]

    if path.startswith("."):
        # Relative: dots climb from the importer's package
        dots = len(path) - len(path.lstrip("."))
        rest = [p for p in path.lstrip(".").split(".") if p]
        base = importer_rel.split("/")[:-1]
        if dots > 1:
            base = base[:len(base) - (dots - 1)] if dots - 1 <= len(base) else []
        target_dir = base + rest
        resolved_any = False
        # `from .pkg import name` — name may itself be a module
        for name in real_names:
            for cand in ("/".join(target_dir + [name]) + ".py",
                         "/".join(target_dir + [name]) + "/__init__.py"):
                if cand in fileset:
                    edges.add(importer_rel, cand, "import", via=name)
                    stats["resolved"] += 1
                    resolved_any = True
                    break
        for cand in ("/".join(target_dir) + ".py" if target_dir else None,
                     "/".join(target_dir + ["__init__.py"]) if target_dir else None):
            if cand and cand in fileset:
                edges.add(importer_rel, cand, "import", via=real_names)
                stats["resolved"] += 1
                resolved_any = True
                break
        if not resolved_any:
            stats["unresolved"] += 1
        return

    parts = path.split(".")

    # Stdlib guard — but ONLY for a plain `import X` / `import X.Y` (no names
    # pulled out). `from types import Insight` names a symbol stdlib `types`
    # doesn't have, so it's a local `types.py`; those go through structural
    # resolution below (sibling / exact-top-level), which is self-validating.
    if not real_names and parts and parts[0] in PY_STDLIB:
        stats["external"] += 1
        return

    def _single_segment(name, via):
        """Resolve a bare module name to (1) a sibling in the importer's own
        directory — script-style / path-rooted layouts, the common case for
        `from AlgorithmImports import *` — then (2) an exact top-level module.
        Never a deep suffix, so `import json` can't reach `a/b/json.py`."""
        importer_dir = importer_rel.rsplit("/", 1)[0] if "/" in importer_rel else ""
        prefix = f"{importer_dir}/" if importer_dir else ""
        for cand in (f"{prefix}{name}.py", f"{prefix}{name}/__init__.py"):
            if cand in fileset and cand != importer_rel:
                edges.add(importer_rel, cand, "import", via=via)
                stats["resolved"] += 1
                return "ok"
        cands = [r for r in top_level.get(name, ()) if r in fileset]
        if len(cands) == 1:
            edges.add(importer_rel, cands[0], "import", via=via)
            stats["resolved"] += 1
            return "ok"
        if len(cands) > 1:
            stats["ambiguous"] += 1
            return "ambiguous"
        return "none"

    # `from a.b import c` — c may itself be the module a/b/c.py (always
    # multi-segment here, so deep suffix matching is safe).
    for name in real_names:
        rel, status = match_suffix(parts + [name], importer_rel)
        if rel and rel in fileset:
            edges.add(importer_rel, rel, "import", via=name)
            stats["resolved"] += 1

    # Longest-prefix match on the module path itself, trimming from the right
    # (trailing segments may be symbols, not modules). A single remaining
    # segment resolves only to a sibling or an exact top-level module — never
    # a deep suffix — or unrelated imports would edge to same-named files.
    for k in range(len(parts), 0, -1):
        seg = parts[:k]
        via = real_names if k == len(parts) else []
        if k == 1:
            status = _single_segment(seg[0], via)
            if status in ("ok", "ambiguous"):
                return
            break  # no sibling / top-level match → external
        rel, status = match_suffix(seg, importer_rel)
        if status == "ambiguous":
            stats["ambiguous"] += 1
            return
        if rel and rel in fileset:
            edges.add(importer_rel, rel, "import", via=via)
            stats["resolved"] += 1
            return
    stats["external"] += 1


# ----------------------------------------------------------------------
# JavaScript resolution
# ----------------------------------------------------------------------

def resolve_js_import(imp, importer_rel, fileset, edges, stats):
    spec, names = imp["path"], imp.get("names", [])
    if not spec.startswith("."):
        stats["external"] += 1
        return
    base = posixpath.normpath(posixpath.join(posixpath.dirname(importer_rel), spec))
    candidates = [base]
    candidates += [base + ext for ext in _JS_EXTS]
    candidates += [posixpath.join(base, "index" + ext) for ext in _JS_EXTS]
    for cand in candidates:
        if cand in fileset:
            edges.add(importer_rel, cand, "import", via=[n for n in names if n != "*"])
            stats["resolved"] += 1
            return
    stats["unresolved"] += 1


# ----------------------------------------------------------------------
# JVM resolution
# ----------------------------------------------------------------------

def build_jvm_index(files):
    """(package, TypeName) → [rel]; also per-file own type names."""
    class_index = defaultdict(list)
    own_types = {}
    for rel, entry in sorted(files.items()):
        if entry["lang"] != "jvm":
            continue
        pkg = entry.get("package", "")
        names = {s["name"] for s in entry["symbols"] if s["kind"] in TYPE_KINDS}
        own_types[rel] = names
        for name in sorted(names):
            class_index[(pkg, name)].append(rel)
    return class_index, own_types


def resolve_jvm_file(rel, entry, class_index, own_types, edges, stats):
    pkg = entry.get("package", "")
    type_refs = set(entry.get("type_refs", []))
    own = own_types.get(rel, set())
    wildcard_pkgs = []

    for imp in entry.get("imports", []):
        path = imp["path"]
        if path.endswith(".*"):
            wildcard_pkgs.append(path[:-2])
            continue
        parts = path.split(".")
        resolved = False
        # com.foo.Bar → (com.foo, Bar); static imports may carry a member:
        # com.foo.Bar.baz → retry as (com.foo, Bar)
        for cut in (1, 2):
            if len(parts) <= cut - 1:
                break
            cand_pkg = ".".join(parts[:-cut])
            cand_cls = parts[-cut]
            targets = class_index.get((cand_pkg, cand_cls), [])
            if len(targets) == 1:
                edges.add(rel, targets[0], "import", via=cand_cls)
                stats["resolved"] += 1
                resolved = True
                break
            if len(targets) > 1:
                stats["ambiguous"] += 1
                resolved = True
                break
        if not resolved:
            stats["external"] += 1

    # Wildcard imports and same-package visibility resolve through the
    # type names the file actually uses.
    for t in sorted(type_refs - own):
        for cand_pkg in [pkg] + wildcard_pkgs:
            targets = class_index.get((cand_pkg, t), [])
            if len(targets) == 1 and targets[0] != rel:
                kind = "same-package" if cand_pkg == pkg else "wildcard-import"
                edges.add(rel, targets[0], kind, via=t)
                stats["ref_edges"] += 1
                break


# ----------------------------------------------------------------------
# Swift resolution
# ----------------------------------------------------------------------

def resolve_swift(files, edges, stats):
    type_index = defaultdict(set)
    for rel, entry in files.items():
        if entry["lang"] != "swift":
            continue
        for s in entry["symbols"]:
            if s["kind"] in TYPE_KINDS:  # extensions excluded on purpose
                type_index[s["name"]].add(rel)

    for rel, entry in sorted(files.items()):
        if entry["lang"] != "swift":
            continue
        # `extension User` defines a symbol named User in THIS file, but the
        # type itself lives elsewhere — extensions must not mask the edge to
        # the real definition.
        own = {s["name"] for s in entry["symbols"] if s["kind"] != "extension"}
        for t in sorted(set(entry.get("type_refs", [])) - own):
            # A local type shadowing a ubiquitous framework type — can't tell
            # this reference from the framework one, so create no edge.
            if t in SWIFT_FRAMEWORK_TYPES:
                stats["framework_shadowed"] += 1
                continue
            targets = type_index.get(t, set())
            if len(targets) == 1:
                target = next(iter(targets))
                if target != rel:
                    edges.add(rel, target, "type-ref", via=t, confidence="medium")
                    stats["ref_edges"] += 1
            elif len(targets) > 1:
                stats["ambiguous"] += 1


# ----------------------------------------------------------------------
# Metrics
# ----------------------------------------------------------------------

def reverse_closure(start_set, rdep):
    """BFS over reverse edges from a set of files. Returns {file: depth},
    excluding the start files themselves."""
    seen = {f: 0 for f in start_set}
    frontier = sorted(start_set)
    depth = 0
    while frontier:
        depth += 1
        nxt = []
        for f in frontier:
            for parent in sorted(rdep.get(f, ())):
                if parent not in seen:
                    seen[parent] = depth
                    nxt.append(parent)
        frontier = nxt
    for f in start_set:
        seen.pop(f, None)
    return seen


def radius_metrics(closure, n_files):
    transitive = len(closure)
    pct = round(100.0 * transitive / max(1, n_files - 1), 1)
    depth = max(closure.values(), default=0)
    score = round(sum(DECAY ** (d - 1) for d in closure.values()), 2)
    return transitive, pct, depth, score


def strongly_connected(adj):
    """Iterative Tarjan. Returns SCCs with ≥2 nodes (dependency cycles)."""
    index_counter = [0]
    index, lowlink = {}, {}
    stack, on_stack = [], set()
    result = []

    for root in sorted(adj):
        if root in index:
            continue
        work = [(root, 0)]
        while work:
            v, pi = work[-1]
            if pi == 0:
                index[v] = lowlink[v] = index_counter[0]
                index_counter[0] += 1
                stack.append(v)
                on_stack.add(v)
            advanced = False
            neighbors = sorted(adj.get(v, ()))
            for i in range(pi, len(neighbors)):
                w = neighbors[i]
                if w not in index:
                    work[-1] = (v, i + 1)
                    work.append((w, 0))
                    advanced = True
                    break
                if w in on_stack:
                    lowlink[v] = min(lowlink[v], index[w])
            if advanced:
                continue
            if lowlink[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                if len(comp) > 1:
                    result.append(sorted(comp))
            work.pop()
            if work:
                u, _ = work[-1]
                lowlink[u] = min(lowlink[u], lowlink[v])
    return sorted(result)


# ----------------------------------------------------------------------
# Build
# ----------------------------------------------------------------------

def build_graph(facts: dict, verbose: bool = False) -> dict:
    files = facts.get("files", {})
    fileset = set(files)
    n_files = len(files)
    edges = EdgeSet()
    stats = Counter()

    match_suffix, py_top_level = build_python_resolver(files)
    class_index, own_types = build_jvm_index(files)

    for rel in sorted(files):
        entry = files[rel]
        lang = entry["lang"]
        stats["imports_total"] += len(entry.get("imports", []))
        if lang == "python":
            for imp in entry.get("imports", []):
                resolve_python_import(imp, rel, fileset, match_suffix,
                                      py_top_level, edges, stats)
        elif lang == "javascript":
            for imp in entry.get("imports", []):
                resolve_js_import(imp, rel, fileset, edges, stats)
        elif lang == "jvm":
            resolve_jvm_file(rel, entry, class_index, own_types, edges, stats)
        elif lang == "swift":
            stats["external"] += len(entry.get("imports", []))  # module imports
    resolve_swift(files, edges, stats)

    edge_list = edges.to_list()

    # Adjacency
    fwd = defaultdict(set)   # A → things A depends on
    rdep = defaultdict(set)  # B → things depending on B
    for e in edge_list:
        fwd[e["src"]].add(e["dst"])
        rdep[e["dst"]].add(e["src"])

    # Symbol attribution: incoming edges land on named symbols (via) or,
    # lacking names, on the file as a whole ("unattributed" — counts
    # against every symbol conservatively).
    attributed = defaultdict(lambda: defaultdict(set))  # dst → name → {src}
    unattributed = defaultdict(set)                     # dst → {src}
    attributable_names = {
        rel: {s["name"] for s in files[rel]["symbols"]
              if s["kind"] in ATTRIBUTABLE_KINDS}
        for rel in files
    }
    for e in edge_list:
        dst = e["dst"]
        hits = [v for v in e["via"] if v in attributable_names.get(dst, ())]
        if hits:
            for name in hits:
                attributed[dst][name].add(e["src"])
        else:
            unattributed[dst].add(e["src"])

    hub_threshold = max(5, int(HUB_FRACTION * n_files))
    hubs = sorted(rel for rel in files if len(rdep.get(rel, ())) >= hub_threshold)

    out_files = {}
    n_attr_edges = sum(1 for e in edge_list
                       if any(v in attributable_names.get(e["dst"], ()) for v in e["via"]))
    for rel in sorted(files):
        entry = files[rel]
        direct = sorted(rdep.get(rel, ()))
        closure = reverse_closure({rel}, rdep)
        transitive, pct, depth, score = radius_metrics(closure, n_files)

        # Per-symbol metrics. A symbol's dependents = edges arriving via its
        # name + all unattributed (whole-file) dependents.
        whole_file_deps = unattributed.get(rel, set())
        sym_out = []
        for s in entry["symbols"][:MAX_SYMBOLS_PER_FILE]:
            if s["kind"] not in ATTRIBUTABLE_KINDS:
                continue
            via_deps = attributed.get(rel, {}).get(s["name"], set())
            sym_direct = via_deps | whole_file_deps
            if sym_direct:
                sym_closure = reverse_closure(sym_direct | {rel}, rdep)
                # dependents themselves are part of the symbol's radius
                sym_trans = len(set(sym_closure) | sym_direct)
                sym_pct = round(100.0 * sym_trans / max(1, n_files - 1), 1)
            else:
                sym_trans, sym_pct = 0, 0.0
            sym_out.append({
                "name": s["name"], "kind": s["kind"],
                "line": s["line"], "end_line": s.get("end_line", 0),
                "direct": len(sym_direct),
                "attributed_direct": len(via_deps),
                "transitive": sym_trans,
                "pct": sym_pct,
                "tier": tier_of(sym_pct, sym_trans),
            })
        sym_out.sort(key=lambda s: (-s["attributed_direct"], -s["direct"], s["line"]))

        n_in = len(direct)
        n_attr_in = len(set().union(*attributed.get(rel, {}).values())) \
            if attributed.get(rel) else 0
        out_files[rel] = {
            "lang": entry["lang"],
            "package": entry.get("package", ""),
            "out": len(fwd.get(rel, ())),
            "direct": n_in,
            "transitive": transitive,
            "pct": pct,
            "depth": depth,
            "score": score,
            "tier": tier_of(pct, transitive),
            "attribution_coverage": round(n_attr_in / n_in, 2) if n_in else 0.0,
            "symbols": sym_out,
        }

    graph = {
        "version": GRAPH_VERSION,
        "tool_version": TOOL_VERSION,
        "built_at_commit": facts.get("built_at_commit", ""),
        "n_files": n_files,
        "n_edges": len(edge_list),
        "resolution": {
            "imports_total": stats["imports_total"],
            "resolved": stats["resolved"],
            "external": stats["external"],
            "unresolved": stats["unresolved"],
            "ambiguous_skipped": stats["ambiguous"],
            "framework_shadowed": stats["framework_shadowed"],
            "type_ref_edges": stats["ref_edges"],
            "attributed_edges": n_attr_edges,
        },
        "hub_threshold": hub_threshold,
        "hubs": hubs,
        "cycles": strongly_connected(fwd)[:MAX_CYCLES],
        "files": out_files,
        "edges": edge_list,
    }
    if verbose:
        r = graph["resolution"]
        print(f"[blastradius] {n_files} files, {len(edge_list)} edges "
              f"(resolved {r['resolved']}, type-ref {r['type_ref_edges']}, "
              f"external {r['external']}, unresolved {r['unresolved']}, "
              f"ambiguous skipped {r['ambiguous_skipped']}, "
              f"framework-shadowed {r['framework_shadowed']})", file=sys.stderr)
    return graph


def main():
    p = argparse.ArgumentParser(description="BlastRadius graph builder")
    p.add_argument("--facts", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()
    with open(args.facts, encoding="utf-8") as f:
        facts = json.load(f)
    graph = build_graph(facts, verbose=args.verbose)
    args.out.write_text(
        json.dumps(graph, indent=1, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
