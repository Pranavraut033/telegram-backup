# Quick Start: Duplicate Detection Features

## What's New?

Your telegram-backup tool now **automatically prevents duplicate downloads** and can **consolidate existing duplicates** to save space!

## Automatic Duplicate Prevention ✨

**Just run normally - it's automatic!**

```bash
python main.py
```

When backing up:
- ✅ Same file in multiple messages? Downloads once
- ✅ Forwarded media? Skips duplicates
- ✅ Cross-posted content? Saves bandwidth
- ✅ Same file in different chats? Detects across all chats!
- ✅ Resume interrupted backup? No re-downloads

**How it works:**
- Computes a "fingerprint" (hash) of each downloaded file
- Before downloading, checks if file with same fingerprint exists **anywhere in your backups**
- If found (even in a different chat), skips download and shows which chat has the file
- **Result:** Faster backups, less storage used, works across all chats

## Find Duplicates in Existing Backups 🔍

Already have backups with duplicates? Clean them up!

```bash
python main.py --consolidate-duplicates /path/to/backup
```

**What happens:**
1. Scans all files in backup folder
2. Finds files with identical content (even if different names)
3. Keeps one copy of each unique file
4. Moves duplicates to `duplicates/` subfolder
5. Reports space saved

**Example output:**
```
🔍 Scanning for duplicate files in: /backups/MyChat
Found 1,234 files

Found 3 group(s) of duplicate files

Group 1: 3 copies of photo_2024.jpg
  Keeping: MyChat/photo_2024.jpg
  → Moved: Topic_1/photo_2024_1.jpg
  → Moved: Topic_2/photo_2024_2.jpg

✓ Consolidation complete!
  Files scanned: 1,234
  Duplicates moved: 5
  Space saved: 45.2 MB
```

## Safe to Use? ✅

**Yes!** The tool:
- Never modifies original files
- Only moves duplicates (doesn't delete)
- Preserves folder structure
- Updates tracking properly
- Can be safely interrupted

**Duplicate folder** keeps everything in case you need to restore.

## When to Use Consolidation

- After backing up multiple chats/groups
- If you've forwarded files between chats
- When storage space is limited
- Before archiving backups

## Tips

1. **Test first**: Run on a copy of your backup folder
2. **Check duplicates folder**: Verify moved files are truly duplicates
3. **Keep backups**: Always have a backup of important data
4. **Run periodically**: After major backup sessions

## Need More Details?

See `DUPLICATE_DETECTION.md` for comprehensive documentation.

## Questions?

**Q: Will this break my existing backups?**
A: No. Existing files work normally. Feature is backward compatible.

**Q: Can I undo consolidation?**
A: Yes. Just move files back from `duplicates/` folder.

**Q: How accurate is duplicate detection?**
A: >99.9% accurate using cryptographic hashing (SHA-256).

**Q: Does this slow down backups?**
A: Minimal (~5-10ms per file). Saves time by skipping duplicate downloads.

---

**Enjoy faster, more efficient Telegram backups! 🚀**
