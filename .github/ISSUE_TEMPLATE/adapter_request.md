---
name: Language adapter request
about: Request (or propose) support for a new language
title: "[adapter] "
labels: adapter, enhancement
---

## Language

<!-- e.g. TypeScript, Go, Rust, Ruby, C#, C/C++ -->

## tree-sitter grammar to use

<!--
Most languages have a `tree-sitter-<language>` PyPI package. Link it.
If competing grammars exist (C++ is the classic case), say which one and why.
-->

## How does this language resolve dependencies?

<!--
This is the part that matters most for BlastRadius — an adapter extracts
symbols + imports, but the graph is only as good as how imports resolve to
files WITHOUT guessing. Sketch it:
- Explicit import paths? (like JS relative imports, Go/Rust module paths) →
  path-resolved, high precision.
- Package/namespace + type name? (like Java/Kotlin/C#) → package-qualified.
- No file-level imports, resolve by type reference? (like Swift) → must be
  uniqueness-gated, and watch for framework-name collisions.
-->

## Are you offering to write it, or just requesting it?

<!--
Both are valid. If writing it: `adapters/python.py` is the cleanest reference
for the extraction shape, and `graph.py` is where the resolver rule goes.
-->

## Representative repo to test against

<!--
Adapter PRs need a real-world audit — a public repo of >500 files in the
target language you know well enough to sanity-check the extracted symbols
and spot-check that the top hotspots' edges are real.
-->

## Anything weird about the language?

<!--
Special cases worth flagging up front:
- TypeScript: type-only imports, decorators, generics, path aliases
- Go: internal packages, vendoring
- Rust: `mod` tree vs files, re-exports
- C/C++: preprocessor, header/impl split
Not blockers — just context for whoever writes it.
-->
