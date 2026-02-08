#!/usr/bin/env python3
"""Estimate disk space saved by deleting duplicates (keeping one per group).

Usage:
    python estimate_savings.py duplicates.json

Input: JSON file from find_duplicates.py (list of duplicate file groups).
Output: Space savings analysis with per-group breakdown and totals.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import List


def format_size(size_bytes: int) -> str:
    """Return human-readable size (B, KiB, MiB, GiB, TiB)."""
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} PiB"


def estimate_savings(duplicates: List[List[str]], *, verbose: bool = False) -> dict:
    """Calculate space savings if all but one file per group is deleted.

    Returns dict with:
    - total_savings: bytes saved
    - group_count: number of duplicate groups
    - file_count_total: total files across all groups
    - file_count_kept: files kept (one per group)
    - file_count_deleted: files deleted
    - groups: list of per-group breakdown (if verbose)
    """

    total_savings = 0
    group_count = 0
    file_count_total = 0
    file_count_deleted = 0
    groups_info = [] if verbose else None

    for group in duplicates:
        if not group:
            continue

        group_count += 1
        file_count_total += len(group)
        file_count_deleted += len(group) - 1

        # Get size of first file (kept); all are identical in a duplicate group
        kept_path = group[0]
        try:
            file_size = os.path.getsize(kept_path)
        except OSError as exc:
            print(
                f"Warning: could not stat '{kept_path}': {exc}",
                file=sys.stderr,
            )
            file_size = 0

        # Savings = (count - 1) * file_size (delete all but one)
        group_savings = (len(group) - 1) * file_size
        total_savings += group_savings

        if verbose:
            groups_info.append(
                {
                    "count": len(group),
                    "size_per_file": file_size,
                    "group_savings": group_savings,
                    "files": group,
                }
            )

    file_count_kept = group_count

    return {
        "total_savings": total_savings,
        "group_count": group_count,
        "file_count_total": file_count_total,
        "file_count_kept": file_count_kept,
        "file_count_deleted": file_count_deleted,
        "groups": groups_info,
    }


def print_summary(result: dict) -> None:
    """Print a summary of space savings."""
    print("=" * 70)
    print("DISK SPACE SAVINGS ANALYSIS")
    print("=" * 70)
    print(f"\nDuplicate groups found:     {result['group_count']}")
    print(f"Total files in groups:      {result['file_count_total']}")
    print(f"Files to keep (1 per group): {result['file_count_kept']}")
    print(f"Files to delete:            {result['file_count_deleted']}")
    print(f"\nSpace saved if deleted:     {format_size(result['total_savings'])}")
    print(f"                            ({result['total_savings']:,} bytes)")
    print("=" * 70)


def print_detailed(result: dict) -> None:
    """Print per-group breakdown of savings."""
    if not result["groups"]:
        return
    print("\nDetailed per-group breakdown:")
    print("-" * 70)
    for idx, group_info in enumerate(result["groups"], start=1):
        files = group_info["files"]
        size_per = group_info["size_per_file"]
        count = group_info["count"]
        savings = group_info["group_savings"]

        print(f"\nGroup {idx}: ({count} files, {format_size(size_per)} each)")
        print(f"  Savings if duplicates deleted: {format_size(savings)}")
        print(f"  Files:")
        for path in files:
            print(f"    {path}")


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Estimate disk space savings by deleting duplicate files."
    )
    parser.add_argument(
        "json_file",
        help="JSON file from find_duplicates.py (list of duplicate groups)",
    )
    parser.add_argument(
        "--detailed",
        action="store_true",
        help="Show per-group breakdown (verbose)",
    )
    return parser.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    json_path = os.path.abspath(args.json_file)

    if not os.path.isfile(json_path):
        print(f"Error: '{json_path}' is not a file.", file=sys.stderr)
        return 1

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            duplicates = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Error: failed to read JSON from '{json_path}': {exc}", file=sys.stderr)
        return 1

    if not isinstance(duplicates, list):
        print(
            "Error: JSON must be a list of duplicate groups (each a list of paths).",
            file=sys.stderr,
        )
        return 1

    result = estimate_savings(duplicates, verbose=args.detailed)
    print_summary(result)

    if args.detailed:
        print_detailed(result)

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
