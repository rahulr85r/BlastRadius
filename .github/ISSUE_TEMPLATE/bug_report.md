---
name: Bug report
about: Something in BlastRadius isn't working the way it should
title: "[bug] "
labels: bug
---

## What happened

<!-- A clear description of what went wrong. -->

## What you expected

<!-- What did you expect instead? -->

## Steps to reproduce

<!--
Ideally:
1. A small public repo (or an anonymised snippet) the bug shows up on
2. The command you ran (e.g. `run.py --verbose`, or a `/blastradius` query)
3. What you got vs what you expected
-->

## Is it a false edge / wrong hotspot?

<!--
BlastRadius's core promise is "no false edges." If a file or symbol looks
wrong in the report, the most useful thing you can tell us is:
- The edge/hotspot you think is wrong (e.g. "Button.swift shows 80 dependents")
- Why you think it's wrong (e.g. "it's a local enum, but the repo imports
  SwiftUI which has its own Button")
This is exactly the class of bug we most want to catch.
-->

## Environment

- BlastRadius commit: <!-- `git -C .claude/skills/blastradius log -1 --oneline` -->
- Python version: <!-- `python3 --version` -->
- OS:
- Repo size (rough file count, languages):

## Output

<!-- The relevant part of blastradius.md, the `/blastradius` card, or the
--verbose resolution stats line. Usually small enough to inline. -->

```
<paste here>
```

## Anything else

<!-- Theories, related issues, etc. -->
