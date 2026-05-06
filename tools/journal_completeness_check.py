#!/usr/bin/env python3
"""Orphan-paragraph completeness check.

Walks an OLD doc and asserts every non-trivial paragraph appears
(substring match, whitespace-normalised) in at least one destination
file or in an explicit allowlist of intentionally-dropped paragraphs.

Exit 0: every paragraph accounted for.
Exit 1: at least one orphan; report names the paragraph.
Exit 2: usage error.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


# Paragraphs shorter than this are skipped (one-liners, headers, list bullets
# of a couple words). Tunable; 80 is a reasonable cut.
_MIN_PARAGRAPH_LEN = 80


def _normalise(text: str) -> str:
    """Collapse whitespace to single spaces; strip; lowercase."""
    return re.sub(r"\s+", " ", text).strip().lower()


def _split_paragraphs(text: str) -> list[str]:
    """Split on blank lines; strip; filter trivially short / heading-only."""
    paragraphs: list[str] = []
    for chunk in re.split(r"\n\s*\n", text):
        chunk = chunk.strip()
        if not chunk:
            continue
        # Skip pure markdown headings (one line starting with #).
        lines = chunk.split("\n")
        if len(lines) == 1 and lines[0].lstrip().startswith("#"):
            continue
        # Skip code fences as units (they're complete; counted as one paragraph).
        if chunk.startswith("```"):
            paragraphs.append(chunk)
            continue
        if len(chunk) >= _MIN_PARAGRAPH_LEN:
            paragraphs.append(chunk)
    return paragraphs


def _load_allowlist(path: Path | None) -> set[str]:
    if path is None or not path.exists():
        return set()
    out: set[str] = set()
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.add(_normalise(line))
    return out


def check(
    old_path: Path,
    destination_paths: list[Path],
    allowlist: set[str],
) -> tuple[int, str]:
    """Return (exit_code, report_text)."""
    old_text = old_path.read_text()
    paragraphs = _split_paragraphs(old_text)

    destinations_text = "\n\n".join(p.read_text() for p in destination_paths if p.exists())
    destinations_normalised = _normalise(destinations_text)

    orphans: list[str] = []
    for p in paragraphs:
        norm = _normalise(p)
        if norm in destinations_normalised:
            continue
        if norm in allowlist:
            continue
        orphans.append(p)

    out: list[str] = []
    out.append(f"# Orphan-paragraph check\n\n")
    out.append(f"OLD doc: {old_path}\n")
    out.append(f"Destinations: {[str(d) for d in destination_paths]}\n")
    out.append(f"Allowlist size: {len(allowlist)}\n")
    out.append(f"Total non-trivial paragraphs in OLD: {len(paragraphs)}\n")
    out.append(f"Orphans: {len(orphans)}\n\n")
    for orphan in orphans:
        snippet = orphan[:200].replace("\n", " ")
        out.append(f"## Orphan\n\n{snippet}{'...' if len(orphan) > 200 else ''}\n\n")
    return (0 if not orphans else 1, "".join(out))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old", type=Path, required=True)
    parser.add_argument("--destinations", type=Path, nargs="+", required=True)
    parser.add_argument("--allowlist", type=Path, default=None)
    args = parser.parse_args(argv)

    allowlist = _load_allowlist(args.allowlist)
    exit_code, report = check(args.old, args.destinations, allowlist)
    print(report)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
