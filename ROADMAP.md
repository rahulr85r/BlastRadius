# BlastRadius Roadmap

The canonical list of things we'd like to improve, organized by scope and readiness. The shorter "good first issue" pointers in [`README.md`](README.md) and [`CONTRIBUTING.md`](CONTRIBUTING.md#contributing-opportunities) are quick pointers into this document.

For how to claim and contribute an item, see [`CONTRIBUTING.md`](CONTRIBUTING.md).

---

## Philosophy

These constraints are load-bearing — proposals that violate them are out of scope no matter how compelling:

- **No LLM in the analysis.** Deterministic static analysis only.
- **No MCP server, no daemon, no network at analysis time.** tree-sitter locally; pure-stdlib downstream.
- **No false edges.** Unresolvable/ambiguous references create no edge — they're counted, not guessed.
- **Deterministic, committed output.** The report is a single markdown file with meaningful diffs.

Anything that satisfies these is fair game.

---

## Status snapshot

- **4 language adapters**: Python, JavaScript, Java/Kotlin (JVM), Swift.
- **Two phases shipping**: the committed `blastradius.md` report (Phase 1) and symbol-level PR impact scoring (Phase 2), plus a silent commit hook and a `/blastradius` Claude Code skill.
- **Resolution**: path-aware (Python/JS), package-qualified (JVM), uniqueness-gated with a framework-name guard (Swift). Dogfooded on netty, Signal-Android, Fincept, DDG, blinkit (~12k files, zero adapter crashes).
- **Validation**: ad-hoc — no formal regression suite yet (see below).

---

## Near-term — concrete, scoped, ~a few hours each

### Language adapters

- **TypeScript adapter** (`adapters/typescript.py`). Extends the JS adapter to `.ts` / `.tsx`; grammars share ~95% of node types. *Highest-impact contribution — most modern frontends are TS.*
- **Go adapter** (`adapters/go.py`). `tree-sitter-go`. Modern infra code; explicit imports make resolution clean.
- **Rust adapter** (`adapters/rust.py`). `tree-sitter-rust`. `use` paths + `mod` tree.
- **Ruby adapter** (`adapters/ruby.py`). `tree-sitter-ruby`. `require`/`require_relative`.
- **C# adapter** (`adapters/csharp.py`). `tree-sitter-c-sharp`. Namespaces map cleanly to the JVM-style package resolver.

### Resolver precision

- **Widen the Swift framework-name guard.** `SWIFT_FRAMEWORK_TYPES` in `graph.py` lists SwiftUI/UIKit/Foundation names that collide with local types (so a local `enum Button` doesn't collect every SwiftUI `Button` use as a false dependent). Add more names; keep generic English words (`Event`, `Name`, `Type`) *out* — those are often legit local hotspots.
- **Import-aware Swift resolution.** Use each file's `import` list to disambiguate: a file that doesn't import SwiftUI referencing `Button` more likely means a local `Button`. More precise than the flat name guard.
- **JVM same-package nuance.** Type references resolve through same-package + wildcard imports today; audit for cases where an explicit import should win over a same-package same-named type.

### Report / output

- **Query-time filters** for the `/blastradius` skill and report: `--lang`, `--exclude=tests/`, `--only=src/`.
- **Per-symbol docstring in blast cards.** The index has per-symbol signatures and spans; capturing the leading doc line would let `/blastradius X` answer "what does X do" with no file read.

---

## Medium-term — design discussion first

Open an issue before writing code.

- **Ranking within a giant SCC.** When a large dependency cycle exists (e.g. DDG's `Core`), hundreds of files land at the same blast-radius % because they're all mutually reachable — a flat, unhelpful plateau. A within-cycle ranking (by direct in-degree, or centrality) would restore signal. This is the single biggest analysis-quality gap.
- **Graph regression test suite** (`tests/`). Gold-set fixtures: one config per repo with expected top hotspots and a sample of expected/forbidden edges. CI fails on drift. Highest-leverage item for confidence.
- **Git co-change signal.** Files that historically change together are coupled even when imports don't capture it (DI, event buses). A cheap, optional overlay that catches what static analysis can't — clearly labeled as a separate signal.
- **PR scoring calibration.** The tiered PR score is currently pct-of-repo + hub touch. Study whether a saturating/log scale reads better on real PRs, and whether to fold in cycle membership.

---

## Long-term / speculative

- **Cross-language edges.** A Kotlin caller of a Java class links today (same JVM adapter); a Swift↔ObjC or TS↔Python (RPC/codegen) boundary does not. Hard, and mostly out of scope, but noted.
- **Incremental PR-time graph.** Rebuild only the changed subgraph for very large monorepos, instead of the full graph, to keep CI fast at 100k+ files.
- **Multi-root / monorepo federation.** Independent packages in one repo with separate import namespaces, each result tagged by origin.

---

## Explicitly out of scope

Listed so contributors don't waste time:

- **Embeddings, semantic search, neural rerankers, LLM-as-analyzer.** Break "no LLM / no model artifact."
- **A hosted service / SaaS / dashboard.** BlastRadius is a per-repo tool, not a service. (Standalone code-visualization products have a poor track record; the committed-file + agent-context model is the deliberate bet.)
- **Runtime instrumentation.** BlastRadius is static-only by design; the radius is a floor, and that's stated on every artifact.
- **Replacing tree-sitter with a hand-written parser.**

If you have a richer-signal idea that fits the constraints, [open an issue](https://github.com/rahulr85r/BlastRadius/issues) — we'd rather discuss before you write code.
