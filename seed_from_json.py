#!/usr/bin/env python3
"""
Seed script to import existing JSON state files into SQLite database.
Scans the backup directory for all state files and populates the database.
"""
import os
import json
import argparse
from datetime import datetime
from pathlib import Path
import config
from state_db import DatabaseManager


def log_info(message):
    """Print info message with timestamp"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")


def log_error(message):
    """Print error message"""
    print(f"❌ ERROR: {message}")


def log_success(message):
    """Print success message"""
    print(f"✅ {message}")


def find_state_files(backup_dir):
    """
    Find all JSON state files in the backup directory.
    
    Args:
        backup_dir: Root backup directory to scan
        
    Returns:
        tuple: (list of chat state files, global state file path or None)
    """
    chat_states = []
    global_state = None
    
    # Look for state files in the backup directory
    for root, _, files in os.walk(backup_dir):
        for fname in files:
            if fname.startswith('.backup_state_') and fname.endswith('.json'):
                fpath = os.path.join(root, fname)
                if 'global' in fname:
                    global_state = fpath
                else:
                    chat_states.append(fpath)
    
    return chat_states, global_state


def extract_chat_hash(state_filename):
    """
    Extract chat hash from state filename.
    Format: .backup_state_<hash>.json
    """
    basename = os.path.basename(state_filename)
    if basename.startswith('.backup_state_') and basename.endswith('.json'):
        return basename[14:-5]  # Remove prefix and .json
    return None


def import_chat_state(db, state_file, dry_run=False):
    """
    Import a single chat state file into the database.
    
    Args:
        db: DatabaseManager instance
        state_file: Path to JSON state file
        dry_run: If True, only validate without importing
        
    Returns:
        tuple: (success: bool, chat_name: str, stats: dict)
    """
    try:
        with open(state_file, 'r', encoding='utf-8') as f:
            state = json.load(f)
    except Exception as e:
        return False, None, {'error': f"Failed to read state file: {e}"}
    
    # Extract metadata
    chat_name = state.get('chat_name', 'Unknown')
    chat_hash = extract_chat_hash(state_file)
    
    if not chat_hash:
        return False, chat_name, {'error': 'Could not extract chat hash from filename'}
    
    # Collect stats
    downloaded_messages = state.get('downloaded_messages', {})
    skipped_messages = state.get('skipped_messages', [])
    failed_messages = state.get('failed_messages', [])
    
    if isinstance(downloaded_messages, list):
        # Old format - convert to dict
        downloaded_messages = {str(msg_id): {'filename': 'unknown', 'size': 0, 'path': None} 
                              for msg_id in downloaded_messages}
    
    stats = {
        'downloaded': len(downloaded_messages),
        'skipped': len(skipped_messages),
        'failed': len(failed_messages),
        'total_files': state.get('total_files', len(downloaded_messages)),
        'total_bytes': state.get('total_bytes', 0)
    }
    
    if dry_run:
        return True, chat_name, stats
    
    # Import into database
    try:
        # Create or get chat
        chat_id = db.get_or_create_chat(chat_name, chat_hash)
        
        # Update chat metadata
        chat_data = db.get_chat_by_hash(chat_hash)
        if not chat_data or not chat_data.get('started_at'):
            # Only update if not already set
            with db.get_cursor(commit=True) as cursor:
                cursor.execute("""
                    UPDATE chats SET 
                        started_at = ?,
                        completed = ?,
                        completed_at = ?,
                        total_files = ?,
                        total_bytes = ?,
                        last_message_id = ?
                    WHERE chat_id = ?
                """, (
                    state.get('started_at'),
                    state.get('completed', False),
                    state.get('completed_at'),
                    state.get('total_files', 0),
                    state.get('total_bytes', 0),
                    state.get('last_message_id'),
                    chat_id
                ))
        
        # Import messages
        message_count = 0
        for msg_id_str, file_info in downloaded_messages.items():
            try:
                msg_id = int(msg_id_str)
                db.add_message(
                    chat_id=chat_id,
                    message_id=msg_id,
                    filename=file_info.get('filename'),
                    file_path=file_info.get('path'),
                    file_size=file_info.get('size', 0),
                    sample_hash=file_info.get('sample_hash'),
                    full_hash=file_info.get('full_hash')
                )
                
                # Mark as downloaded
                db.set_message_status(chat_id, msg_id, 'downloaded')
                
                # Register in global hash index
                if file_info.get('sample_hash') and file_info.get('size', 0) > 0:
                    db.register_file_hash(
                        file_info['size'],
                        file_info['sample_hash'],
                        file_info.get('path')
                    )
                
                message_count += 1
            except Exception as e:
                log_error(f"Failed to import message {msg_id_str}: {e}")
                continue
        
        # Import skipped messages
        for msg_id in skipped_messages:
            try:
                db.set_message_status(chat_id, msg_id, 'skipped')
            except Exception as e:
                log_error(f"Failed to import skipped message {msg_id}: {e}")
        
        # Import failed messages
        for msg_id in failed_messages:
            try:
                db.set_message_status(chat_id, msg_id, 'failed')
            except Exception as e:
                log_error(f"Failed to import failed message {msg_id}: {e}")
        
        # Import duplicates
        duplicate_map = state.get('duplicate_map', {})
        for dup_msg_id_str, canon_msg_id_str in duplicate_map.items():
            try:
                dup_msg_id = int(dup_msg_id_str)
                canon_msg_id = int(canon_msg_id_str) if canon_msg_id_str != 'global' else -1
                db.mark_duplicate(chat_id, dup_msg_id, chat_id, canon_msg_id)
            except Exception as e:
                log_error(f"Failed to import duplicate mapping {dup_msg_id_str} -> {canon_msg_id_str}: {e}")
        
        stats['imported_messages'] = message_count
        return True, chat_name, stats
        
    except Exception as e:
        return False, chat_name, {'error': f"Failed to import into database: {e}"}


def import_global_state(db, state_file, dry_run=False):
    """
    Import global state file into the database.
    
    Args:
        db: DatabaseManager instance
        state_file: Path to global JSON state file
        dry_run: If True, only validate without importing
        
    Returns:
        tuple: (success: bool, stats: dict)
    """
    try:
        with open(state_file, 'r', encoding='utf-8') as f:
            state = json.load(f)
    except Exception as e:
        return False, {'error': f"Failed to read global state file: {e}"}
    
    hash_index = state.get('hash_index', {})
    stats = {'hash_entries': len(hash_index)}
    
    if dry_run:
        return True, stats
    
    # Import hash entries
    imported = 0
    for key, file_path in hash_index.items():
        try:
            # Parse key: "size:hash"
            parts = key.split(':', 1)
            if len(parts) != 2:
                continue
            
            file_size = int(parts[0])
            sample_hash = parts[1]
            
            # Only import if file still exists
            if os.path.exists(file_path):
                db.register_file_hash(file_size, sample_hash, file_path)
                imported += 1
        except Exception as e:
            log_error(f"Failed to import hash entry {key}: {e}")
            continue
    
    stats['imported_hashes'] = imported
    return True, stats


def seed_database(backup_dir, db_path=None, dry_run=False, force=False):
    """
    Main function to seed database from JSON state files.
    
    Args:
        backup_dir: Root backup directory containing JSON state files
        db_path: Path to database file (auto-determined if not set)
        dry_run: If True, only validate files without importing
        force: If True, overwrite existing database
        
    Returns:
        dict: Summary statistics
    """
    # Validate backup directory
    if not os.path.isdir(backup_dir):
        log_error(f"Backup directory not found: {backup_dir}")
        return None
    
    log_info(f"Scanning backup directory: {backup_dir}")
    
    # Find all state files
    chat_states, global_state = find_state_files(backup_dir)
    
    log_info(f"Found {len(chat_states)} chat state files")
    if global_state:
        log_info(f"Found global state file: {os.path.basename(global_state)}")
    
    if not chat_states and not global_state:
        log_error("No state files found in backup directory")
        return None
    
    if dry_run:
        log_info("DRY RUN MODE - No changes will be made")
    
    # Initialize database
    if not db_path:
        db_path = os.path.join(backup_dir, "telegram_backup.db")
    
    # Check if database already exists
    if os.path.exists(db_path) and not force and not dry_run:
        log_error(f"Database already exists: {db_path}")
        log_info("Use --force to overwrite existing database")
        return None
    
    if not dry_run:
        # Remove existing database if force
        if force and os.path.exists(db_path):
            log_info(f"Removing existing database: {db_path}")
            os.remove(db_path)
        
        log_info(f"Initializing database: {db_path}")
        db = DatabaseManager(db_path)
    else:
        db = None
    
    # Import chat states
    summary = {
        'total_chats': len(chat_states),
        'imported_chats': 0,
        'failed_chats': 0,
        'total_messages': 0,
        'total_bytes': 0,
        'errors': []
    }
    
    for i, state_file in enumerate(chat_states, 1):
        basename = os.path.basename(state_file)
        log_info(f"[{i}/{len(chat_states)}] Processing: {basename}")
        
        success, chat_name, stats = import_chat_state(db, state_file, dry_run)
        
        if success:
            summary['imported_chats'] += 1
            summary['total_messages'] += stats.get('downloaded', 0)
            summary['total_bytes'] += stats.get('total_bytes', 0)
            
            log_success(f"  Chat: {chat_name}")
            log_info(f"    Downloaded: {stats.get('downloaded', 0)} messages")
            log_info(f"    Skipped: {stats.get('skipped', 0)}")
            log_info(f"    Failed: {stats.get('failed', 0)}")
            log_info(f"    Size: {stats.get('total_bytes', 0):,} bytes")
        else:
            summary['failed_chats'] += 1
            error_msg = stats.get('error', 'Unknown error')
            log_error(f"  Failed to import {chat_name}: {error_msg}")
            summary['errors'].append(f"{basename}: {error_msg}")
    
    # Import global state
    if global_state and db:
        log_info(f"Processing global state: {os.path.basename(global_state)}")
        success, stats = import_global_state(db, global_state, dry_run)
        
        if success:
            log_success("  Global state imported")
            log_info(f"    Hash entries: {stats.get('imported_hashes', stats.get('hash_entries', 0))}")
        else:
            log_error(f"  Failed to import global state: {stats.get('error', 'Unknown error')}")
    
    # Print summary
    print("\n" + "=" * 60)
    print("IMPORT SUMMARY")
    print("=" * 60)
    print(f"Total chats found:    {summary['total_chats']}")
    print(f"Successfully imported: {summary['imported_chats']}")
    print(f"Failed:               {summary['failed_chats']}")
    print(f"Total messages:       {summary['total_messages']:,}")
    print(f"Total size:           {summary['total_bytes']:,} bytes ({summary['total_bytes'] / (1024**3):.2f} GB)")
    
    if summary['errors']:
        print(f"\nErrors encountered: {len(summary['errors'])}")
        for error in summary['errors'][:5]:  # Show first 5 errors
            print(f"  • {error}")
        if len(summary['errors']) > 5:
            print(f"  ... and {len(summary['errors']) - 5} more")
    
    if not dry_run and db:
        # Optimize database
        log_info("\nOptimizing database...")
        db.vacuum()
        db_size = db.get_database_size()
        log_success(f"Database optimized. Final size: {db_size:,} bytes ({db_size / (1024**2):.2f} MB)")
        db.close()
    
    print("=" * 60)
    
    return summary


def main():
    """Main entry point for seed script"""
    parser = argparse.ArgumentParser(
        description="Import JSON state files into SQLite database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run to validate files
  python seed_from_json.py --dry-run
  
  # Import with default settings
  python seed_from_json.py
  
  # Import with custom paths
  python seed_from_json.py --backup-dir /path/to/backup --db-path /path/to/db.sqlite
  
  # Force overwrite existing database
  python seed_from_json.py --force
        """
    )
    
    parser.add_argument(
        '--backup-dir',
        default=config.BACKUP_DIRECTORY,
        help=f"Backup directory to scan (default: {config.BACKUP_DIRECTORY})"
    )
    
    parser.add_argument(
        '--db-path',
        default=None,
        help="Path to SQLite database file (default: <backup-dir>/telegram_backup.db)"
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help="Validate files without importing"
    )
    
    parser.add_argument(
        '--force',
        action='store_true',
        help="Overwrite existing database"
    )
    
    args = parser.parse_args()
    
    # Run seeding
    print("=" * 60)
    print("TELEGRAM BACKUP - JSON TO SQLITE MIGRATION")
    print("=" * 60)
    print()
    
    result = seed_database(
        backup_dir=args.backup_dir,
        db_path=args.db_path,
        dry_run=args.dry_run,
        force=args.force
    )
    
    if result:
        print("\n✅ Migration completed successfully!")
        if args.dry_run:
            print("\nTo perform the actual import, run without --dry-run flag")
    else:
        print("\n❌ Migration failed!")
        exit(1)


if __name__ == '__main__':
    main()
