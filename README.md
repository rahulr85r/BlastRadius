# 💥 BlastRadius

**"What breaks if I change this?" — answered for every file *and every class/function* in your repo, in a markdown file anyone can read.**

BlastRadius statically analyzes your codebase (tree-sitter symbol extraction + a precision-first, bidirectional dependency graph) and:

1. **Phase 1 — the committed report.** Drops a deterministic `blastradius.md` at your repo root: risk-tiered hotspots, the exact classes/functions the risk flows through, hubs, circular dependencies, and a dependency map. Committed to the repo, so the whole team — and any coding agent reading your repo — sees it without running anything.
2. **Phase 2 — the PR comment.** A GitHub Action that scores every pull request: *"31% of the repo depends on code changed in this PR"* — scored **per symbol**, so editing an isolated helper in a hotspot file scores low, while touching the load-bearing class scores high.
3. **`/blastradius` in Claude Code.** Ask *"what breaks if I change `AuthManager`?"* and get an instant blast card from the pre-built graph — zero file scanning, zero LLM analysis.

## Philosophy — simplicity is the product

- **No LLM in the analysis.** Everything is deterministic static analysis. Same code in → same report out.
- **No MCP, no server, no daemon.** The interface is a markdown file and a query script. Humans read it on GitHub; agents read it as cheap context.
- **No network at analysis time.** tree-sitter parses locally; everything downstream is pure Python stdlib.
- **No false edges.** An import or type reference that can't be resolved *unambiguously* to a repo file creates **no edge** — it's counted in the report's resolution stats instead. The graph under-claims rather than lies.

## Quick start

```bash
# 1. Copy the skill into your repo
cp -r .claude/skills/blastradius  YOUR_REPO/.claude/skills/blastradius

# 2. Install the tree-sitter grammars (index time only)
pip install -r YOUR_REPO/.claude/skills/blastradius/requirements.txt

# 3. Build the graph and the report
cd YOUR_REPO
python3 .claude/skills/blastradius/run.py

# → blastradius.md at your repo root
# → .claude/skills/blastradius/index/graph.json (the machine-readable graph)
```

Commit `blastradius.md` and the `index/` directory — the committed graph is what the PR bot scores against and what `/blastradius` queries.

## Silent mode — runs automatically on every commit (recommended)

You don't have to remember to run anything. Install the git hook once and `blastradius.md` regenerates itself, silently, as part of **every commit** — nobody has to know the tool is even there.

```bash
# one-time, per clone
sh .claude/skills/blastradius/install.sh
```

From then on, every `git commit` that touches code silently rebuilds the report (incrementally — typically well under a second) and includes the refreshed `blastradius.md` in that same commit. No commands, no prompts, no output.

It is deliberately **best-effort and never intrusive**:

- It **never blocks or slows a commit** meaningfully — docs-only commits skip instantly, and code commits rebuild only what changed.
- If a developer hasn't run `pip install` (no tree-sitter grammars) or has no Python, the hook **silently skips** and leaves the committed report untouched — it never overwrites a good report with an empty one. The CI report workflow (below) regenerates the authoritative version on push, so the repo's report is always correct regardless of who committed.
- It only ever stages BlastRadius's own outputs (`blastradius.md` + `index/`), nothing the developer didn't choose to commit.

> Git stores hooks in `.git/hooks`, which isn't versioned — that's git's security model, so the one-time `install.sh` per clone is unavoidable. Add that line to your repo's existing setup script or `Makefile` and new clones get it with zero extra thought. If you already use a pre-commit framework (husky, pre-commit), `install.sh` detects it and prints the one line to chain instead of clobbering.

### In Claude Code

```
/blastradius                     # repo overview — hotspots, hubs, cycles
/blastradius src/core/auth.py    # blast card for a file
/blastradius AuthManager         # blast card for a class or function
```

## Symbol-level risk — the part that matters

Most impact tools stop at file granularity. BlastRadius records **which symbol every dependency edge enters through** (the imported name, the referenced type). That means:

- A file with 40 dependents where all 40 import `AuthManager` is critical **at `AuthManager`** — and low-risk everywhere else in the file.
- The report's *Concentrated risk* section names these files explicitly: *"only changes touching `AuthManager` (L14–210) are critical; the rest of this file is lower-risk."*
- The PR bot maps your diff's changed lines to symbol spans: touch the isolated helper → 🟢 low; touch the load-bearing class → 🔴 critical.
- Whole-module imports (`import utils`) can't be attributed to a symbol, so they conservatively count against every symbol in the file — the tool never *under*-reports risk to look clever. Each file's attribution coverage is shown so you know how much signal is symbol-precise.

## What the report contains

| Section | Answers |
|---|---|
| Top hotspots | Which files can break the most of the repo, and through which symbols |
| Concentrated risk | Files where one class/function carries the radius — edit the rest freely |
| Most depended-on symbols | The repo's actual load-bearing classes/functions, ranked |
| Hubs | Utility modules ≥10% of the repo leans on |
| Circular dependencies | Cycles that make blast radii contagious |
| Dependency map | Mermaid diagram of the hotspot subgraph (renders on GitHub) |
| Resolution stats | How many imports resolved / were external / were *skipped rather than guessed* |

## Phase 2 — PR impact comments

Copy both workflow templates into your repo's `.github/workflows/`:

**Report refresh** (keeps the committed graph current; runs on pushes to main, opens a mechanical PR — your feature diffs never churn):

```yaml
# .github/workflows/blastradius-report.yml — copy from this repo,
# and REMOVE the --include-self flag (that's only for the BlastRadius
# source repo itself).
```

**PR scoring** (pure stdlib, no dependencies to install — it reads the committed baseline graph from the merge-base):

```yaml
# .github/workflows/blastradius-pr.yml — copy verbatim from this repo.
```

Every PR then gets a sticky comment like:

> ## 💥 BlastRadius: 🟠 high — **17.3%** of the repo depends on code changed in this PR
>
> | Changed file | What was touched | Risk | Direct dependents | Reach | % of repo |
> |---|---|---|---:|---:|---:|
> | `src/core/auth.py` | `AuthManager` | 🟠 high | 23 | 71 | 17.3% |
> | `src/core/auth.py` | `format_debug` (no attributed dependents) | 🟢 low | 0 | 0 | 0.0% |
>
> ⚠️ **Hub touched**: `src/db/connection.py`

## Supported languages

| Language | Extensions | Edge sources |
|---|---|---|
| Python | `.py` | absolute + relative imports (path-resolved), `from x import name` (symbol-attributed) |
| JavaScript | `.js` `.jsx` `.mjs` `.cjs` | ES imports/re-exports, `require()`, dynamic `import()` — relative paths resolved exactly; named imports attributed |
| Java / Kotlin | `.java` `.kt` `.kts` | declared `package` + imports resolved to (package, ClassName); wildcard imports and same-package references resolved through the types actually used |
| Swift | `.swift` | type references, gated on repo-wide uniqueness; extensions link to the extended type |

Adding a language = one adapter file (`adapters/<lang>.py`, ~100 lines) + a resolver rule. TypeScript is the highest-impact next adapter.

## How the graph is built (the algorithm, honestly)

1. **Extract** (tree-sitter, index time): per file — symbols with kinds and line spans, structured imports with imported names, referenced type names, declared package.
2. **Resolve** (pure stdlib): language-aware rules turn imports/type-refs into edges. Longest-suffix module matching with importer-proximity tie-breaks (Python), exact relative-path resolution (JS), package-qualified type lookup (JVM), uniqueness-gated type references (Swift). **Ambiguity → no edge + a counter**, never a guess.
3. **Attribute**: each edge records its `via` symbols → per-symbol dependent sets.
4. **Score**: reverse BFS per file and per symbol. `score = Σ 0.6^(depth−1)` over transitive dependents — a direct importer outweighs one four hops away. Tiers: 🔴 ≥25% of repo · 🟠 ≥10% · 🟡 ≥3% · 🟢 <3%.
5. **Detect**: hubs (≥10% direct dependents) and dependency cycles (Tarjan SCC).

### Known limitations

- **Static analysis only.** Dependency injection, reflection, event buses, and network calls between services are invisible. The radius is a *floor*, not a ceiling — the report says so on every artifact.
- Swift resolution is uniqueness-gated: repos with many same-named types will show fewer Swift edges (counted, not hidden).
- Dynamic `import()`/`require()` with non-literal arguments can't be resolved.

## Repo layout

```
.claude/skills/blastradius/
  SKILL.md          # the /blastradius Claude Code command
  install.sh        # one-time silent-mode installer (wires the git hook)
  run.py            # index → graph → report, one shot
  indexer.py        # tree-sitter extraction (facts.json, hash-cached)
  graph.py          # resolution + attribution + metrics (graph.json)
  report.py         # blastradius.md renderer (deterministic)
  query.py          # /blastradius blast cards (pure stdlib)
  pr_impact.py      # Phase 2 PR scorer (pure stdlib)
  hooks/pre-commit  # silent-mode git hook (regenerates on every commit)
  adapters/         # python, javascript, jvm (java+kotlin), swift
.github/workflows/
  blastradius-report.yml   # report refresh on main
  blastradius-pr.yml       # PR impact comments
```

## How it runs — three surfaces, one graph

| Surface | Trigger | Needs Claude? | Needs setup |
|---|---|---|---|
| **Silent hook** | every local commit | no | `install.sh` once per clone |
| **CI report + PR comment** | push / pull request | no | copy the two workflow files |
| **`/blastradius <target>`** | you ask, in Claude Code | only this one | nothing |

All three read the same committed graph. The hook and CI keep it fresh; the query surface is a pure convenience. Nothing about continual use requires an LLM or a network call.

## License

MIT
