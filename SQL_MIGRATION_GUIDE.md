# SQLite Migration Guide

This guide explains how to migrate from JSON-based state management to SQLite for better performance and scalability.

## Overview

The Telegram Backup tool now supports both JSON (legacy) and SQLite (recommended) backends for state management. SQLite provides:

- **Better Performance**: O(1) hash lookups instead of loading entire files
- **Lower Memory Usage**: Only loads needed data, not entire state
- **Scalability**: Handles 100k+ messages without slowdown
- **Transaction Safety**: Atomic updates prevent corruption
- **Query Capabilities**: Can generate reports and analytics

## Configuration

### Environment Variables

Add these to your `.env` file:

```bash
# Enable SQLite backend (default: true)
DB_ENABLE=true

# Path to database file (default: auto-determined)
DB_PATH=/path/to/telegram_backup.db

# Fallback to JSON if SQLite fails (default: true)
DB_LEGACY_JSON_FALLBACK=true

# Backup directory for seed script (if different from default)
BACKUP_DIRECTORY=/Volumes/My Passport/telegram_media_backup
```

### Default Behavior

- **DB_ENABLE=true**: New backups use SQLite automatically
- **DB_PATH**: If not set, database is created in backup root as `telegram_backup.db`
- **DB_LEGACY_JSON_FALLBACK=true**: Falls back to JSON if database initialization fails

## Migration Process

### Step 1: Dry Run (Recommended)

First, validate your JSON state files without making changes:

```bash
python seed_from_json.py --dry-run
```

This will:
- Scan for all JSON state files
- Validate their structure
- Report what would be imported
- Show any errors

### Step 2: Import Existing State

Import your JSON state files into SQLite:

```bash
# With default settings (reads BACKUP_DIRECTORY from .env)
python seed_from_json.py

# Or specify custom paths
python seed_from_json.py --backup-dir /path/to/backup --db-path /path/to/db.sqlite

# Force overwrite if database exists
python seed_from_json.py --force
```

The script will:
- Create a new SQLite database
- Import all chat states
- Import global hash index
- Preserve all metadata (dates, sizes, hashes)
- Verify and report any errors

### Step 3: Verify Import

After import, the seed script displays a summary:

```
IMPORT SUMMARY
============================================================
Total chats found:    15
Successfully imported: 15
Failed:               0
Total messages:       12,345
Total size:           45,678,901 bytes (42.56 GB)
============================================================
```

### Step 4: Resume Backups

Your next backup will automatically use the SQLite backend:

```bash
python main.py
```

The tool will detect the database and use it instead of JSON files.

## Dual-Mode Operation

### How It Works

- `StateManager` checks `config.DB_ENABLE` on initialization
- If enabled, attempts to open SQLite database
- Falls back to JSON if database fails and `DB_LEGACY_JSON_FALLBACK=true`
- All public API methods work identically regardless of backend

### JSON State Files After Migration

After migrating to SQLite:
- JSON state files are **not deleted** automatically
- They remain as a backup
- New state changes only update the database
- You can safely delete JSON files once verified SQLite works

### Exporting from SQLite to JSON

To export database back to JSON (for backup/portability):

```python
from state_db import DatabaseManager

db = DatabaseManager('/path/to/telegram_backup.db')
exported_files = db.export_all_to_json('/path/to/output')
print(f"Exported {len(exported_files)} files")
db.close()
```

## Performance Comparison

### JSON Backend
- **Load time**: 2-5 seconds for 10k messages
- **Memory**: 100MB+ for large backups
- **Duplicate lookup**: O(n) linear scan
- **Write time**: 1-2 seconds per save

### SQLite Backend
- **Load time**: <100ms (only metadata)
- **Memory**: ~10MB baseline + active data
- **Duplicate lookup**: O(1) indexed query
- **Write time**: <10ms per transaction

## Troubleshooting

### Import Errors

**"No state files found"**
- Check `BACKUP_DIRECTORY` in `.env`
- Verify JSON files exist: `ls -la /path/to/backup/.backup_state_*.json`

**"Database already exists"**
- Use `--force` to overwrite: `python seed_from_json.py --force`
- Or manually delete: `rm /path/to/telegram_backup.db`

**"Failed to import chat"**
- Run with `--dry-run` to see specific errors
- Check JSON file is valid: `python -m json.tool state_file.json`

### Runtime Issues

**"Failed to initialize database"**
- Check file permissions: `ls -l telegram_backup.db`
- Verify disk space: `df -h`
- Check SQLite is available: `python -c "import sqlite3; print(sqlite3.version)"`

**"Falling back to JSON backend"**
- Set `DB_LEGACY_JSON_FALLBACK=false` to force SQLite
- Check logs for specific error message
- Verify database file is not corrupted

### Corruption Recovery

If database becomes corrupted:

```bash
# 1. Export to JSON for backup
python -c "from state_db import DatabaseManager; db = DatabaseManager('telegram_backup.db'); db.export_all_to_json('backup_json'); db.close()"

# 2. Delete corrupted database
rm telegram_backup.db

# 3. Re-import from JSON
python seed_from_json.py
```

## Database Maintenance

### Vacuum (Optimize)

The database is automatically vacuumed after import. For manual optimization:

```python
from state_db import DatabaseManager

db = DatabaseManager('/path/to/telegram_backup.db')
db.vacuum()
db.close()
```

### Statistics

View comprehensive database statistics:

```python
from state_db import DatabaseManager

db = DatabaseManager('/path/to/telegram_backup.db')
stats = db.get_stats_summary()
print(stats)
db.close()
```

### Cleanup Orphaned Records

Remove orphaned records and fix inconsistencies:

```python
from state_db import DatabaseManager

db = DatabaseManager('/path/to/telegram_backup.db')
cleaned = db.cleanup_orphaned_records()
print(f"Cleaned {sum(cleaned.values())} orphaned records")
db.close()
```

### Rebuild Hash Index

If hash index becomes inconsistent:

```python
from state_db import DatabaseManager

db = DatabaseManager('/path/to/telegram_backup.db')
count = db.rebuild_hash_index_from_messages()
print(f"Rebuilt hash index with {count} entries")
db.close()
```

## Schema Information

### Database Location

Default: `<backup_directory>/telegram_backup.db`

### Tables

- **chats**: Chat metadata (name, dates, stats)
- **messages**: Downloaded messages with file info
- **file_hashes**: Global hash index for duplicates
- **duplicates**: Duplicate message mappings
- **message_status**: Message status (downloaded/skipped/failed)
- **schema_version**: Schema version tracking

### Indexes

- Sample hash, file size, file path for fast lookups
- Composite indexes for duplicate detection
- Foreign keys enforce referential integrity

## Backward Compatibility

### Legacy JSON Support

- Set `DB_ENABLE=false` to force JSON backend
- Existing JSON-only installations continue to work
- New features may be SQL-only

### Migration Timeline

- **v1.x**: Both backends supported
- **v2.x**: SQLite becomes default
- **v3.x+**: JSON may be deprecated (export available)

## Best Practices

1. **Always run dry-run first** before importing
2. **Keep JSON backups** until SQLite is verified
3. **Use version control** for `.env` configuration
4. **Regular database exports** for portability
5. **Monitor database size** and vacuum periodically
6. **Test restores** on non-production data first

## Support

For issues or questions:
1. Check this guide and error messages
2. Run diagnostics: `python seed_from_json.py --dry-run`
3. Review logs with `DEBUG=true` in config
4. Open an issue with error details and database stats
