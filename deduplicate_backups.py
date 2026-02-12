#!/usr/bin/env python3
"""
Deduplication script for telegram-backup (SQLite backend).

This script:
1. Scans the backup directory and computes sample hashes for all files
   (reuses existing DB hashes when available; hashes files missing in DB)
2. Updates DB records with missing hashes and/or sizes
3. Rebuilds the global hash index in SQLite
4. Identifies and moves duplicate files to a 'duplicates' folder
5. Updates DB records with new paths

Usage:
    python deduplicate_backups.py

The script will read BACKUP_DIR from .env or prompt for it.
"""

import os
import sys
import json
from datetime import datetime
from collections import defaultdict

# Add project root to path to import modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import utils
from state_db import DatabaseManager


def _is_duplicate_dir(path):
    """Return True if path is inside a duplicate/duplicates folder."""
    parts = path.split(os.sep)
    return 'duplicates' in parts or 'duplicate' in parts


def _normalize_path(path):
    if not path:
        return None
    return os.path.normcase(os.path.realpath(os.path.normpath(path)))


def load_env():
    """Load environment variables from .env file."""
    env_file = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_file):
        with open(env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip().strip('"').strip("'")


def get_backup_dir():
    """Get backup directory from env or prompt user."""
    load_env()

    backup_dir = getattr(config, 'BACKUP_DIR', None) or os.environ.get('BACKUP_DIR')

    if not backup_dir or not os.path.isdir(backup_dir):
        print("BACKUP_DIR not found in .env or invalid.")
        backup_dir = input("Enter the full path to your backup directory: ").strip()

    if not os.path.isdir(backup_dir):
        print(f"Error: '{backup_dir}' is not a valid directory.")
        sys.exit(1)

    return os.path.abspath(backup_dir)


def scan_and_hash_files(backup_dir, message_index=None):
    """
    Recursively scan the backup directory and compute hashes for all files.
    Returns: (file_hashes, untracked_files)
    - file_hashes: {file_path: (size, sample_hash)}
    - untracked_files: list of dicts with untracked file details
    """
    file_hashes = {}
    untracked_files = []

    for root, dirs, files in os.walk(backup_dir):
        if _is_duplicate_dir(root) or '/.backup' in root:
            continue

        # Skip files directly in the backup root (only process subfolders)
        if _normalize_path(root) == _normalize_path(backup_dir):
            continue

        for filename in files:
            if filename.startswith('.'):
                continue

            file_path = os.path.join(root, filename)

            try:
                size = os.path.getsize(file_path)
                if size == 0:
                    try:
                        os.remove(file_path)
                        print(f"  🗑️  Deleted empty file: {filename}")
                    except Exception as e:
                        print(f"  ⚠️  Failed to delete empty file {filename}: {e}")
                    continue

                sample_hash = None
                if message_index is not None:
                    normalized = _normalize_path(file_path)
                    existing = message_index.get(normalized)
                    if existing and existing.get('sample_hash') and existing.get('file_size') == size:
                        sample_hash = existing.get('sample_hash')
                    if not existing:
                        untracked_files.append({
                            'path': file_path,
                            'relative_path': os.path.relpath(file_path, backup_dir),
                            'size': size
                        })

                if not sample_hash:
                    sample_hash = utils.sample_hash_file(file_path)

                if sample_hash:
                    file_hashes[file_path] = (size, sample_hash)
            except Exception as e:
                print(f"  ⚠️  Error processing {filename}: {e}")
                continue

    # Attach hashes to untracked entries (only if we computed a hash)
    untracked_by_path = {u['path']: u for u in untracked_files}
    for file_path, (size, sample_hash) in file_hashes.items():
        entry = untracked_by_path.get(file_path)
        if entry:
            entry['sample_hash'] = sample_hash

    return file_hashes, untracked_files


def register_untracked_hashes(db_manager, file_hashes, message_index):
    """Register untracked file hashes in global index with empty message/chat IDs."""
    registered = 0
    for file_path, (size, sample_hash) in file_hashes.items():
        if _normalize_path(file_path) in message_index:
            continue
        if not sample_hash:
            continue
        db_manager.register_file_hash(size, sample_hash, file_path, message_id=None, chat_id=None)
        registered += 1
    return registered


def update_db_hashes(db_manager, message_index, file_hashes):
    """Update DB records with missing hashes/sizes for tracked files."""
    updated = 0
    for file_path, (size, sample_hash) in file_hashes.items():
        normalized = _normalize_path(file_path)
        msg = message_index.get(normalized)
        if not msg:
            continue

        stored_hash = msg.get('sample_hash')
        stored_size = msg.get('file_size')

        if stored_hash == sample_hash and stored_size == size:
            continue

        with db_manager.get_cursor(commit=True) as cursor:
            cursor.execute(
                """
                UPDATE messages
                SET file_size = ?, sample_hash = ?, file_path = ?, filename = ?
                WHERE chat_id = ? AND message_id = ?
                """,
                (
                    size,
                    sample_hash,
                    file_path,
                    os.path.basename(file_path),
                    msg.get('chat_id'),
                    msg.get('message_id')
                )
            )
        updated += 1

    return updated


def group_duplicates(file_hashes):
    """Group file paths by (size, sample_hash) and return only duplicates."""
    hash_groups = defaultdict(list)
    for file_path, (size, sample_hash) in file_hashes.items():
        if not sample_hash:
            continue
        hash_groups[(size, sample_hash)].append(file_path)

    return {k: v for k, v in hash_groups.items() if len(v) > 1}


def choose_canonical(paths, message_index):
    """Prefer keeping a tracked file when possible."""
    for path in paths:
        if _normalize_path(path) in message_index:
            return path
    return paths[0]


def prune_global_index(db_manager):
    """
    Remove global hash index entries whose files no longer exist.
    Faster than full rebuild because it avoids re-hashing files.
    """
    removed = 0
    with db_manager.get_cursor(commit=True) as cursor:
        cursor.execute("SELECT hash_key, first_occurrence_path FROM file_hashes")
        for row in cursor.fetchall():
            path = row['first_occurrence_path']
            if not path or not os.path.exists(path):
                cursor.execute("DELETE FROM file_hashes WHERE hash_key = ?", (row['hash_key'],))
                removed += 1
    return removed


def move_duplicates(backup_dir, duplicate_groups, db_manager, message_index):
    """
    Move duplicate files to duplicates/ folder, keeping first occurrence.
    Updates DB records with new paths.
    """
    duplicates_base = os.path.join(backup_dir, 'duplicates')

    total_moved = 0
    bytes_saved = 0

    for idx, ((size, sample_hash), paths) in enumerate(duplicate_groups.items(), start=1):
        canonical_path = choose_canonical(paths, message_index)
        duplicates = [p for p in paths if p != canonical_path]

        print(f"\nGroup {idx}: {len(paths)} copies ({utils.format_bytes(size)})")
        print(f"  Keeping: {os.path.relpath(canonical_path, backup_dir)}")

        for dup_path in duplicates:
            try:
                rel_path = os.path.relpath(dup_path, backup_dir)
                new_path = os.path.join(duplicates_base, rel_path)
                os.makedirs(os.path.dirname(new_path), exist_ok=True)

                os.rename(dup_path, new_path)

                total_moved += 1
                bytes_saved += size

                print(f"  → Moved: {rel_path}")

                update_db_paths(db_manager, dup_path, new_path)
            except Exception as e:
                print(f"  ✗ Error moving {os.path.basename(dup_path)}: {e}")

    return total_moved, bytes_saved


def update_db_paths(db_manager, old_path, new_path):
    """Update DB records that reference the old path."""
    try:
        db_manager.update_file_path(old_path, new_path)
    except Exception:
        pass


def main():
    print("=" * 80)
    print("Telegram Backup - Deduplicate Backups")
    print("=" * 80)
    print()

    # Force SQLite backend
    config.DB_ENABLE = True
    config.DB_LEGACY_JSON_FALLBACK = False

    backup_dir = get_backup_dir()
    print(f"📁 Backup directory: {backup_dir}\n")

    db_path = config.DB_PATH or os.path.join(backup_dir, "telegram_backup.db")
    db_manager = DatabaseManager(db_path)

    # Build message index (path -> message record)
    message_index = {}
    with db_manager.get_cursor() as cursor:
        cursor.execute("""
            SELECT chat_id, message_id, file_path, file_size, sample_hash
            FROM messages
            WHERE file_path IS NOT NULL
        """)
        for row in cursor.fetchall():
            normalized = _normalize_path(row['file_path'])
            if normalized:
                message_index[normalized] = dict(row)

    print("🔎 Scanning and hashing files...")
    file_hashes, untracked_files = scan_and_hash_files(backup_dir, message_index)
    print(f"✓ Hashed {len(file_hashes)} file(s)\n")

    if untracked_files:
        untracked_json_path = os.path.join(backup_dir, 'dedup_untracked_files.json')
        with open(untracked_json_path, 'w', encoding='utf-8') as f:
            json.dump({
                'scan_date': datetime.now().isoformat(),
                'total_untracked': len(untracked_files),
                'untracked_files': untracked_files
            }, f, indent=2)
        print(f"⚠️  Untracked files: {len(untracked_files)}")
        print(f"📝 Saved list to: {untracked_json_path}\n")

    updated = update_db_hashes(db_manager, message_index, file_hashes)
    if updated:
        print(f"✓ Updated {updated} DB record(s) with missing hashes/sizes\n")

    print("🌐 Rebuilding global hash index...")
    unique_count = db_manager.rebuild_hash_index_from_messages()

    # Register untracked files into global index (message_id/chat_id = NULL)
    untracked_registered = register_untracked_hashes(db_manager, file_hashes, message_index)
    print(f"✓ Global index built with {unique_count} unique file(s)\n")
    if untracked_registered:
        print(f"✓ Registered {untracked_registered} untracked file(s) in global index\n")

    duplicate_groups = group_duplicates(file_hashes)
    if not duplicate_groups:
        print("\n✅ No duplicates found! All files are unique.\n")
        return

    total_duplicates = sum(len(paths) - 1 for paths in duplicate_groups.values())
    print(f"\n📦 Found {total_duplicates} duplicate file(s) to consolidate\n")

    response = input("Move duplicates to 'duplicates' folder? (y/n): ").strip().lower()
    if response == 'y':
        print("\n🚚 Moving duplicates...")
        moved, saved = move_duplicates(backup_dir, duplicate_groups, db_manager, message_index)

        print("\n🔄 Pruning global index (fast path)...")
        removed = prune_global_index(db_manager)
        print(f"   Removed {removed} stale hash entr(ies)")

        print(f"\n✅ Deduplication complete!")
        print(f"  • Duplicates moved: {moved}")
        print(f"  • Space saved: {utils.format_bytes(saved)}")
        print(f"  • Duplicates folder: {os.path.join(backup_dir, 'duplicates')}")
    else:
        print("\n✓ Skipped duplicate consolidation")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Deduplication interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Error during deduplication: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)