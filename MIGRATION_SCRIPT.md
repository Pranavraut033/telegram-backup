# Migration Script - Hash-Based Duplicate Detection

## Overview

The `migrate_to_hash_detection.py` script helps you upgrade existing telegram-backup folders to use the new hash-based duplicate detection system.

## What It Does

1. **Scans all existing files** in your backup folder
2. **Computes sample hashes** (first+last 64KB) for each file
3. **Populates chat state files** with hash information for tracked files only
4. **Skips untracked files** and saves them to `migration_skipped_files.json`
5. **Preserves existing message IDs** from state files
6. **Builds global hash index** for cross-chat duplicate detection
7. **Identifies duplicates** across all tracked files
8. **Moves duplicates** to `duplicates/` folder (optional)
9. **Updates all state files** with new paths

### Important: Message ID Handling

- **Files with existing state entries**: Message IDs are **preserved** exactly as they are, and hashes are added
- **Files without state entries**: **Skipped completely** - not added to state, not tracked for duplicates
- **Skipped files report**: A JSON file (`migration_skipped_files.json`) is created listing all untracked files
- **Recommendation**: Run this script on backups that have state files (`.backup_state_*.json`) for proper tracking

## When to Use

- After upgrading to the version with hash-based duplicate detection
- To consolidate existing backups and remove duplicates
- To prepare old backups for the new duplicate detection system
- When state files are missing or corrupted

## Usage

### Basic Usage

```bash
python migrate_to_hash_detection.py
```

The script will:
- Read `BACKUP_DIR` from your `.env` file
- Or prompt you to enter the backup directory path

### Prerequisites

1. Ensure you have the virtual environment activated:
   ```bash
   source venv/bin/activate  # macOS/Linux
   # or
   venv\Scripts\activate  # Windows
   ```

2. Make sure `BACKUP_DIR` is set in `.env`:
   ```env
   BACKUP_DIR=/path/to/your/backups
   ```

3. Backup your data (optional but recommended):
   ```bash
   cp -r /path/to/backups /path/to/backups.backup
   ```

## What to Expect

### Step 1: Discovery
```
🔎 Discovering chat directories...
✓ Found 5 chat director(ies)
```

### Step 2: Processing Each Chat
```
📂 Processing: FamilyChat
  Computing hashes...
  ✓ Hashed 234 file(s)
  Updating state file...
  ✓ Updated 230 existing entries, skipped 4 untracked files
```

**Note:** "Updated" means files already tracked with proper message IDs. "Skipped" means files found on disk that weren't in the state file (these are NOT added to state).

### Step 3: Building Global Index
```
🌐 Building global hash index...
✓ Global index built with 1,156 unique file(s)

📝 Saved 15 skipped file(s) to: migration_skipped_files.json
```

### Step 4: Finding Duplicates
```
🔍 Scanning for duplicates across all chats...
✓ Scanned 1,234 files
✓ Found 15 group(s) with duplicates

📦 Found 78 duplicate file(s) to consolidate
```

### Step 5: Moving Duplicates (Optional)
```
Move duplicates to 'duplicates' folder? (y/n): y

🚚 Moving duplicates...

Group 1: 3 copies (2.3 MB)
  Keeping: FamilyChat/photo.jpg
  → Moved: WorkGroup/photo_1.jpg
  → Moved: FriendsChat/photo_2.jpg

...

✅ Migration complete!
  • Duplicates moved: 78
  • Space saved: 145.6 MB
  • Duplicates folder: /backups/duplicates
```

## Performance

### Speed
- **Hashing**: ~100-500 files/second (depends on file sizes and disk speed)
- **10,000 files**: ~30-60 seconds for hashing
- **Moving files**: Nearly instant (same filesystem)

### Memory
- **Typical**: <50 MB RAM usage
- **Large backups** (100k+ files): <500 MB RAM

## Safety Features

### Non-Destructive
- Original files are **moved**, not deleted
- All moved files go to `duplicates/` folder
- Folder structure is preserved in duplicates folder
- State files are backed up automatically

### Reversible
You can undo the migration by:
1. Moving files back from `duplicates/` folder
2. Deleting the state files
3. Re-running the migration script

### Validation
- Skips empty files (0 bytes)
- Handles permission errors gracefully
- Reports errors for problematic files
- Continues processing even if individual files fail

## Output Files

### Skipped Files JSON
Location: `<backup_dir>/migration_skipped_files.json`

Contains:
- List of all files found on disk but not tracked in state
- Each entry includes:
  - `chat`: Chat name
  - `path`: Absolute file path
  - `relative_path`: Path relative to backup directory
  - `size`: File size in bytes
  - `sample_hash`: Computed sample hash
  - `reason`: Why it was skipped (always "not_in_state")
- Migration timestamp
- Total count

Example:
```json
{
  "migration_date": "2026-02-09T10:30:45.123456",
  "total_skipped": 15,
  "skipped_files": [
    {
      "chat": "FamilyChat",
      "path": "/backups/FamilyChat/unknown_photo.jpg",
      "relative_path": "FamilyChat/unknown_photo.jpg",
      "size": 245678,
      "sample_hash": "abc123...",
      "reason": "not_in_state"
    }
  ]
}
```

### Global State File
Location: `<backup_dir>/.backup_state_global.json`

Contains:
- Global hash index (size:hash → file_path)
- Timestamps
- Version info

### Chat State Files
Location: `<backup_dir>/.backup_state_<chat_hash>.json`

Updated with:
- Sample hashes for tracked files only
- Corrected file sizes
- Local hash index (tracked files only)

### Duplicates Folder
Location: `<backup_dir>/duplicates/`

Structure:
```
duplicates/
├── ChatA/
│   └── duplicate_file.jpg
├── ChatB/
│   └── another_duplicate.mp4
└── ChatC/
    └── Topic1/
        └── nested_duplicate.png
```

Preserves original folder structure!

## Troubleshooting

### "No chat directories found"
**Cause**: Backup directory is empty or has no valid chat folders
**Solution**: Check that you provided the correct backup directory path

### "Error processing file: Permission denied"
**Cause**: Insufficient permissions to read some files
**Solution**: Run with appropriate permissions or skip those files

### "Error during migration"
**Cause**: Unexpected error (corrupted files, disk full, etc.)
**Solution**: Check the error message and stack trace for details

### Files Not Hashed
**Cause**: Files might be:
- Empty (0 bytes) - automatically skipped
- Corrupted - error logged
- In duplicates folder - intentionally skipped

### State File Issues
**Cause**: State file corrupted or invalid JSON
**Solution**: 
1. Backup the state file
2. Delete it
3. Re-run migration (will create new state)

### What About Untracked Files?
**Cause**: Files were not tracked in state before migration
**Impact**: These files are **skipped** and listed in `migration_skipped_files.json`
**Solution**: 
- Review the JSON file to see which files were skipped
- If these files are important, you can:
  1. Re-download them using the backup tool (recommended)
  2. Manually add them to state with proper message IDs (advanced)
- Untracked files won't participate in duplicate detection

### Why Were Some Files Skipped?
**Cause**: These are placeholder IDs for files not previously tracked in state
**Impact**: Files are not tracked and won't participate in duplicate detection
**Solution**: Review `migration_skipped_files.json` to identify them, then re-download if needed

### What's in migration_skipped_files.json?
This file contains detailed information about every file that was skipped during migration:
- **Total count** of skipped files
- **Per-file details**: chat name, paths, size, hash, and reason
- **Migration timestamp** for tracking
- Use this to identify files that need to be re-downloaded

## Examples

### Example 1: Clean Migration
```bash
$ python migrate_to_hash_detection.py

================================================================================
Telegram Backup - Hash Detection Migration Script
================================================================================

📁 Backup directory: /Users/john/telegram-backups

🔎 Discovering chat directories...
✓ Found 3 chat director(ies)

📂 Processing: FamilyChat
  Computing hashes...
  ✓ Hashed 156 file(s)
  Updating state file...
  ✓ Updated 156 existing entries, skipped 0 untracked files

📂 Processing: WorkGroup
  Computing hashes...
  ✓ Hashed 89 file(s)
  Updating state file...
  ✓ Updated 85 existing entries, skipped 4 untracked files

📂 Processing: FriendsChat
  Computing hashes...
  ✓ Hashed 234 file(s)
  Updating state file...
  ✓ Updated 234 existing entries, skipped 0 untracked files

🌐 Building global hash index...
✓ Global index built with 456 unique file(s)

📝 Saved 4 skipped file(s) to: migration_skipped_files.json

🔍 Scanning for duplicates across all chats...
✓ Scanned 479 files
✓ Found 8 group(s) with duplicates

📦 Found 23 duplicate file(s) to consolidate

Move duplicates to 'duplicates' folder? (y/n): y

🚚 Moving duplicates...
[... duplicate groups listed ...]

✅ Migration complete!
  • Duplicates moved: 23
  • Space saved: 45.2 MB

================================================================================
Migration Summary:
  • Chats processed: 3
  • Files tracked in state: 475
  • Files skipped (not in state): 4
  • Unique files: 456
  • State files updated: 3 + 1 global
  • Skipped files JSON: migration_skipped_files.json
================================================================================

✨ Your backups are now using hash-based duplicate detection!
   Future downloads will automatically skip duplicates.
   ⚠️  4 untracked files were skipped (see migration_skipped_files.json)
```

### Example 2: No Duplicates
```bash
🔍 Scanning for duplicates across all chats...
✓ Scanned 1,234 files
✓ Found 0 group(s) with duplicates

✅ No duplicates found! All files are unique.

✨ Your backups are now using hash-based duplicate detection!
```

### Example 3: Skip Consolidation
```bash
📦 Found 50 duplicate file(s) to consolidate

Move duplicates to 'duplicates' folder? (y/n): n

✓ Skipped duplicate consolidation

✨ Your backups are now using hash-based duplicate detection!
```

## After Migration

### What Changes
✅ All tracked files have sample hashes computed
✅ Global hash index is built from tracked files only
✅ Each chat has updated state file
✅ Duplicates moved to `duplicates/` folder (if chosen)
✅ Untracked files listed in `migration_skipped_files.json`

### What Stays the Same
✅ Original files remain in place (except duplicates)
✅ Folder structure unchanged
✅ No re-downloading needed

### Next Steps
1. Run `python main.py` to continue backing up
2. New downloads will automatically skip duplicates
3. Cross-chat duplicate detection works immediately

## Cleanup

### Verify Migration
After migration, verify everything works:
```bash
python main.py --debug
```

### Remove Duplicates Folder
If satisfied, you can delete the duplicates folder:
```bash
rm -rf /path/to/backups/duplicates
```

**Warning**: Only do this after verifying no important unique files were incorrectly moved!

## Best Practices

### Before Migration
1. ✅ Backup your entire backup folder
2. ✅ Ensure enough disk space (same as current backup size)
3. ✅ Close any programs accessing the backup files
4. ✅ Test on a small backup first

### During Migration
1. ✅ Don't interrupt the process (can corrupt state files)
2. ✅ Monitor the output for errors
3. ✅ Note any files that failed to process

### After Migration
1. ✅ Verify state files were created/updated
2. ✅ Check that duplicates folder contains expected files
3. ✅ Run a test backup to confirm everything works
4. ✅ Review duplicates before deleting duplicates folder

## Script Options

Currently the script is interactive. For automated workflows, you can modify it to accept command-line arguments:

```python
# Potential additions (not yet implemented):
# --backup-dir <path>      Specify backup directory
# --skip-duplicates        Skip duplicate consolidation
# --dry-run               Show what would be done without changes
# --quiet                 Minimal output
```

## Technical Details

### Algorithm
1. Iterate through all chat directories
2. For each file:
   - Compute SHA-256 hash of first+last 64KB
   - Store (size, hash) tuple
3. Update chat state with hashes
4. Build global index (first occurrence of each unique file)
5. Group files by (size, hash)
6. Identify groups with >1 file
7. Move all but first file to duplicates folder
8. Update state files with new paths

### Performance Optimization
- Streaming I/O (only reads 128KB per file)
- In-memory hash tables for fast lookup
- Batch file operations
- Skip already processed files

## Support

For issues or questions:
1. Check the error message and stack trace
2. Review this README
3. Check DUPLICATE_DETECTION.md for details
4. Open an issue on GitHub

---

**Ready to migrate?** Run `python migrate_to_hash_detection.py` to get started! 🚀
