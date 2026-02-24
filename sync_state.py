#!/usr/bin/env python3
"""
Sync backup state from filesystem and rclone remote.
Scans local files and remote listing to build/update state database.
"""
import os
import sys
import argparse
from collections import defaultdict
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rclone_manager import RcloneManager
from state_db import DatabaseManager
import config
import utils

console = Console()


def extract_message_id_from_filename(filename):
    """
    Extract message ID from filename.
    Assumes format: <message_id>_<description>.<ext> or <message_id>.<ext>
    """
    try:
        # Remove extension
        name_without_ext = os.path.splitext(filename)[0]
        # Try to extract leading number
        parts = name_without_ext.split('_')
        msg_id = int(parts[0])
        return msg_id
    except (ValueError, IndexError):
        return None


def scan_local_files(backup_dir, chat_name):
    """
    Scan local backup directory for files.
    
    Returns:
        List of dicts with keys: message_id, filename, file_path, file_size, sample_hash
    """
    records = []

    candidate_dirs = []
    for candidate in (chat_name, utils.sanitize_dirname(chat_name)):
        candidate_path = os.path.join(backup_dir, candidate)
        if candidate_path not in candidate_dirs:
            candidate_dirs.append(candidate_path)

    seen_paths = set()
    for chat_dir in candidate_dirs:
        if not os.path.exists(chat_dir):
            continue

        for root, _, files in os.walk(chat_dir):
            for filename in files:
                if filename.startswith('.'):
                    continue

                file_path = os.path.join(root, filename)
                if file_path in seen_paths:
                    continue
                seen_paths.add(file_path)

                if not os.path.isfile(file_path):
                    continue

                try:
                    file_size = os.path.getsize(file_path)
                    if file_size == 0:
                        continue

                    # Extract message ID from filename (optional)
                    message_id = extract_message_id_from_filename(filename)
                    if not message_id:
                        # Some backups don't include message IDs in filenames.
                        # Keep record and resolve message_id from state using file paths later.
                        try:
                            message_id = int(os.path.splitext(filename)[0])
                        except ValueError:
                            message_id = None

                    # Compute sample hash
                    sample_hash = utils.sample_hash_file(file_path)

                    records.append({
                        'message_id': message_id,
                        'filename': filename,
                        'file_path': file_path,
                        'local_path': file_path,
                        'file_size': file_size,
                        'sample_hash': sample_hash
                    })
                except Exception as e:
                    console.print(f"[yellow]Warning: Error processing {filename}: {e}[/yellow]")
                    continue
    
    return records


def scan_remote_files(rclone_manager, remote_path, chat_name, remote_chat_folders=None):
    """
    Scan rclone remote for files.
    
    Returns:
        List of dicts with keys: message_id, filename, remote_path, file_size, hash
    """
    records = []
    
    candidate_folders = []
    for candidate in (chat_name, utils.sanitize_dirname(chat_name)):
        if candidate and candidate not in candidate_folders:
            candidate_folders.append(candidate)

    if remote_chat_folders is not None:
        candidate_folders = [name for name in candidate_folders if name in remote_chat_folders]

    for folder_name in candidate_folders:
        remote_chat_path = f"{remote_path}/{folder_name}".rstrip('/')

        try:
            files = rclone_manager.list_remote_files(remote_chat_path, recursive=True)

            for file_info in files:
                filename = file_info['name']
                file_path = file_info['path']
                file_size = file_info['size']

                # Extract message ID (optional)
                message_id = extract_message_id_from_filename(filename)
                if not message_id:
                    try:
                        message_id = int(os.path.splitext(filename)[0])
                    except ValueError:
                        message_id = None

                records.append({
                    'message_id': message_id,
                    'filename': filename,
                    'remote_path': f"{remote_chat_path}/{file_path}",
                    'remote_ref': file_path,
                    'file_size': file_size,
                    'sample_hash': file_info.get('hash')  # May be None if remote doesn't support hashing
                })
        except Exception as e:
            console.print(f"[yellow]Warning: Could not scan remote path {remote_chat_path}: {e}[/yellow]")
    
    return records


def sync_chat_state(db, chat_id, local_records, remote_records):
    """
    Merge local and remote records and update database.
    
    Returns:
        Dict with stats: local_updated, remote_updated, both_updated
    """
    stats = {'local_updated': 0, 'remote_updated': 0, 'both_updated': 0}
    
    # Build message ID maps
    local_map = {r['message_id']: r for r in local_records if r.get('message_id') is not None}
    remote_map = {r['message_id']: r for r in remote_records if r.get('message_id') is not None}
    
    all_msg_ids = set(local_map.keys()) | set(remote_map.keys())
    
    for msg_id in all_msg_ids:
        local_rec = local_map.get(msg_id)
        remote_rec = remote_map.get(msg_id)
        
        if local_rec and remote_rec:
            # File exists in both locations
            db.add_message(
                chat_id=chat_id,
                message_id=msg_id,
                filename=local_rec['filename'],
                file_path=local_rec['file_path'],
                file_size=local_rec['file_size'],
                sample_hash=local_rec.get('sample_hash') or remote_rec.get('sample_hash'),
                local_path=local_rec['local_path'],
                remote_path=remote_rec['remote_path'],
                remote_ref=remote_rec['remote_ref'],
                storage_status='both'
            )
            db.set_message_status(chat_id, msg_id, 'downloaded', 'available in local and remote')
            stats['both_updated'] += 1
        elif local_rec:
            # Local only
            db.add_message(
                chat_id=chat_id,
                message_id=msg_id,
                filename=local_rec['filename'],
                file_path=local_rec['file_path'],
                file_size=local_rec['file_size'],
                sample_hash=local_rec.get('sample_hash'),
                local_path=local_rec['local_path'],
                storage_status='local'
            )
            db.set_message_status(chat_id, msg_id, 'downloaded', 'available locally')
            stats['local_updated'] += 1
        elif remote_rec:
            # Remote only
            db.add_message(
                chat_id=chat_id,
                message_id=msg_id,
                filename=remote_rec['filename'],
                file_size=remote_rec['file_size'],
                sample_hash=remote_rec.get('sample_hash'),
                remote_path=remote_rec['remote_path'],
                remote_ref=remote_rec['remote_ref'],
                storage_status='remote'
            )
            db.set_message_status(chat_id, msg_id, 'downloaded', 'available remotely')
            stats['remote_updated'] += 1
    
    return stats


def sync_hash_index(db, all_records):
    """
    Build global hash index from all records.
    
    Returns:
        Number of hash entries created
    """
    hash_records = []
    
    for rec in all_records:
        if rec.get('sample_hash') and rec.get('file_size', 0) > 0:
            hash_records.append({
                'file_size': rec['file_size'],
                'sample_hash': rec['sample_hash'],
                'file_path': rec.get('file_path') or rec.get('local_path'),
                'message_id': rec.get('message_id'),
                'chat_id': rec.get('chat_id'),
                'storage_location': rec.get('storage_status', 'local'),
                'remote_ref': rec.get('remote_ref')
            })
    
    return db.bulk_register_hashes(hash_records)


def _norm_path(path):
    """Normalize path for cross-platform/state matching."""
    if not path:
        return None
    return os.path.normpath(str(path)).replace('\\', '/').strip()


def _build_basename_index(paths_to_msg_ids):
    """Build basename -> unique message_id map from a path index."""
    grouped = defaultdict(set)
    for path, msg_id in paths_to_msg_ids.items():
        base = os.path.basename(path)
        if base:
            grouped[base].add(msg_id)

    unique_map = {}
    for base, msg_ids in grouped.items():
        if len(msg_ids) == 1:
            unique_map[base] = next(iter(msg_ids))
    return unique_map


def resolve_message_ids_from_state(local_records, remote_records, existing_messages):
    """
    Resolve missing message IDs using existing state paths.

    Matching priority:
      1) exact local_path/file_path match (local records)
      2) exact remote_path/remote_ref match (remote records)
      3) unique basename match within chat scope
    """
    local_path_to_msg = {}
    remote_path_to_msg = {}
    remote_ref_to_msg = {}

    for row in existing_messages:
        msg_id = row.get('message_id')
        if msg_id is None:
            continue

        local_path = _norm_path(row.get('local_path') or row.get('file_path'))
        remote_path = _norm_path(row.get('remote_path'))
        remote_ref = _norm_path(row.get('remote_ref'))

        if local_path:
            local_path_to_msg[local_path] = msg_id
        if remote_path:
            remote_path_to_msg[remote_path] = msg_id
        if remote_ref:
            remote_ref_to_msg[remote_ref] = msg_id

    local_basename_to_msg = _build_basename_index(local_path_to_msg)
    remote_basename_to_msg = _build_basename_index({**remote_path_to_msg, **remote_ref_to_msg})

    resolved_local = 0
    resolved_remote = 0

    for rec in local_records:
        if rec.get('message_id') is not None:
            continue

        local_path = _norm_path(rec.get('local_path') or rec.get('file_path'))
        msg_id = local_path_to_msg.get(local_path)

        if msg_id is None and rec.get('filename'):
            msg_id = local_basename_to_msg.get(rec['filename'])

        if msg_id is not None:
            rec['message_id'] = msg_id
            resolved_local += 1

    for rec in remote_records:
        if rec.get('message_id') is not None:
            continue

        remote_path = _norm_path(rec.get('remote_path'))
        remote_ref = _norm_path(rec.get('remote_ref'))

        msg_id = remote_path_to_msg.get(remote_path)
        if msg_id is None and remote_ref is not None:
            msg_id = remote_ref_to_msg.get(remote_ref)

        if msg_id is None and rec.get('filename'):
            msg_id = remote_basename_to_msg.get(rec['filename'])

        if msg_id is not None:
            rec['message_id'] = msg_id
            resolved_remote += 1

    unresolved_local = sum(1 for rec in local_records if rec.get('message_id') is None)
    unresolved_remote = sum(1 for rec in remote_records if rec.get('message_id') is None)

    return {
        'resolved_local': resolved_local,
        'resolved_remote': resolved_remote,
        'unresolved_local': unresolved_local,
        'unresolved_remote': unresolved_remote,
    }


def discover_local_chats(backup_dir):
    """Discover chat folders in local backup directory."""
    chats = set()
    if not os.path.exists(backup_dir):
        return chats

    for item in os.listdir(backup_dir):
        item_path = os.path.join(backup_dir, item)
        if os.path.isdir(item_path) and not item.startswith('.'):
            chats.add(item)

    return chats


def discover_remote_chats(rclone_manager, remote_path):
    """Discover top-level chat folders in remote backup path."""
    chats = set()
    if not rclone_manager or not remote_path:
        return chats

    try:
        for folder in rclone_manager.list_remote_dirs(remote_path, recursive=False):
            folder_name = folder.strip('/').split('/')[-1]
            if folder_name and not folder_name.startswith('.'):
                chats.add(folder_name)
    except Exception as e:
        console.print(f"[yellow]Warning: Could not discover remote chat folders under {remote_path}: {e}[/yellow]")

    return chats


def resolve_chat_id(db, existing_chats_by_name, chat_name):
    """Resolve existing chat_id by name, or create chat record if missing."""
    existing = existing_chats_by_name.get(chat_name)
    if existing:
        return existing['chat_id']

    chat_hash = utils.sanitize_dirname(chat_name)
    return db.get_or_create_chat(chat_name, chat_hash)


def sync_state(backup_dir, remote_path=None, dry_run=False):
    """
    Main sync function: scan local and remote, update state database.
    
    Args:
        backup_dir: Local backup directory path
        remote_path: rclone remote path (optional)
        dry_run: If True, show what would be done without making changes
    """
    console.print(f"\n[bold cyan]🔄 Syncing backup state...[/bold cyan]")
    console.print(f"   Local backup: {backup_dir}")
    if remote_path:
        console.print(f"   Remote path: {remote_path}")
    console.print()
    
    # Initialize database
    db_path = config.DB_PATH or os.path.join(backup_dir, "telegram_backup.db")
    db = DatabaseManager(db_path)
    
    # Check if remote is available
    rclone_manager = None
    if remote_path:
        rclone_manager = RcloneManager()
        if not rclone_manager.is_available():
            console.print("[yellow]⚠️  rclone not found, skipping remote sync[/yellow]")
            rclone_manager = None
    
    # Discover chats from local + remote + DB state
    local_chats = discover_local_chats(backup_dir)
    remote_chats = discover_remote_chats(rclone_manager, remote_path) if rclone_manager and remote_path else set()
    existing_db_chats = db.get_all_chats()

    chats_to_sync = set(local_chats) | set(remote_chats) | {chat['chat_name'] for chat in existing_db_chats}

    if not chats_to_sync:
        console.print("[yellow]No chats found in local folders, remote folders, or state database[/yellow]")
        return

    chats_to_sync = sorted(chats_to_sync)
    existing_chats_by_name = {chat['chat_name']: chat for chat in existing_db_chats}

    console.print(
        f"[cyan]Found {len(chats_to_sync)} chat(s) to sync "
        f"(local: {len(local_chats)}, remote: {len(remote_chats)}, db: {len(existing_db_chats)})[/cyan]\n"
    )
    
    # Sync each chat
    total_stats = {
        'chats': 0,
        'local_files': 0,
        'remote_files': 0,
        'total_messages': 0,
        'resolved_by_path': 0,
        'unresolved_without_message_id': 0,
        'missing_marked': 0,
        'hashes_indexed': 0
    }
    
    all_records = []
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        console=console
    ) as progress:
        task = progress.add_task("Syncing chats...", total=len(chats_to_sync))
        
        for chat_name in chats_to_sync:
            progress.update(task, description=f"Syncing: {chat_name[:30]}...")
            
            # Get or create chat in database
            chat_id = resolve_chat_id(db, existing_chats_by_name, chat_name)
            
            # Scan local files
            local_records = scan_local_files(backup_dir, chat_name)
            total_stats['local_files'] += len(local_records)
            
            # Scan remote files
            remote_records = []
            if rclone_manager and remote_path:
                remote_records = scan_remote_files(
                    rclone_manager,
                    remote_path,
                    chat_name,
                    remote_chat_folders=remote_chats
                )
                total_stats['remote_files'] += len(remote_records)
            
            # Merge and update state
            if not dry_run:
                existing_messages = db.get_all_messages(chat_id)

                resolution_stats = resolve_message_ids_from_state(
                    local_records,
                    remote_records,
                    existing_messages
                )
                total_stats['resolved_by_path'] += (
                    resolution_stats['resolved_local'] + resolution_stats['resolved_remote']
                )
                total_stats['unresolved_without_message_id'] += (
                    resolution_stats['unresolved_local'] + resolution_stats['unresolved_remote']
                )

                chat_stats = sync_chat_state(db, chat_id, local_records, remote_records)
                total_stats['total_messages'] += sum(chat_stats.values())

                # Reconcile stale rows that were previously present but now missing in both local and remote
                seen_msg_ids = {
                    r['message_id']
                    for r in (local_records + remote_records)
                    if r.get('message_id') is not None
                }
                for row in existing_messages:
                    msg_id = row['message_id']
                    if msg_id in seen_msg_ids:
                        continue
                    if db.mark_message_missing(chat_id, msg_id):
                        total_stats['missing_marked'] += 1
                
                # Track for hash index
                for rec in local_records + remote_records:
                    if rec.get('message_id') is None:
                        continue
                    rec['chat_id'] = chat_id
                    all_records.append(rec)
                
                # Update chat stats
                db.update_chat_stats(
                    chat_id,
                    total_files=len(local_records) + len(remote_records),
                    total_bytes=sum(r.get('file_size', 0) for r in local_records + remote_records)
                )
            
            total_stats['chats'] += 1
            progress.advance(task)
    
    # Build hash index
    if not dry_run:
        console.print("\n[cyan]Building global hash index...[/cyan]")
        hashes_indexed = db.rebuild_hash_index_from_messages()
        total_stats['hashes_indexed'] = hashes_indexed
    
    # Print summary
    console.print("\n[bold green]✓ State sync complete![/bold green]")
    console.print(f"   Chats synced: {total_stats['chats']}")
    console.print(f"   Local files: {total_stats['local_files']}")
    console.print(f"   Remote files: {total_stats['remote_files']}")
    console.print(f"   Total messages: {total_stats['total_messages']}")
    console.print(f"   Resolved by state path: {total_stats['resolved_by_path']}")
    console.print(f"   Unresolved (no message id): {total_stats['unresolved_without_message_id']}")
    console.print(f"   Missing marked unavailable: {total_stats['missing_marked']}")
    console.print(f"   Hash index entries: {total_stats['hashes_indexed']}")
    console.print()
    
    if dry_run:
        console.print("[yellow]Dry run complete - no changes were made[/yellow]")
    else:
        console.print(f"[dim]State database: {db_path}[/dim]")
    console.print()


def main():
    """Entry point"""
    parser = argparse.ArgumentParser(
        description="Sync telegram backup state from filesystem and rclone remote"
    )
    parser.add_argument(
        'backup_dir',
        help='Local backup directory path'
    )
    parser.add_argument(
        '--remote',
        dest='remote_path',
        help='rclone remote path (e.g., myremote:telegram-backup)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making changes'
    )
    
    args = parser.parse_args()
    
    if not os.path.isdir(args.backup_dir):
        console.print(f"[bold red]Error: '{args.backup_dir}' is not a valid directory[/bold red]")
        sys.exit(1)
    
    try:
        sync_state(args.backup_dir, args.remote_path, args.dry_run)
    except KeyboardInterrupt:
        console.print("\n[yellow]Sync cancelled by user[/yellow]")
        sys.exit(1)
    except Exception as e:
        console.print(f"\n[bold red]Error: {e}[/bold red]")
        if config.DEBUG:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
