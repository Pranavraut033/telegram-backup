# Telegram Media Backup

[![Build](https://github.com/Pranavraut033/telegram-backup/actions/workflows/build.yml/badge.svg?branch=main)](https://github.com/Pranavraut033/telegram-backup/actions/workflows/build.yml) [![Release](https://github.com/Pranavraut033/telegram-backup/actions/workflows/release.yml/badge.svg?branch=main)](https://github.com/Pranavraut033/telegram-backup/actions/workflows/release.yml) [![Python](https://img.shields.io/badge/python-3.7%2B-blue)](https://www.python.org/) [![Issues](https://img.shields.io/github/issues/Pranavraut033/telegram-backup)](https://github.com/Pranavraut033/telegram-backup/issues)

CLI tool for backing up media from Telegram chats and groups using the Telegram Client API.

---

## Setup

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Get API credentials** from https://my.telegram.org/apps

3. **Copy `.env.example` to `.env` and fill in your credentials:**
   ```bash
   cp .env.example .env
   # Edit .env and set API_ID, API_HASH, etc.
   ```

> **Note:** Do NOT edit `config.py` for credentials. All secrets are now loaded from `.env`.

## Usage

### Basic Usage

```bash
python main.py
```

### Command-Line Options

```bash
# Enable debug/verbose logging
python main.py --debug
python main.py --verbose
python main.py -v

# Logout and clear session
python main.py --logout
python main.py --signout
```

### Interactive Flow

1. **Authentication** (first run only)
   - Enter phone number with country code (e.g., +4915510256211)
   - The `+` is added automatically if you forget it
   - Wait for the login code (check Telegram app or SMS)
   - Type `resend` to request a new code
   - Type `help` for troubleshooting if code doesn't arrive

2. **Select Chat/Group**
   - Browse numbered list of all your chats and groups
   - Enter the number to select
   - Confirm your selection

3. **Choose Media Types**
   - Select from: images, videos, audio, voice, documents, stickers
   - Enter numbers (comma-separated) or type `all`

4. **Set Filters** (optional)
   - Message limit (leave blank for all messages)
   - Date range (format: YYYY-MM-DD, leave blank to skip)

5. **Output Directory**
   - Specify custom path or press Enter for default (`./telegram_media_backup`)

6. **Download Progress**
   - A modern, interactive progress bar powered by the `rich` library.
   - Provides real-time updates on downloaded, skipped, and error counts.
   - Displays current file being processed with timestamps.
   - Includes a detailed summary at the end.

---

## Building Standalone Executables

You can build a single-file executable for Windows, macOS, or Linux using PyInstaller:

```bash
pip install pyinstaller
pyinstaller --onefile main.py --name telegram-backup
```

- The output will be in the `dist/` folder.
- Distribute the executable without exposing your `.env` file.

---

## CI/CD: Automated Build & Release

This project uses **GitHub Actions** to automatically build and package executables for all major platforms:

1. **On every new tag push (vX.Y.Z):**
   - Build executables for Windows, macOS, and Linux
   - Upload artifacts for each OS
   - Create a GitHub Release and attach the executables

**Workflow files:**
- `.github/workflows/build.yml` — builds executables for all OSes
- `.github/workflows/release.yml` — creates a release and uploads builds

---

## Features

- **Media Types**: Downloads photos, videos, audio, voice messages, documents, and stickers
- **Resume Capability**: Automatically resumes interrupted downloads from where they left off
- **Backup Compatibility**: Skips already downloaded files (backward compatible with previous backups)
- **State Management**: Tracks download progress in real-time, survives crashes and interruptions
- **Corrupted File Detection**: Automatically detects and re-downloads missing, empty, or incomplete files
- **Forum Support**: Automatically detects and handles forum topics
- **Smart Authentication**: 
  - Session persistence (no re-authentication needed)
  - Code resend functionality
  - Helpful troubleshooting during login
  - Auto-formats phone numbers
- **Rate Limiting**: Handles Telegram rate limits automatically with retry logic
- **Duplicate Prevention**: Avoids re-downloading existing files
- **Organized Storage**: Creates clean folder structure by chat/topic
- **Error Handling**: Graceful handling of missing permissions, deleted media, etc.
- **Debug Mode**: Verbose logging for troubleshooting
- **Modern CLI UI**: Utilizes `rich` library for a clean, interactive, and colorful terminal experience.

---

## Folder Structure

Downloaded media is organized as:

```
telegram_media_backup/
├── .backup_state_<hash>.json    # State file (auto-created)
├── Chat Name/
│   ├── photo_12345.jpg
│   ├── video_12346.mp4
│   └── ...
└── Forum Chat Name/
    ├── Topic 1/
    │   ├── photo_67890.jpg
    │   └── ...
    └── Topic 2/
        └── ...
```

**State Files**: The tool creates hidden `.backup_state_*.json` files to track progress. 
- These enable resume functionality
- Safe to keep for ongoing backups
- Delete to force a fresh start (won't re-download existing files)

---

## Progress Display

The tool features a modern, clean progress display:

```
📥 Downloading media from: Saved Messages
📁 Output directory: ./telegram_media_backup/Saved_Messages
🔍 Scanning messages...
Found 1,247 media messages
[14:32:15] 📥 Downloading: photo_12345.jpg (msg 12345)
[14:32:16] ✓ Completed: photo_12345.jpg (2.4MB)
[14:32:17] 📥 Downloading: video_12346.mp4 (msg 12346)
[14:32:25] ✓ Completed: video_12346.mp4 (15.8MB)
[14:32:25] ⊙ Skipped: photo_12347.jpg (already exists)
│ ████████████████████░░░░░░░░░░ │  67.3% │ 840/1247 │ ✓ 825  ⊘ 10  ✗ 5 │ 2.1GB │ 15.3 files/s
────────────────────────────────────────────────────────
📊 Download Summary
────────────────────────────────────────────────────────
✓ Downloaded:  825 files
⊙ Skipped:     10 files
✗ Errors:      5 files
📦 Total size: 2.1GB
⏱️  Duration:   54.2s
⚡ Avg speed:  15.21 files/s
────────────────────────────────────────────────────────
```

---

## Resume Capability

### Automatic Resume

If your download is interrupted (network failure, crash, Ctrl+C):

1. Simply run the tool again
2. Select the same chat
3. The tool automatically detects previous progress
4. Shows resume information and continues from where it stopped

```
🔄 Resuming previous backup...
   Started: 2026-01-18 14:30:22
   Last updated: 2026-01-18 14:45:10
   Already downloaded: 1,247 files
```

### How It Works

- **State Tracking**: Saves message IDs and file information after each successful download
- **File Validation**: On resume, checks if files still exist and are valid (not corrupted/empty)
- **Automatic Re-download**: Missing or corrupted files are automatically re-downloaded
- **Backward Compatible**: Checks if files exist before downloading
- **Incremental Backups**: Running again on the same chat only downloads new media
- **Multiple Chats**: Each chat has its own independent state

### Corrupted File Detection

The tool automatically detects and re-downloads:
- **Missing files**: Marked as downloaded but file no longer exists
- **Empty files**: 0-byte files (incomplete downloads)
- **Size mismatches**: Files that don't match expected size

When resuming, you'll see:
```
🔄 Resuming previous backup...
   Started: 2026-01-18 14:30:22
   Already downloaded: 1,247 files
   📋 Validating existing files...
   ⚠️  Found 3 missing or corrupted files - will re-download
```

### Fresh Start

To start over and ignore previous state:
```bash
# Delete state files
rm telegram_media_backup/.backup_state_*.json
# Files won't be re-downloaded (checks if they exist)
# Only new messages will be processed
```

---

## Troubleshooting

### Not Receiving Authentication Code

- Check Telegram app on **any device** where you're logged in
- Look for message from "Telegram" official account
- Check SMS messages on your phone
- Wait 30-60 seconds before trying `resend`
- Type `help` during code entry for more info

### Rate Limiting

The tool automatically handles rate limits by waiting the required time. Enable `--debug` to see detailed wait times.

### Session Issues

If you encounter authentication problems:
```bash
python main.py --logout
```
Then run normally to re-authenticate.

---

## Requirements

- Python 3.7+
- Telethon library (1.34.0+)
- Valid Telegram account
- API credentials from https://my.telegram.org/apps
- `.env` file for configuration (see `.env.example`)

---

## Notes

- Uses Telegram Client API (MTProto), not Bot API
- No database required
- Media-only backup (text messages are not saved)
- Original filenames preserved when available
- Session files stored locally (keep them secure)
- **.env and session files are git-ignored by default**

---

## Legal Notice

**IMPORTANT: This tool is provided for personal backup purposes only.**

### Permitted Use

✅ **Recommended and legally safe:**
- Backing up your own "Saved Messages" 
- Archiving media you personally created or saved
- Personal, non-commercial backup of your own content
- Exporting your personal data for archival purposes

### Restrictions

⚠️ **Use responsibly and be aware:**
- **Respect copyright**: Downloaded media may be copyrighted by original creators
- **Privacy compliance**: Backing up group chats or channels may involve others' personal data
- **Obtain consent**: Get explicit permission before backing up shared/group conversations
- **Follow Telegram ToS**: Comply with Telegram's Terms of Service at all times
- **No redistribution**: Do not redistribute, sell, or publicly share backed-up content
- **Local laws apply**: Ensure compliance with privacy laws in your jurisdiction (GDPR, CCPA, etc.)

### Security Responsibilities

🔒 **You are responsible for:**
- Securing your API credentials (`API_ID`, `API_HASH`) in `.env`
- Protecting session files (`.session` files = full account access)
- Encrypting backup storage if it contains sensitive data
- Not committing credentials to public repositories
- Proper disposal of backups when no longer needed

### Disclaimer

This software is provided "as is" without warranty of any kind. The authors and contributors:
- Are not responsible for misuse of this tool
- Do not endorse or encourage violation of privacy, copyright, or terms of service
- Assume no liability for legal consequences of your use
- Recommend consulting legal counsel if unsure about compliance

**By using this tool, you agree to use it responsibly, legally, and ethically, and accept full responsibility for your actions.**
