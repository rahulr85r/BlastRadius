# Contributing to BlastRadius

Thank you for considering a contribution. BlastRadius is small on purpose. The bar for additions is one question: **does this help answer "what breaks if I change this?" more accurately, for more repos, without breaking the load-bearing constraints below?** Inside that lane, contributions of every size are welcome.

> **Sister project:** BlastRadius shares its DNA — the tree-sitter symbol-extraction adapters and the "no LLM, no server, pure-stdlib" philosophy — with [**TokenHack**](https://github.com/rahulr85r/TokenHack), which answers a different question (staging the right context so AI assistants spend fewer tokens on large repos). If you've contributed a language adapter to one, porting it to the other is often a couple of hours. Improvements to the shared adapter shape are welcome in both.

---

## The load-bearing constraints

These are what make BlastRadius adoptable. A change that violates one is out of scope no matter how clever — please don't spend time on it without opening an issue first:

- **No LLM in the analysis.** Everything is deterministic static analysis. Same code in → same report out.
- **No MCP server, no daemon, no network at analysis time.** tree-sitter parses locally; everything downstream is pure Python stdlib.
- **No false edges.** An import or type reference that can't be resolved *unambiguously* to a repo file must create **no edge** — count it in the resolution stats instead. The graph under-claims rather than lies. This is the property the whole product's credibility rests on.
- **Deterministic, committed output.** The report is a committed markdown file whose diffs are meaningful. Anything that makes the output non-deterministic (timestamps, ordering by a hash set, RNG) will be rejected.

---

## The short version

1. **Fork** this repo to your own GitHub account.
2. Clone your fork, create a branch (`git checkout -b your-change-name`).
3. Make your change; run the pipeline locally to sanity-check (see [Testing](#testing-your-change)).
4. Push to your fork and **open a pull request** against `rahulr85r/BlastRadius:main`.
5. Rahul reviews. Once approved, your PR is merged.

Direct pushes to `main` are blocked for everyone except the repo owner.

---

## Setting up your fork

```bash
# 1. Fork https://github.com/rahulr85r/BlastRadius — you now have your own copy.

# 2. Clone YOUR fork (replace YOUR-USERNAME):
git clone https://github.com/YOUR-USERNAME/BlastRadius.git
cd BlastRadius

# 3. Add the original as "upstream" so you can sync future changes:
git remote add upstream https://github.com/rahulr85r/BlastRadius.git
git fetch upstream
```

Before starting a contribution, sync your `main` with upstream:

```bash
git checkout main && git fetch upstream && git rebase upstream/main && git push origin main
```

---

## Making a change

```bash
git checkout -b add-typescript-adapter
# ... make your change, test it locally ...
git add <files>
git commit -m "Add TypeScript adapter

Extends adapters/javascript.py to .ts / .tsx. The tree-sitter-typescript
grammar shares ~95% of node types with the JavaScript grammar, so most of
the extraction logic carries over unchanged."
git push origin add-typescript-adapter
# Open a PR: your branch -> rahulr85r/BlastRadius:main
```

### Commit style

Short subject (≤ 70 chars), imperative mood ("Add X", not "Added X"). If the change is more than a couple of lines, explain the **why** in the body — the git history is the durable record of design decisions.

**No AI attribution lines** (`Co-Authored-By: Claude`, Copilot, etc.) in commits. BlastRadius credits humans only. Using an AI assistant to draft a change is fine; just don't co-author the commit with it.

---

## Testing your change

There's no formal test suite yet (a ranker/graph regression suite is the highest-leverage item on the [roadmap](ROADMAP.md)). For now, test by hand — and because the whole product is "the graph must not lie," **testing means auditing real edges, not just checking that it runs.**

**1. Run the full pipeline on a real repo:**

```bash
cd /path/to/some/repo
python3 -m venv .br-venv && source .br-venv/bin/activate
pip install -r /path/to/BlastRadius/.claude/skills/blastradius/requirements.txt
python3 /path/to/BlastRadius/.claude/skills/blastradius/run.py --verbose
```

It should finish without errors and write `blastradius.md` at the repo root plus `.claude/skills/blastradius/index/graph.json`.

**2. Audit the output for correctness, not just presence.** Open `blastradius.md` and pick 2–3 of the top hotspots. For each, spot-check that its claimed dependents actually reference the local definition — not a framework/stdlib type of the same name. (This is exactly the class of bug that produces false edges; the resolver's job is to *skip* the ambiguous ones.)

**3. For resolver / adapter changes**, include in your PR description:
- Edge counts **before and after** on at least one real repo of >500 files.
- If your change removes edges, confirm they were *false* edges (sample a few). If it adds edges, confirm they're *real*.
- Confirm non-target languages are unaffected (byte-identical graph is the usual expectation when you only touch one language's resolver).

**4. For anything that changes committed output**, confirm it's still **deterministic**: run twice with `--force` and diff — `graph.json` and `blastradius.md` must be byte-identical across runs.

This concrete before/after evidence is the closest thing BlastRadius has to tests right now.

---

## Contributing opportunities

The canonical list is [`ROADMAP.md`](ROADMAP.md). The highest-impact items:

**Sharply scoped, ~a few hours each:**

- **TypeScript adapter** (`adapters/typescript.py`) — extends the JS adapter to `.ts` / `.tsx`. Highest-leverage contribution; most modern frontends are TS.
- **Go / Rust / Ruby / C# adapters** — tree-sitter wrappers following the shape of `adapters/python.py`, plus a resolver rule in `graph.py`.
- **Widen the Swift framework-name guard** (`SWIFT_FRAMEWORK_TYPES` in `graph.py`) — more SwiftUI/UIKit/Foundation names that collide with local types.

**Larger — open an issue first to scope:**

- Ranking *within* a giant strongly-connected component (dependency cycle), so the report differentiates the files inside a big cycle instead of a flat plateau.
- A graph regression test suite (`tests/`): gold-set repos with expected hotspots/edges, CI fails on drift.
- Import-aware Swift resolution (use a file's `import` list to disambiguate framework vs local type references).

If you have an idea that fits the constraints, open an issue — happy to discuss before you write code.

---

## Pull request checklist

- [ ] Branch is up to date with `upstream/main`.
- [ ] Ran the pipeline locally on at least one real repo.
- [ ] **Audited** a sample of edges for correctness (no false edges introduced).
- [ ] Output is still deterministic (two `--force` runs are byte-identical).
- [ ] Commits have descriptive messages explaining the *why*.
- [ ] No AI attribution lines in commits.
- [ ] For resolver/adapter changes: before/after edge counts in the PR description.
- [ ] For new adapters: tested on a real repo of that language.

The PR template walks you through this.

---

## Review process

Rahul reads every PR personally. Expect a first response within a few days, inline comments, and a squash-merge into `main` once approved. If you don't hear back after a week, feel free to ping the PR.

---

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). By participating, you agree to abide by its terms. Report unacceptable behavior to the contact in that document.

## License

By contributing, you agree that your contributions will be licensed under the same [MIT License](LICENSE) that covers the project. You retain copyright on your contributions.
