"""
Configuration for Telegram Media Backup
"""


# Load environment variables from .env file if present
import os
from dotenv import load_dotenv
load_dotenv()

# Telegram API credentials (must be set in .env)
API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")

# Session settings
SESSION_NAME = os.getenv("SESSION_NAME", "telegram_backup_session")

# Default settings
DEFAULT_OUTPUT_DIR = os.getenv("DEFAULT_OUTPUT_DIR", "./telegram_media_backup")
DEFAULT_MESSAGE_LIMIT = (
    int(os.getenv("DEFAULT_MESSAGE_LIMIT")) if os.getenv("DEFAULT_MESSAGE_LIMIT") else None
)
LAST_CONFIG_FILE = os.getenv("LAST_CONFIG_FILE", ".last_backup_config.json")

# Supported media types
MEDIA_TYPES = {
    "images": ["photo"],
    "videos": ["video"],
    "audio": ["audio"],
    "voice": ["voice"],
    "documents": ["document"],
    "stickers": ["sticker"]
}

# Download settings
CHUNK_SIZE = 4 * 1024 * 1024  # 4MB chunks
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds

# Cache settings
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", 600))  # cache valid for 10 minutes by default

# Debug settings
DEBUG = False  # Set to True for verbose logging
