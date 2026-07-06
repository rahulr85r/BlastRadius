<!--
Thanks for sending a PR to BlastRadius. Fill in the sections below.
Delete any section that's genuinely not applicable.
-->

## Summary

<!-- One or two sentences: what does this PR do? -->

## Why

<!--
What problem does this solve? Link an issue if there is one ("Closes #42").
For features: what use case motivated it? For bug fixes: what was broken,
and how did you find it?
-->

## How I tested this

<!--
BlastRadius has no formal test suite yet. Because the whole product rests on
"the graph must not lie," testing means AUDITING edges, not just running it.

- Which repo did you run the pipeline on? (size, language)
- Edge counts BEFORE vs AFTER your change.
- Did you spot-check a sample of edges to confirm they're real (not false
  edges from a name collision)?
- If you only touched one language's resolver, is the graph for the other
  languages unchanged?
- Two `--force` runs still byte-identical? (determinism)
-->

## Checklist

- [ ] Branch is up to date with `upstream/main`.
- [ ] Ran the pipeline locally on at least one real repo.
- [ ] Audited a sample of edges — no false edges introduced.
- [ ] Output is still deterministic (two `--force` runs are byte-identical).
- [ ] Commit messages explain the *why*.
- [ ] No AI attribution lines (`Co-Authored-By: Claude` etc.) in commits.
- [ ] For resolver/adapter changes: before/after edge counts are in "How I tested".
- [ ] For a new adapter: tested on a real repo of that language.

## Anything else reviewers should know?

<!-- Trade-offs, open questions, things you're unsure about. -->
