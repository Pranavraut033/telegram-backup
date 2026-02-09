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
# Show help message
python main.py --help
python main.py -h

# Enable debug/verbose logging
python main.py --debug
python main.py --verbose
python main.py -v

# Use simple logging mode (disable progress bars)
python main.py --simple
python main.py --no-progress

# Fresh mode - ignore last used settings
python main.py --fresh
python main.py --no-cache

# Logout and clear session
python main.py --logout
python main.py --signout

# Find and consolidate duplicate files
python main.py --consolidate-duplicates /path/to/backup
python main.py --find-duplicates /path/to/backup
```

### Migration Script

If you have existing backups from before the hash-based duplicate detection feature, run the migration script:

```bash
python migrate_to_hash_detection.py
```

This will:
- Compute hashes for all existing files
- Build the global hash index
- Identify and consolidate duplicate files
- Update all state files

See [MIGRATION_SCRIPT.md](MIGRATION_SCRIPT.md) for detailed instructions.

### Documentation

- [SQL_MIGRATION_GUIDE.md](SQL_MIGRATION_GUIDE.md) - **NEW:** Migrate to SQLite for better performance
- [QUICK_START_SQL.md](QUICK_START_SQL.md) - Quick SQLite migration guide
- [DUPLICATE_DETECTION.md](DUPLICATE_DETECTION.md) - Comprehensive guide to duplicate detection features
- [CROSS_CHAT_DUPLICATES.md](CROSS_CHAT_DUPLICATES.md) - How cross-chat duplicate detection works
- [QUICK_START_DUPLICATES.md](QUICK_START_DUPLICATES.md) - Quick reference guide
- [MIGRATION_SCRIPT.md](MIGRATION_SCRIPT.md) - Migration script usage and details

For more detailed help and examples, run:
```bash
python main.py --help
```

or see [help.txt](help.txt)

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
   - **Message limit** - Maximum number of messages to scan (leave blank for all)
   - **File size limit** - Skip files larger than this (e.g., 50MB, 2GB)
   - **Date range** - Backup messages from a specific period (format: YYYY-MM-DD, leave blank to skip)
   - **Sorting** - Sort by date or reaction count

5. **Output Directory**
   - Specify custom path or press Enter for default (`./telegram_media_backup`)

6. **Download Progress**
   - A modern, interactive progress bar powered by the `rich` library.
   - Provides real-time updates on downloaded, skipped, and error counts.
   - Displays current file being processed with timestamps.
   - Includes a detailed summary at the end.
   - Use `--simple` mode to disable progress bars for logging to file

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

### Using downloaded build artifacts

You can download the built executables either from the GitHub Actions run artifacts (Build job) or from a Release (created by the Release workflow):

- From a Release: go to the repository Releases page, find the tag you want and download the attached `telegram-backup` asset for your platform (Windows builds will be `telegram-backup.exe`, macOS/Linux builds are single-file executables).

- From an Actions run: open the Build workflow run, expand the Build job, and download the artifact named `telegram-backup-<platform>`.

Once downloaded, run the executable for your platform:

- macOS / Linux:
  ```bash
  # If the binary is zipped, unzip first, then:
  chmod +x telegram-backup
  ./telegram-backup --help
  ./telegram-backup  # runs the backup CLI
  ```

- Windows (PowerShell / CMD):
  ```powershell
  # Download telegram-backup.exe from the release or artifacts
  .\telegram-backup.exe --help
  .\telegram-backup.exe
  ```

Notes:
- The executables are built with PyInstaller as single-file binaries and may be zipped by Actions when uploaded; extract before running if needed.
- Use `--help` to see available options (e.g., `--debug`, `--logout`).
- Always run builds from official releases or CI artifacts to ensure integrity.

### Running the executable

Follow these steps to set up the environment and run the downloaded executable:

1. Create a `.env` file (recommended)

   ```bash
   cp .env.example .env
   # Edit .env and set API_ID, API_HASH, etc.
   ```

   Example `.env`:

   ```dotenv
   API_ID=123456
   API_HASH=your_api_hash_here
   SESSION_NAME=telegram_backup_session
   DEFAULT_OUTPUT_DIR=./telegram_media_backup
   DEFAULT_MESSAGE_LIMIT=
   ```

2. Where to place `.env`

- Place `.env` next to the executable or run the executable from the directory containing `.env`. The program uses `python-dotenv` to load variables from the current working directory.

3. Alternative: set environment variables directly

- macOS / Linux:
  ```bash
  export API_ID=123456
  export API_HASH=your_api_hash
  ./telegram-backup
  ```

- Windows PowerShell:
  ```powershell
  $env:API_ID="123456"
  $env:API_HASH="your_api_hash"
  .\telegram-backup.exe
  ```

4. Run the executable

- macOS / Linux:
  ```bash
  chmod +x telegram-backup
  ./telegram-backup --help
  ./telegram-backup
  ```

- Windows (PowerShell / CMD):
  ```powershell
  .\telegram-backup.exe --help
  .\telegram-backup.exe
  ```

5. Notes & troubleshooting

- A session file (`<SESSION_NAME>.session`) will be created in the working directory—keep it secure and do **not** commit it.
- If the executable complains about missing credentials, verify that `.env` is present in the current directory or that you exported the environment variables in the shell you are running.
- Use `--debug` for verbose logs.
- For automated runs (systemd, services, CI), set environment variables in the service/unit or use an environment file.

### macOS — Gatekeeper & security notes 🔒

macOS may block downloaded, unsigned binaries with Gatekeeper. If you run into "unidentified developer" or "can't be opened" errors, follow one of these safe options:

- GUI (recommended for non-technical users):
  1. Attempt to open the app by double-clicking (you may see a warning).
  2. Open System Settings → Privacy & Security (or System Preferences → Security & Privacy on older macOS).
  3. Under **Security**, click **Open Anyway** for the blocked app, then confirm **Open** in the dialog.

- Terminal (power users):
  ```bash
  # Make the file executable (if needed)
  chmod +x ./telegram-backup

  # Remove the download quarantine attribute (marks the file as trusted)
  xattr -d com.apple.quarantine ./telegram-backup

  # Check Gatekeeper status (accepted => allowed; rejected => blocked)
  spctl -a -v ./telegram-backup
  ```

- Notes on notarization and signing:
  - Signed and notarized builds will pass Gatekeeper automatically. If you distribute macOS binaries widely, consider signing and notarizing releases (codesign + xcrun notarytool + stapler) in your Build workflow.

  - Required GitHub Secrets (for automated signing & notarization):
    - `APPLE_IDENTITY_P12` — Base64-encoded `.p12` of your **Developer ID Application** certificate (private key included).
    - `APPLE_IDENTITY_P12_PASSWORD` — Password used to export the `.p12` (if any).
    - `APPLE_SIGNING_IDENTITY` — The identity string used by `codesign` (e.g., `Developer ID Application: Your Name (TEAMID)`).
    - `APPLE_API_KEY_ID` — App Store Connect API key ID (the Key ID of the AuthKey .p8)
    - `APPLE_API_ISSUER_ID` — App Store Connect Issuer ID (the Issuer ID for your API key).
    - `APPLE_API_PRIVATE_KEY` — Base64-encoded `.p8` private key (AuthKey_<KEYID>.p8) used by `notarytool`.

  - How it works (summary): the macOS runner imports your `.p12` certificate into a temporary keychain, `codesign`s the built binary with the provided identity, packages the artifact (zip), submits it to Apple's notarization service via `xcrun notarytool`, waits for notarization to complete, and then `staple`s the notarization ticket to the binary so Gatekeeper accepts it.

  - Security notes:
    - Keep these secrets in the repository settings (Repository > Settings > Secrets) and **do not** commit certificate files into the repo.
    - Test signing & notarization in a private branch first; if notarization fails the Build job will show the notarytool output and fail.

  - Avoid disabling Gatekeeper globally (e.g., `spctl --master-disable`) — this reduces system security and is not recommended.

---

## Features

- **SQLite Backend** (NEW): 10-50x faster state management with 90% less memory usage
- **Media Types**: Downloads photos, videos, audio, voice messages, documents, and stickers
- **Resume Capability**: Automatically resumes interrupted downloads from where they left off
- **Backup Compatibility**: Skips already downloaded files (backward compatible with previous backups)
- **State Management**: Tracks download progress in real-time, survives crashes and interruptions
- **Corrupted File Detection**: Automatically detects and re-downloads missing, empty, or incomplete files
- **Forum Support**: Automatically detects and handles forum topics
- **Smart Filtering**: 
  - Filter by date range (from/to)
  - Filter by file size (skip files larger than limit)
  - Limit number of messages to scan
  - Sort by date or reaction count
- **Smart Caching**: 
  - Message lists cached for faster repeated runs
  - Configurable cache TTL (Time To Live)
- **Settings Persistence**: 
  - Remembers last used settings for quick re-runs
  - `--fresh` flag to ignore cached settings
- **Smart Authentication**: 
  - Session persistence (no re-authentication needed)
  - Code resend functionality
  - Helpful troubleshooting during login
  - Auto-formats phone numbers
- **Rate Limiting**: Handles Telegram rate limits automatically with retry logic
- **Duplicate Prevention**: Avoids re-downloading existing files
- **Organized Storage**: Creates clean folder structure by chat/topic
- **Error Handling**: Graceful handling of missing permissions, deleted media, etc.
- **Debug Mode**: Verbose logging for troubleshooting (`--debug` flag)
- **Simple Mode**: Disable progress bars for logging to file (`--simple` flag)
- **Modern CLI UI**: Utilizes `rich` library for a clean, interactive, and colorful terminal experience.
- **Comprehensive Help**: Built-in help documentation (`--help` flag)

---

## Project Files

### Core Application Files

| File | Purpose |
|------|---------|
| `main.py` | Entry point, CLI handler, interactive prompts |
| `telegram_client.py` | Telegram client wrapper and session management |
| `downloader.py` | Media download logic with progress tracking |
| `topic_handler.py` | Forum topic detection and handling |
| `dialog_selector.py` | Chat/group selection interface |
| `media_filter.py` | Media type filtering and message validation |
| `state_manager.py` | Download state management and resume capability (dual SQL/JSON) |
| `state_db.py` | SQLite database layer for efficient state storage |
| `seed_from_json.py` | Migration script to import JSON state into SQLite |
| `config.py` | Configuration loader (loads from `.env`) |
| `utils.py` | Helper utilities (file handling, sanitization) |

### Configuration & Documentation

| File | Purpose |
|------|---------|
| `.env.example` | Template for environment variables |
| `.env` | Your credentials (created from `.env.example`, not committed) |
| `help.txt` | Help documentation (displayed with `--help`) |
| `README.md` | This file |

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
