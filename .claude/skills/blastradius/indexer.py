#!/usr/bin/env python3
"""BlastRadius indexer — phase 1 of the pipeline.

Walks the repository, parses code files via tree-sitter adapters, and writes
per-file extraction facts (symbols, imports, references, type refs) to:

    .claude/skills/blastradius/index/facts.json
    .claude/skills/blastradius/index/meta.json   # file hashes (incremental)

The graph builder (graph.py) consumes facts.json; the report renderer
(report.py) consumes the graph. Run everything at once via run.py.

Dependencies: tree-sitter + per-language grammars (see requirements.txt) —
needed at INDEX time only. Everything downstream is pure stdlib.
The indexer degrades gracefully: if a grammar is missing, files in that
language are skipped with a warning, but the rest of the index still builds.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from adapters import availability_report, get_adapter, supported_extensions  # noqa: E402

# Directories pruned during the walk — generated artifacts, dependency trees,
# and tool caches. `.claude` is pruned by default so the skill's own code
# doesn't pollute consumer-repo graphs; pass --include-self when indexing the
# BlastRadius source repo itself.
STOP_DIRS = {
    "node_modules", "vendor", "dist", "build", "target", "out",
    ".git", ".venv", "venv", "env", ".tox",
    ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "__pycache__", ".next", ".nuxt",
    ".gradle", ".idea", ".vscode",
    "DerivedData", "Pods", "Carthage",
    "coverage", "htmlcov", "site-packages",
    ".claude",
}

INDEX_REL = ".claude/skills/blastradius/index"
FACTS_FILE = "facts.json"
META_FILE = "meta.json"
FACTS_VERSION = 1

MAX_FILE_SIZE = 1024 * 1024  # 1 MB — skip vendored bundles, minified blobs


def find_repo_root(start: Path) -> Path:
    """Walk up from `start` looking for the repo root (.git, or the skill dir
    so the indexer still works in non-git contexts like tarballs)."""
    p = start.resolve()
    for _ in range(40):
        if (p / ".git").exists() or (p / ".claude" / "skills" / "blastradius").is_dir():
            return p
        if p.parent == p:
            break
        p = p.parent
    return start.resolve()


def current_commit(repo_root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return ""


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def walk_code(root: Path, exts, stop_dirs=None):
    """Yield (rel_path, full_path) for code files under `root`."""
    exts_set = {e.lower() for e in exts}
    stop = stop_dirs if stop_dirs is not None else STOP_DIRS
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in stop)
        for fn in sorted(filenames):
            ext = os.path.splitext(fn)[1].lower()
            if ext not in exts_set:
                continue
            full = Path(dirpath) / fn
            try:
                rel = full.relative_to(root).as_posix()
            except ValueError:
                continue
            yield rel, full


def load_json(path: Path):
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def build_facts(root: Path, force: bool = False, verbose: bool = False,
                include_self: bool = False) -> dict:
    """Parse the repo and return (and persist) the facts document."""
    started = time.time()
    avail = availability_report()
    if verbose:
        for lang, ok in sorted(avail.items()):
            mark = "OK " if ok else "-- "
            print(f"  [{mark}] adapter: {lang}", file=sys.stderr)

    stop_dirs = (STOP_DIRS - {".claude"}) if include_self else STOP_DIRS

    out_dir = root / INDEX_REL
    out_dir.mkdir(parents=True, exist_ok=True)
    meta_path = out_dir / META_FILE
    facts_path = out_dir / FACTS_FILE

    prev_meta = ({} if force else (load_json(meta_path) or {}))
    prev_hashes = prev_meta.get("file_hashes", {})
    prev_facts = None if force else load_json(facts_path)
    prev_files = (prev_facts or {}).get("files", {})

    files: dict = {}
    new_hashes: dict = {}
    n_parsed = n_reused = n_skipped = 0
    skip_reasons: dict = {}

    def _skip(reason: str):
        nonlocal n_skipped
        n_skipped += 1
        skip_reasons[reason] = skip_reasons.get(reason, 0) + 1

    for rel, full in walk_code(root, supported_extensions(), stop_dirs=stop_dirs):
        try:
            size = full.stat().st_size
        except OSError:
            _skip("stat-error")
            continue
        if size > MAX_FILE_SIZE:
            _skip("too-large")
            continue
        try:
            h = file_hash(full)
        except OSError:
            _skip("read-error")
            continue
        new_hashes[rel] = h

        if not force and prev_hashes.get(rel) == h and rel in prev_files:
            files[rel] = prev_files[rel]
            n_reused += 1
            continue

        adapter = get_adapter(rel)
        if adapter is None:
            _skip("no-adapter")
            continue

        try:
            with open(full, "rb") as f:
                source = f.read()
        except OSError:
            _skip("read-error")
            continue

        try:
            result = adapter.extract(source, rel)
        except Exception as exc:
            if verbose:
                print(f"  [warn] adapter failed on {rel}: {exc}", file=sys.stderr)
            _skip("adapter-exception")
            continue

        files[rel] = {
            "lang": adapter.LANGUAGE_NAME,
            "size": size,
            "package": result.package,
            "symbols": [s.to_dict() for s in result.symbols],
            "imports": [i.to_dict() for i in result.imports],
            "references": result.references,
            "type_refs": result.type_refs,
        }
        n_parsed += 1

    elapsed = time.time() - started
    facts = {
        "version": FACTS_VERSION,
        "built_at_commit": current_commit(root),
        "n_files": len(files),
        "n_parsed": n_parsed,
        "n_reused": n_reused,
        "n_skipped": n_skipped,
        "skip_reasons": skip_reasons,
        "adapters_available": avail,
        "files": files,
    }

    facts_path.write_text(
        json.dumps(facts, indent=1, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    meta_path.write_text(
        json.dumps({"version": FACTS_VERSION, "file_hashes": new_hashes},
                   indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(
        f"[blastradius] indexed {len(files)} files "
        f"({n_parsed} parsed, {n_reused} reused, {n_skipped} skipped) "
        f"in {elapsed:.2f}s",
        file=sys.stderr,
    )
    return facts


def main():
    p = argparse.ArgumentParser(description="BlastRadius indexer")
    p.add_argument("--root", type=Path, default=None,
                   help="Repo root (default: detect from cwd via .git)")
    p.add_argument("--force", action="store_true",
                   help="Full rebuild (ignore meta.json hash cache)")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--include-self", action="store_true",
                   help="Include `.claude/` in the index (used by the Blast "
                        "Radius source repo itself)")
    args = p.parse_args()
    root = find_repo_root(args.root or Path.cwd())
    build_facts(root, force=args.force, verbose=args.verbose,
                include_self=args.include_self)


if __name__ == "__main__":
    main()
