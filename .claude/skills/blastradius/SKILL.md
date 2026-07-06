---
name: blastradius
description: Answer "what breaks if I change this?" from the repo's committed dependency graph — per file AND per class/function. Zero LLM analysis, pure local lookup.
argument-hint: "<file, class, or function — empty for repo overview>"
disable-model-invocation: true
when_to_use: Before changing, refactoring, or deleting code the user is unsure about — "what depends on X?", "is it safe to change Y?", "what's the blast radius of Z?". Also to review the repo's risk hotspots. Reads the pre-built graph; no file scanning.
---

# BlastRadius — dependency impact lookup

The user invoked `/blastradius` with this target:

> **$ARGUMENTS**

Blast card from the local dependency graph (zero LLM calls — pure local lookup):

!`python3 .claude/skills/blastradius/query.py "$ARGUMENTS"`

---

## How to use the blast card above

- **Risk is per-symbol, not per-file.** The per-symbol breakdown shows which class/function the dependents actually enter through. If the user plans to edit a symbol listed as *lower-risk / no attributed dependents*, say so — even when the file's overall tier is high. Conversely, if their edit touches a load-bearing symbol, lead with that.
- **"Direct dependents" break first.** When the user asks what to check or test after a change, list the direct dependents; mention the transitive count and depth for scale.
- **Hubs (⚠️)**: broadly depended on by design; recommend extra review, not avoidance.
- **The graph under-claims.** It is static import/type analysis — dependency injection, reflection, event buses, and cross-service calls are invisible. Present the radius as a floor: "at least N files".
- If the card says **no graph found**, offer to build it: `python3 .claude/skills/blastradius/run.py` (needs `pip install -r .claude/skills/blastradius/requirements.txt` once). If the target didn't resolve uniquely, show the listed candidates and ask which one the user means.
- The full committed report is at `blastradius.md` (repo root); point the user there for the repo-wide picture (hotspots, cycles, hub list).

Answer the user's underlying question now, using the blast card.
