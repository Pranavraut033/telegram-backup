# Cloud-Aware Resume Feature

## Overview

The cloud-aware resume system enables the telegram-backup tool to track files in both local and remote storage locations, allowing efficient backup workflows where files can be moved to cloud storage without triggering re-downloads from Telegram.

## Key Features

### 1. **Location Tracking**
Files are tracked with three possible states:
- `local`: File exists only on local disk
- `remote`: File exists only in cloud storage (via rclone)
- `both`: File exists in both locations

### 2. **Hash-Based Skip Logic**
The tool skips downloading files if content with the same hash exists in either:
- Local storage (same chat or cross-chat)
- Remote storage (synced via rclone)

This uses sample-based hashing (first+last 64KB) for fast duplicate detection.

### 3. **State Synchronization**
The `sync_state.py` script scans:
- Local filesystem for existing backup files
- rclone remote listing for files in cloud storage
- Updates SQLite database with location information

### 4. **Hybrid Verification**
During backup:
- Trusts state database about remote file locations (fast)
- Validates local files on disk
- No per-message rclone checks during download (performance)

Optional explicit verification via `--sync-state` command refreshes all location data.

## Schema Changes (v2)

### Messages Table
Added columns:
- `local_path TEXT` - Local file path
- `remote_path TEXT` - Remote rclone path
- `remote_ref TEXT` - Remote reference/identifier
- `storage_status TEXT` - 'local', 'remote', or 'both'
- `local_verified_at TIMESTAMP` - Last local verification
- `remote_verified_at TIMESTAMP` - Last remote verification

### File Hashes Table
Added columns:
- `storage_location TEXT` - Location of canonical file
- `remote_ref TEXT` - Remote reference if canonical is remote

### Migration
Automatic v1→v2 migration on startup:
- Migrates existing `file_path` to `local_path`
- Sets `storage_status='local'` for existing files
- Preserves all existing functionality

## Usage Workflow

### Typical Cloud Workflow

1. **Initial Backup**
   ```bash
   python main.py
   # Select chat, download to local storage
   ```

2. **Move Files to Cloud**
   ```bash
   # Using rclone move
   python main.py  # Menu option 4
   # Or command line
   rclone move ./telegram_media_backup myremote:telegram-backup --progress
   ```

3. **Sync State**
   ```bash
   # Update database with remote locations
   python main.py --sync-state ./telegram_media_backup --remote myremote:telegram-backup
   ```

4. **Resume Backup**
   ```bash
   python main.py
   # Files already in cloud are skipped automatically
   ```

### Command-Line Usage

```bash
# Sync state from filesystem + remote
python main.py --sync-state /path/to/backup --remote myremote:telegram-backup

# Dry run to preview changes
python main.py --sync-state /path/to/backup --remote myremote:backup --dry-run

# Sync local only (no remote)
python main.py --sync-state /path/to/backup
```

### Interactive Menu

Option 6 in the main menu:
```
6. Generate/sync state from filesystem + remote
```

Prompts for:
- Local backup directory
- Remote path (optional)
- Dry run mode (yes/no)

## Technical Details

### State Database (SQLite)

Default backend with location tracking:
- Efficient for large backups
- Supports bulk updates
- Foreign key constraints
- Atomic transactions

### Legacy JSON Support

JSON backend still functions but without cloud-aware features:
- Local-only validation
- No remote location tracking
- For backward compatibility only

### Rclone Integration

New capabilities in `rclone_manager.py`:
- `list_remote_files()` - List files with metadata
- `check_remote_exists()` - Check if remote path exists
- `get_remote_size()` - Get remote file size

Supports JSON output from `rclone lsjson` with:
- File paths
- File sizes
- Modification times
- Hashes (if remote supports)

### Skip Logic Flow

During backup, for each message:
1. Check if message ID is in database
2. If found, check `storage_status`:
   - `local`: Validate local file exists
   - `remote`: Trust state (no rclone check)
   - `both`: Accept either location
3. If available anywhere → skip download
4. Otherwise → download from Telegram

### Duplicate Detection

Enhanced to work across locations:
- Hash computed after download
- Checks local hash index (same chat)
- Checks global hash index (all chats, local or remote)
- If duplicate found anywhere:
  - Delete just-downloaded file
  - Mark as duplicate
  - Skip and continue

## Performance Considerations

### Fast Operations
- State lookups via SQLite indexes
- No per-file remote verification during backup
- Bulk state updates during sync
- Sample-based hashing (first+last 64KB)

### Slow Operations
- Initial rclone remote listing (one-time per sync)
- Full directory scan during sync
- Hash computation for new files

### Optimization Tips
- Run `--sync-state` after bulk cloud transfers only
- Use sample hashing (default) instead of full hashing
- SQLite backend recommended for large backups (>10k files)

## Safety & Validation

### Data Integrity
- Local file size validation
- Hash-based duplicate detection
- State database with foreign keys
- No destructive operations without confirmation

### Recovery Options
- Dry-run mode for state sync (`--dry-run`)
- Atomic database transactions
- Corrupt DB auto-recovery
- Legacy JSON fallback

### Collision Handling
Sample hashing has ~99.9%+ accuracy but not 100%:
- Collisions unlikely but possible
- Remote-only canonicals increase blast radius
- Optional full hash verification (future enhancement)
- Document acknowledges caveat in DUPLICATE_DETECTION.md

## Limitations

### Current Scope
- SQLite backend only (v1 implementation)
- rclone-based remote access only
- No Telegram API scans during sync
- Sample-based hashing (fast but not perfect)

### Not Supported
- Other cloud backends (S3 direct, GCS, etc.)
- Automatic remote verification during backup
- Full content hashing (optional, not default)
- JSON backend cloud-awareness

## Troubleshooting

### Files Not Being Skipped

1. Check state sync ran successfully:
   ```bash
   python main.py --sync-state /path --remote myremote:path
   ```

2. Verify database has remote paths:
   ```python
   import sqlite3
   conn = sqlite3.connect('telegram_backup.db')
   cursor = conn.execute("SELECT COUNT(*) FROM messages WHERE storage_status='remote'")
   print(cursor.fetchone())
   ```

3. Check rclone remote is accessible:
   ```bash
   rclone ls myremote:telegram-backup
   ```

### State Sync Fails

- Ensure rclone is in PATH
- Verify remote path format: `remote:path/to/folder`
- Check rclone config: `rclone config show`
- Try dry-run first: `--dry-run` flag

### Database Corruption

Auto-recovery on startup:
- Corrupted DB moved to `.corrupt.<timestamp>`
- New DB created with schema v2
- Re-run sync to rebuild state

## Future Enhancements

Potential improvements:
- Optional full-hash verification mode
- Direct S3/GCS integration (no rclone)
- Periodic background remote verification
- Compression detection before hash
- Multi-remote support
- Web UI for state management

## Related Documentation

- [DUPLICATE_DETECTION.md](DUPLICATE_DETECTION.md) - Hash-based deduplication
- [CROSS_CHAT_DUPLICATES.md](CROSS_CHAT_DUPLICATES.md) - Cross-chat duplicate detection
- [SQL_MIGRATION_GUIDE.md](SQL_MIGRATION_GUIDE.md) - SQLite backend migration
- [help.txt](help.txt) - Command-line reference
- [README.md](README.md) - General usage guide

## Version History

- **v2.0**: Initial cloud-aware resume implementation
  - Schema migration v1→v2
  - Location tracking (local/remote/both)
  - Hash-based skip across locations
  - sync_state.py script
  - CLI integration (--sync-state, menu)

---

For questions or issues, see: https://github.com/Pranavraut033/telegram-backup/issues
