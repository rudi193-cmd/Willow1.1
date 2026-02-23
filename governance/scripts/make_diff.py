#!/usr/bin/env python3
"""
make_diff.py — Generate a proper unified diff for governance proposals.

Usage:
    python governance/scripts/make_diff.py --file core/foo.py --new-file /tmp/foo_new.py
    python governance/scripts/make_diff.py --file core/foo.py --new-content-stdin

Output: unified diff to stdout, ready to embed in a ```diff block.

Why this exists:
    Hand-written diffs have wrong hunk line counts and fail git apply --check.
    This generates a valid unified diff via difflib so apply_commits.py succeeds.
"""

import sys
import difflib
import argparse
from pathlib import Path


def make_diff(original_path: str, new_content: str) -> str:
    orig = Path(original_path)
    old_lines = orig.read_text(encoding="utf-8").splitlines(keepends=True) if orig.exists() else []
    new_lines = new_content.splitlines(keepends=True)

    # Use git-style a/ b/ prefixes so git apply accepts it
    rel = original_path.replace("\\", "/")
    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{rel}",
        tofile=f"b/{rel}",
        lineterm="",
    )
    return "".join(diff)


def main():
    parser = argparse.ArgumentParser(description="Generate unified diff for governance proposals")
    parser.add_argument("--file", required=True, help="Path to the existing file (relative to repo root)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--new-file", help="Path to file containing new content")
    group.add_argument("--stdin", action="store_true", help="Read new content from stdin")
    args = parser.parse_args()

    if args.new_file:
        new_content = Path(args.new_file).read_text(encoding="utf-8")
    else:
        new_content = sys.stdin.read()

    diff = make_diff(args.file, new_content)
    if not diff:
        print("# No changes detected", file=sys.stderr)
        sys.exit(0)

    print(diff, end="")


if __name__ == "__main__":
    main()
