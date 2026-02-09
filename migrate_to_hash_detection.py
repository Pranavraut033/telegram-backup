#!/usr/bin/env python3
"""
Migration script for telegram-backup hash-based duplicate detection.

⚠️  NOTE: This script works with JSON state files only. 
    For SQLite backups, use seed_from_json.py instead.

This script:
1. Scans all existing backup files and computes sample hashes
2. Populates the global state file (.backup_state_global.json)
3. Populates each chat's state file with hashes
4. Identifies and moves duplicate files to 'duplicates' folder
5. Updates all state files with new paths

Usage:
    python migrate_to_hash_detection.py
    
The script will read BACKUP_DIR from .env or prompt for it.
This script automatically forces JSON mode regardless of DB_ENABLE setting.
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import hashlib

# Add project root to path to import modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import utils
import config
from state_manager import StateManager, GlobalStateManager


def _is_duplicate_dir(path):
    """Return True if path is inside a duplicate/duplicates folder."""
    parts = path.split(os.sep)
    return 'duplicates' in parts or 'duplicate' in parts


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
    
    # Try to get from config/env
    backup_dir = getattr(config, 'BACKUP_DIR', None) or os.environ.get('BACKUP_DIR')
    
    if not backup_dir or not os.path.isdir(backup_dir):
        print("BACKUP_DIR not found in .env or invalid.")
        backup_dir = input("Enter the full path to your backup directory: ").strip()
    
    if not os.path.isdir(backup_dir):
        print(f"Error: '{backup_dir}' is not a valid directory.")
        sys.exit(1)
    
    return os.path.abspath(backup_dir)


def find_chat_directories(backup_dir):
    """
    Find all chat directories in the backup folder.
    A chat directory contains media files (not state files).
    """
    chat_dirs = []
    
    for item in os.listdir(backup_dir):
        item_path = os.path.join(backup_dir, item)
        
        # Skip files, hidden folders, and duplicate/duplicates folder
        if not os.path.isdir(item_path):
            continue
        if item.startswith('.'):
            continue
        if item in ('duplicates', 'duplicate'):
            continue
        
        # Check if it contains media files
        has_media = False
        try:
            for sub_item in os.listdir(item_path):
                if not sub_item.startswith('.'):
                    sub_path = os.path.join(item_path, sub_item)
                    if os.path.isfile(sub_path):
                        has_media = True
                        break
                    # Could also be a subdirectory (topics)
                    elif os.path.isdir(sub_path):
                        for sub_sub_item in os.listdir(sub_path):
                            if not sub_sub_item.startswith('.') and os.path.isfile(os.path.join(sub_path, sub_sub_item)):
                                has_media = True
                                break
                if has_media:
                    break
        except PermissionError:
            continue
        
        if has_media:
            chat_dirs.append((item, item_path))
    
    return chat_dirs


def scan_and_hash_files(chat_dir):
    """
    Recursively scan a chat directory and compute hashes for all files.
    Returns dict: {file_path: (size, sample_hash)}
    """
    file_hashes = {}
    
    for root, dirs, files in os.walk(chat_dir):
        # Skip duplicate/duplicates folders
        if _is_duplicate_dir(root):
            continue
        
        for filename in files:
            if filename.startswith('.'):
                continue
            
            file_path = os.path.join(root, filename)
            
            try:
                size = os.path.getsize(file_path)
                if size == 0:
                    print(f"  ⚠️  Skipping empty file: {filename}")
                    continue
                
                sample_hash = utils.sample_hash_file(file_path)
                if sample_hash:
                    file_hashes[file_path] = (size, sample_hash)
            except Exception as e:
                print(f"  ⚠️  Error processing {filename}: {e}")
                continue
    
    return file_hashes


def update_chat_state(backup_dir, chat_name, chat_dir, file_hashes):
    """
    Update a chat's state file with computed hashes.
    Only updates files that already have message IDs in the state.
    Skips files not tracked in state (no placeholder IDs generated).
    Returns: (updated_count, skipped_files_list)
    
    Note: This script works with JSON state files only.
    """
    # Force JSON mode for this migration script
    import config as cfg
    original_db_enable = cfg.DB_ENABLE
    cfg.DB_ENABLE = False
    
    state_manager = StateManager(backup_dir, chat_name)
    
    # Restore original setting
    cfg.DB_ENABLE = original_db_enable
    
    def _normalize_path(path):
        if not path:
            return None
        return os.path.normcase(os.path.realpath(os.path.normpath(path)))

    # Track which files we found and hashed
    updated_count = 0
    skipped_files = []
    
    # Normalize file_hashes for reliable path comparison
    file_hashes_norm = {}
    for file_path, (size, sample_hash) in file_hashes.items():
        normalized = _normalize_path(file_path)
        if normalized:
            file_hashes_norm[normalized] = (file_path, size, sample_hash)
    
    # Get set of paths already in state (normalized)
    existing_paths = {
        _normalize_path(info.get('path'))
        for info in state_manager.state['downloaded_messages'].values()
        if info.get('path')
    }
    
    # Update existing entries with hashes
    for msg_id, file_info in state_manager.state['downloaded_messages'].items():
        file_path = file_info.get('path')
        normalized = _normalize_path(file_path)
        if normalized and normalized in file_hashes_norm:
            _, size, sample_hash = file_hashes_norm[normalized]
            file_info['sample_hash'] = sample_hash
            # Update size if missing or wrong
            if file_info.get('size') != size:
                file_info['size'] = size
            updated_count += 1
    
    # Collect files that are not in state (will be skipped)
    for normalized, (file_path, size, sample_hash) in file_hashes_norm.items():
        if normalized not in existing_paths:
            skipped_files.append({
                'chat': chat_name,
                'path': file_path,
                'relative_path': os.path.relpath(file_path, backup_dir),
                'size': size,
                'sample_hash': sample_hash,
                'reason': 'not_in_state'
            })
    
    # Rebuild hash index (only for tracked files)
    state_manager.rebuild_hash_index()
    
    return updated_count, skipped_files


def identify_duplicates(backup_dir):
    """
    Scan all files in backup directory and identify duplicates by size+hash.
    Returns: dict of {(size, hash): [file_paths]}
    """
    print("\n🔍 Scanning for duplicates across all chats...")
    
    hash_groups = defaultdict(list)
    total_files = 0
    
    for root, dirs, files in os.walk(backup_dir):
        # Skip duplicate/duplicates folder and hidden folders
        if _is_duplicate_dir(root) or '/.backup' in root:
            continue
        
        for filename in files:
            if filename.startswith('.'):
                continue
            
            file_path = os.path.join(root, filename)
            
            try:
                size = os.path.getsize(file_path)
                if size == 0:
                    continue
                
                sample_hash = utils.sample_hash_file(file_path)
                if sample_hash:
                    key = (size, sample_hash)
                    hash_groups[key].append(file_path)
                    total_files += 1
            except Exception:
                continue
    
    # Filter to only groups with duplicates
    duplicate_groups = {k: v for k, v in hash_groups.items() if len(v) > 1}
    
    print(f"✓ Scanned {total_files} files")
    print(f"✓ Found {len(duplicate_groups)} group(s) with duplicates")
    
    return duplicate_groups


def prune_global_index(global_state):
    """
    Remove global hash index entries whose files no longer exist.
    Faster than full rebuild because it avoids re-hashing files.
    """
    if not global_state.state.get('hash_index'):
        return 0
    
    removed = 0
    for key, path in list(global_state.state['hash_index'].items()):
        if not path or not os.path.exists(path):
            del global_state.state['hash_index'][key]
            removed += 1
    
    if removed:
        global_state._save_state()
    return removed


def move_duplicates(backup_dir, duplicate_groups):
    """
    Move duplicate files to duplicates/ folder, keeping first occurrence.
    Updates state files with new paths.
    """
    duplicates_base = os.path.join(backup_dir, 'duplicates')
    
    total_moved = 0
    bytes_saved = 0
    
    for idx, ((size, sample_hash), paths) in enumerate(duplicate_groups.items(), start=1):
        # Keep the first file, move others
        canonical_path = paths[0]
        duplicates = paths[1:]
        
        print(f"\nGroup {idx}: {len(paths)} copies ({utils.format_bytes(size)})")
        print(f"  Keeping: {os.path.relpath(canonical_path, backup_dir)}")
        
        for dup_path in duplicates:
            try:
                # Calculate relative path to preserve folder structure
                rel_path = os.path.relpath(dup_path, backup_dir)
                new_path = os.path.join(duplicates_base, rel_path)
                
                # Create necessary subdirectories
                os.makedirs(os.path.dirname(new_path), exist_ok=True)
                
                # Move the duplicate file
                os.rename(dup_path, new_path)
                
                total_moved += 1
                bytes_saved += size
                
                print(f"  → Moved: {rel_path}")
                
                # Update state files if they reference this file
                update_state_file_paths(backup_dir, dup_path, new_path)
                
            except Exception as e:
                print(f"  ✗ Error moving {os.path.basename(dup_path)}: {e}")
    
    return total_moved, bytes_saved


def update_state_file_paths(backup_dir, old_path, new_path):
    """
    Update any state files that reference the old path.
    """
    # Find all state files
    for filename in os.listdir(backup_dir):
        if filename.startswith('.backup_state_') and filename.endswith('.json'):
            state_file = os.path.join(backup_dir, filename)
            
            try:
                with open(state_file, 'r', encoding='utf-8') as f:
                    state = json.load(f)
                
                # Update paths in downloaded_messages
                updated = False
                if 'downloaded_messages' in state:
                    for msg_id, file_info in state['downloaded_messages'].items():
                        if file_info.get('path') == old_path:
                            file_info['path'] = new_path
                            updated = True
                
                if updated:
                    state['last_updated'] = datetime.now().isoformat()
                    with open(state_file, 'w', encoding='utf-8') as f:
                        json.dump(state, f, indent=2)
            
            except Exception:
                continue


def main():
    """Main migration process."""
    print("=" * 80)
    print("Telegram Backup - Hash Detection Migration Script")
    print("=" * 80)
    print()
    
    # Get backup directory
    backup_dir = get_backup_dir()
    print(f"📁 Backup directory: {backup_dir}\n")
    
    # Find all chat directories
    print("🔎 Discovering chat directories...")
    chat_dirs = find_chat_directories(backup_dir)
    
    if not chat_dirs:
        print("❌ No chat directories found in backup folder.")
        sys.exit(1)
    
    print(f"✓ Found {len(chat_dirs)} chat director(ies)\n")
    
    # Process each chat
    all_file_hashes = {}
    all_skipped_files = []
    
    for chat_name, chat_dir in chat_dirs:
        print(f"📂 Processing: {chat_name}")
        
        # Scan and hash files
        print("  Computing hashes...")
        file_hashes = scan_and_hash_files(chat_dir)
        print(f"  ✓ Hashed {len(file_hashes)} file(s)")
        
        # Update chat state
        print("  Updating state file...")
        updated, skipped_files = update_chat_state(backup_dir, chat_name, chat_dir, file_hashes)
        print(f"  ✓ Updated {updated} existing entries, skipped {len(skipped_files)} untracked files")
        
        # Collect skipped files
        all_skipped_files.extend(skipped_files)
        
        # Collect for global index (only tracked files)
        for file_path, hash_data in file_hashes.items():
            if file_path not in [s['path'] for s in skipped_files]:
                all_file_hashes[file_path] = hash_data
        
        print()
    
    # Build global state
    print("🌐 Building global hash index...")
    
    # Force JSON mode for this migration script
    import config as cfg
    original_db_enable = cfg.DB_ENABLE
    cfg.DB_ENABLE = False
    
    global_state = GlobalStateManager(backup_dir)
    
    # Restore original setting
    cfg.DB_ENABLE = original_db_enable
    
    global_state.state['hash_index'] = {}
    
    # Group by hash to register only first occurrence
    hash_to_path = {}
    for file_path, (size, sample_hash) in all_file_hashes.items():
        key = f"{size}:{sample_hash}"
        if key not in hash_to_path:
            hash_to_path[key] = file_path
    
    global_state.state['hash_index'] = hash_to_path
    global_state._save_state()
    print(f"✓ Global index built with {len(hash_to_path)} unique file(s)\n")
    
    # Save skipped files to JSON
    if all_skipped_files:
        skipped_json_path = os.path.join(backup_dir, 'migration_skipped_files.json')
        with open(skipped_json_path, 'w', encoding='utf-8') as f:
            json.dump({
                'migration_date': datetime.now().isoformat(),
                'total_skipped': len(all_skipped_files),
                'skipped_files': all_skipped_files
            }, f, indent=2)
        print(f"📝 Saved {len(all_skipped_files)} skipped file(s) to: migration_skipped_files.json\n")
    
    # Identify and move duplicates
    duplicate_groups = identify_duplicates(backup_dir)
    
    if not duplicate_groups:
        print("\n✅ No duplicates found! All files are unique.\n")
    else:
        total_duplicates = sum(len(paths) - 1 for paths in duplicate_groups.values())
        print(f"\n📦 Found {total_duplicates} duplicate file(s) to consolidate\n")
        
        # Ask for confirmation
        response = input("Move duplicates to 'duplicates' folder? (y/n): ").strip().lower()
        
        if response == 'y':
            print("\n🚚 Moving duplicates...")
            moved, saved = move_duplicates(backup_dir, duplicate_groups)
            
            # Fast prune global index after moving files
            print("\n🔄 Pruning global index (fast path)...")
            removed = prune_global_index(global_state)
            print(f"   Removed {removed} stale hash entr(ies)")
            
            print(f"\n✅ Migration complete!")
            print(f"  • Duplicates moved: {moved}")
            print(f"  • Space saved: {utils.format_bytes(saved)}")
            print(f"  • Duplicates folder: {os.path.join(backup_dir, 'duplicates')}")
        else:
            print("\n✓ Skipped duplicate consolidation")
    
    print("\n" + "=" * 80)
    print("Migration Summary:")
    print(f"  • Chats processed: {len(chat_dirs)}")
    print(f"  • Files tracked in state: {len(all_file_hashes)}")
    print(f"  • Files skipped (not in state): {len(all_skipped_files)}")
    print(f"  • Unique files: {len(hash_to_path)}")
    print(f"  • State files updated: {len(chat_dirs)} + 1 global")
    if all_skipped_files:
        print(f"  • Skipped files JSON: migration_skipped_files.json")
    print("=" * 80)
    print("\n✨ Your backups are now using hash-based duplicate detection!")
    print("   Future downloads will automatically skip duplicates.")
    if all_skipped_files:
        print(f"   ⚠️  {len(all_skipped_files)} untracked files were skipped (see migration_skipped_files.json)\n")
    else:
        print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Migration interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Error during migration: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
