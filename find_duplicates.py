#!/usr/bin/env python3
"""Detect duplicate files in a directory tree.

Usage:
    python find_duplicates.py /path/to/target

Functional approach:
1. Group files by size to avoid hashing obviously unique files.
2. For groups with >1 file, compute SHA-256 hashes in streaming mode.
3. Report groups where multiple files share the same size and hash.

Complexity:
- Time: O(N + H), where N is number of files (size check) and H is total bytes
  hashed across size-collision groups. Hashing is linear in examined data.
- Space: O(K), where K is the number of size collisions plus hash groupings;
  file contents are streamed in fixed chunks to keep memory bounded.
"""

from __future__ import annotations

import argparse
import json
import time
import hashlib
import os
import sys
from collections import defaultdict
from typing import Dict, Iterable, List, Tuple

CHUNK_SIZE = 1024 * 1024  # 1 MiB read size for hashing
SAMPLE_SIZE = 64 * 1024  # 64 KiB partial hash window for stage 2


def iter_files(root: str) -> Iterable[Tuple[str, int]]:
    """Yield (absolute_path, size_bytes) for regular files under root.

    Symlinks are skipped to avoid unintended traversal. Unreadable entries emit
    warnings but do not halt execution.
    """

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        # Optionally, we could prune dirnames here if needed; keeping defaults.
        for name in filenames:
            path = os.path.join(dirpath, name)
            try:
                st = os.lstat(path)
            except OSError as exc:  # e.g., permission denied
                print(f"Warning: could not stat '{path}': {exc}", file=sys.stderr)
                continue

            if not os.path.isfile(path) or os.path.islink(path):
                continue  # ignore non-regular files and symlinked files

            yield os.path.abspath(path), st.st_size


def hash_file(path: str) -> str | None:
    """Return SHA-256 hex digest for file, streaming in CHUNK_SIZE blocks.

    On failure, emit a warning and return None so caller can skip the file.
    """

    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            while True:
                chunk = handle.read(CHUNK_SIZE)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError as exc:
        print(f"Warning: could not read '{path}': {exc}", file=sys.stderr)
        return None

    return digest.hexdigest()


def sample_hash_file(path: str, sample_size: int) -> str | None:
    """Return SHA-256 digest of first+last N bytes to cheaply rule out mismatches.

    Uses full file if it is shorter than 2 * sample_size. On failure returns None.
    """

    if sample_size <= 0:
        return hash_file(path)

    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            # First window
            head = handle.read(sample_size)
            digest.update(head)

            # Tail window
            try:
                handle.seek(-sample_size, os.SEEK_END)
            except OSError:
                # File shorter than sample_size; rewind and hash full content once
                handle.seek(0, os.SEEK_SET)
                digest = hashlib.sha256()
                while True:
                    chunk = handle.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    digest.update(chunk)
                return digest.hexdigest()

            tail = handle.read(sample_size)
            digest.update(tail)
    except OSError as exc:
        print(f"Warning: could not read '{path}': {exc}", file=sys.stderr)
        return None

    return digest.hexdigest()


def group_by_size(files: Iterable[Tuple[str, int]]) -> Dict[int, List[str]]:
    groups: Dict[int, List[str]] = defaultdict(list)
    for path, size in files:
        groups[size].append(path)
    return groups


class ProgressLogger:
    """Lightweight progress logger that writes to stderr.

    - Uses carriage return on TTYs to update a single line.
    - Falls back to normal line printing when not a TTY.
    - Throttles updates to avoid excessive IO.
    """

    def __init__(self, enabled: bool, interval: float = 0.5):
        self.enabled = enabled
        self.interval = interval
        self._last = 0.0

    def update(self, message: str, *, force: bool = False) -> None:
        if not self.enabled:
            return
        now = time.monotonic()
        if not force and (now - self._last) < self.interval:
            return
        stream = sys.stderr
        if hasattr(stream, "isatty") and stream.isatty():
            print("\r" + message, end="", file=stream)
        else:
            print(message, file=stream)
        stream.flush()
        self._last = now

    def done(self) -> None:
        if not self.enabled:
            return
        stream = sys.stderr
        if hasattr(stream, "isatty") and stream.isatty():
            print(file=stream)


def find_duplicates(root: str, sample_size: int, *, progress: bool = False) -> List[List[str]]:
    """Find duplicate files under root, returning groups of duplicate paths."""

    prog = ProgressLogger(progress)

    size_groups = group_by_size(iter_files(root))
    total_files = sum(len(v) for v in size_groups.values())
    size_collision_candidates = sum(len(v) for v in size_groups.values() if len(v) > 1)
    prog.update(
        f"Stage 1/3: scanned files={total_files}, size-collision candidates={size_collision_candidates}",
        force=True,
    )
    duplicate_sets: List[List[str]] = []

    for size, paths in size_groups.items():
        if len(paths) < 2:
            continue  # unique size, cannot be duplicates

        # Stage 2: partial hash on size collisions to cheaply prune mismatches.
        sample_groups: Dict[str, List[str]] = defaultdict(list)
        sample_done = 0
        sample_total = len(paths)
        for path in paths:
            digest = sample_hash_file(path, sample_size)
            if digest:
                sample_groups[digest].append(path)
            sample_done += 1
            prog.update(
                f"Stage 2/3: partial hashing size={size} ({sample_done}/{sample_total})",
            )

        # Stage 3: full hash only on partial-hash collisions.
        full_total = sum(len(x) for x in sample_groups.values() if len(x) > 1)
        full_done = 0
        for sample_paths in sample_groups.values():
            if len(sample_paths) < 2:
                continue

            full_groups: Dict[str, List[str]] = defaultdict(list)
            for path in sample_paths:
                digest = hash_file(path)
                if digest:
                    full_groups[digest].append(path)
                full_done += 1
                prog.update(
                    f"Stage 3/3: full hashing size={size} ({full_done}/{max(full_total,1)})",
                )

            for digest_paths in full_groups.values():
                if len(digest_paths) > 1:
                    duplicate_sets.append(sorted(digest_paths))  # deterministic order

    prog.update(
        f"Done: duplicate groups={len(duplicate_sets)} (files scanned={total_files})",
        force=True,
    )
    prog.done()
    return duplicate_sets


def print_duplicates(duplicates: List[List[str]]) -> None:
    if not duplicates:
        print("No duplicate files found.")
        return

    print("Duplicate files detected:")
    for idx, group in enumerate(sorted(duplicates), start=1):
        print(f"\nGroup {idx}:")
        for path in group:
            print(f"  {path}")


def write_duplicates_json(duplicates: List[List[str]], out_path: str) -> None:
    """Write duplicates to a JSON file as a list of path lists.

    Ensures deterministic order by sorting paths within groups and groups overall.
    """
    # Sort paths within each group (already sorted, but enforce) and sort groups by tuple of paths
    normalized = [sorted(group) for group in duplicates]
    normalized.sort(key=lambda g: tuple(g))

    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(normalized, f, indent=2, ensure_ascii=False)
    except OSError as exc:
        print(f"Error: failed to write JSON to '{out_path}': {exc}", file=sys.stderr)
        raise


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect duplicate files within a directory (recursively)."
    )
    parser.add_argument(
        "root",
        help="Target directory to scan",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=SAMPLE_SIZE,
        help="Bytes to sample from start and end for partial hashing (default: 65536)",
    )
    parser.add_argument(
        "--progress",
        action="store_true",
        help="Show progress to stderr while hashing",
    )
    parser.add_argument(
        "--json-out",
        dest="json_out",
        metavar="PATH",
        help="Write duplicate groups to JSON file instead of printing",
    )
    return parser.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    root = os.path.abspath(args.root)

    if not os.path.isdir(root):
        print(f"Error: '{root}' is not a directory or is inaccessible.", file=sys.stderr)
        return 1

    sample_size = max(0, args.sample_size)

    duplicates = find_duplicates(root, sample_size, progress=args.progress)

    if args.json_out:
        try:
            write_duplicates_json(duplicates, os.path.abspath(args.json_out))
        except Exception:
            return 1
        # When writing JSON, avoid verbose printing; emit concise status.
        if duplicates:
            print(f"Wrote {len(duplicates)} duplicate group(s) to {os.path.abspath(args.json_out)}")
        else:
            # Write empty list to JSON and also inform the user
            print(f"No duplicate files found. Wrote empty list to {os.path.abspath(args.json_out)}")
    else:
        print_duplicates(duplicates)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
