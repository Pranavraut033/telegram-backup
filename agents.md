# Telegram Backup - Agent Guide

## Project Overview
CLI tool for backing up media from Telegram chats and groups using Telegram Client API. Downloads messages and media while filtering by date and media type.

## Environment Setup

### Virtual Environment (Required)
```bash
# Create venv
python3 -m venv venv

# Activate venv
source venv/bin/activate  # macOS/Linux
# or
venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt
```

**Always use venv for all `python` and `pip` commands.**

## Project Structure
- `main.py` - Entry point, CLI handler
- `telegram_client.py` - Telegram client wrapper
- `downloader.py` - Media download logic with duplicate detection
- `topic_handler.py` - Topic/thread handling
- `dialog_selector.py` - Chat/group selection UI
- `media_filter.py` - Filter messages by type/date
- `state_manager.py` - Session state management with hash tracking
- `config.py` - Configuration loader
- `utils.py` - Helper utilities including file hashing
- `find_duplicates.py` - Standalone duplicate file finder

## Key Commands

```bash
# Interactive backup flow
python main.py

# With debug output
python main.py --debug

# Find and consolidate duplicates
python main.py --consolidate-duplicates /path/to/backup

# Logout
python main.py --logout
```

## Setup Flow
1. Get API credentials: https://my.telegram.org/apps
2. Create `.env` from `.env.example` with `API_ID`, `API_HASH`, phone
3. First run: authenticate via phone number/OTP
4. Select chats and filters interactively

## Development Notes
- Uses Telethon library for Telegram API
- Session stored in `telegram_backup_session.session`
- Config loaded from `.env` (never hardcode secrets in `config.py`)
- State preserved across runs in `state_manager.py`
- **Duplicate detection**: Content-based hashing prevents redundant downloads
- **Hash storage**: Sample hashes (first+last 64KB) stored in state for O(1) duplicate lookup
- See `DUPLICATE_DETECTION.md` for detailed documentation on duplicate features

## Common Tasks

**Add new feature:** Modify relevant module, test with `python main.py`
**Debug issues:** Use `python main.py --debug` for verbose logging
**Reset session:** Delete `telegram_backup_session.session` or run `python main.py --logout`
**Update deps:** `pip install -r requirements.txt` (ensure venv active)

---
*Always activate venv before running any commands.*
