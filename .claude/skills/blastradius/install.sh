#!/bin/sh
# BlastRadius — one-time silent-mode installer.
#
# Wires the pre-commit hook into this clone so blastradius.md regenerates
# automatically on every commit. Run once per clone:
#
#     sh .claude/skills/blastradius/install.sh
#
# (Add that line to your repo's existing setup script / Makefile so new
# clones get it with no extra step.)
#
# Git stores hooks in .git/hooks, which is NOT versioned — this is git's
# security model, so a one-time install per clone is unavoidable. After this,
# it's completely silent: nobody invokes anything, ever.

set -e
ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
    echo "BlastRadius: not inside a git repository." >&2
    exit 1
}

SRC="$ROOT/.claude/skills/blastradius/hooks/pre-commit"
HOOK="$ROOT/.git/hooks/pre-commit"
[ -f "$SRC" ] || { echo "BlastRadius: hook script not found at $SRC" >&2; exit 1; }
chmod +x "$SRC"
mkdir -p "$ROOT/.git/hooks"

# Already installed (our symlink) → done.
if [ -L "$HOOK" ] && [ "$(readlink "$HOOK")" = "../../.claude/skills/blastradius/hooks/pre-commit" ]; then
    echo "BlastRadius: silent mode already active."
    exit 0
fi

# A different pre-commit hook exists → don't clobber it; explain how to chain.
if [ -e "$HOOK" ]; then
    echo "BlastRadius: a pre-commit hook already exists at:"
    echo "    $HOOK"
    echo "Leave it in place and chain BlastRadius by adding this line to it:"
    echo ""
    echo "    \"\$(git rev-parse --show-toplevel)/.claude/skills/blastradius/hooks/pre-commit\" || true"
    echo ""
    exit 0
fi

# Relative symlink so hook-script updates propagate automatically and the link
# stays valid regardless of where the repo lives on disk.
ln -s "../../.claude/skills/blastradius/hooks/pre-commit" "$HOOK"
echo "BlastRadius: silent mode installed."
echo "blastradius.md now regenerates automatically on every commit — no commands, no noise."
