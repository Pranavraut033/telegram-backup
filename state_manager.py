"""
Download state management for resume capability in Telegram backup.
Tracks progress and enables resuming downloads.
Supports both SQLite (default) and JSON (legacy) backends.
"""
import json
import os
import sqlite3
from datetime import datetime
import hashlib
import config
import utils
from state_db import DatabaseManager


def log_debug(message):
    """Print debug message if DEBUG is enabled"""
    if config.DEBUG:
        print(f"[DEBUG] {message}")


class StateManager:
    def _migrate_to_dict_format(self):
        """Migrate downloaded_messages from list format to dict format if needed."""
        if isinstance(self.state['downloaded_messages'], list):
            log_debug("Migrating downloaded_messages from list to dict format")
            old_list = self.state['downloaded_messages']
            self.state['downloaded_messages'] = {}
            for old_id in old_list:
                self.state['downloaded_messages'][str(old_id)] = {
                    'filename': 'unknown',
                    'size': 0,
                    'path': None
                }
    
    def generate_state_from_existing_files(self, backup_dir):
        """
        Scan the backup directory and mark all found media files as downloaded in the state file.
        Also computes sample hashes for duplicate detection.
        """
        downloaded = {}
        total_files = 0
        total_bytes = 0
        log_debug(f"Generating state from existing files in {backup_dir}")
        try:
            for root, _, files in os.walk(backup_dir):
                for fname in files:
                    if fname.startswith('.'):
                        continue
                    fpath = os.path.join(root, fname)
                    if not os.path.isfile(fpath):
                        continue
                    try:
                        size = os.path.getsize(fpath)
                        # Use filename as message_id if no better info
                        msg_id = fname.split('.')[0]
                        
                        # Compute sample hash for duplicate detection
                        sample_hash = utils.sample_hash_file(fpath)
                        
                        downloaded[msg_id] = {
                            'filename': fname,
                            'size': size,
                            'path': fpath,
                            'sample_hash': sample_hash
                        }
                        
                        # Update hash index
                        if sample_hash:
                            self._update_hash_index(size, sample_hash, msg_id)
                        
                        total_files += 1
                        total_bytes += size
                    except Exception as e:
                        log_debug(f"Error processing file {fpath}: {e}")
                        continue
            
            self.state['downloaded_messages'] = downloaded
            self.state['total_files'] = total_files
            self.state['total_bytes'] = total_bytes
            self._save_state()
            log_debug(f"Generated state with {total_files} files ({total_bytes} bytes)")
        except Exception as e:
            log_debug(f"Error generating state from existing files: {e}")

    def __init__(self, output_dir, chat_name):
        """
        Initialize state manager for a chat backup.
        Uses SQLite backend if enabled, falls back to JSON otherwise.
        """
        self.output_dir = output_dir
        self.chat_name = chat_name
        self.chat_hash = self._sanitize_for_filename(chat_name)
        self.state_file = os.path.join(output_dir, f".backup_state_{self.chat_hash}.json")
        self.state = {}
        
        # Determine backend mode
        self.use_db = config.DB_ENABLE
        self.db = None
        self.chat_id = None
        
        if self.use_db:
            try:
                # Initialize database
                db_path = config.DB_PATH or os.path.join(output_dir, "telegram_backup.db")
                self.db = DatabaseManager(db_path)
                self.chat_id = self.db.get_or_create_chat(chat_name, self.chat_hash)
                log_debug(f"Using SQLite backend for chat: {chat_name} (chat_id={self.chat_id})")
            except Exception as e:
                log_debug(f"Failed to initialize database: {e}")
                if config.DB_LEGACY_JSON_FALLBACK:
                    log_debug("Falling back to JSON backend")
                    self.use_db = False
                    self.db = None
                else:
                    raise
        
        # Fallback to JSON
        if not self.use_db:
            self.state = self._load_state()
            log_debug(f"Using JSON backend for chat: {chat_name}")
        
        # Initialize global state manager for cross-chat duplicate detection
        self.global_state = GlobalStateManager(output_dir)
    
    def _sanitize_for_filename(self, name):
        """
        Create a safe filename from a chat name (for state file).
        """
        return hashlib.md5(name.encode()).hexdigest()[:8]
    
    def _load_state(self):
        """
        Load existing state from file, or create a new state dict.
        """
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    loaded_state = json.load(f)
                log_debug(f"Loaded existing state from {self.state_file}")
                return loaded_state
            except Exception as e:
                log_debug(f"Failed to load state file: {e}. Creating new state.")
        
        log_debug(f"Creating new state for chat: {self.chat_name}")
        return {
            'chat_name': self.chat_name,
            'started_at': datetime.now().isoformat(),
            'last_updated': None,
            'completed': False,
            'downloaded_messages': {},  # Dict: {message_id: {"filename": str, "size": int, "path": str, "sample_hash": str, "full_hash": str (optional)}}
            'skipped_messages': [],
            'failed_messages': [],
            'total_files': 0,
            'total_bytes': 0,
            'last_message_id': None,
            'hash_index': {},  # Dict: {(size, sample_hash): [message_ids]} for fast duplicate lookup
            'duplicate_map': {}  # Dict: {duplicate_msg_id: canonical_msg_id} tracks which messages share files
        }
    
    def _save_state(self):
        """
        Save the current state to the JSON file.
        """
        self.state['last_updated'] = datetime.now().isoformat()
        try:
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(self.state, f, indent=2)
            log_debug(f"State saved to {self.state_file}")
        except Exception as e:
            log_debug(f"Error saving state: {e}")
            print(f"⚠️  Warning: Could not save state: {e}")
    
    def validate_downloaded_file(self, message_id):
        """
        Validate if a downloaded file still exists and is valid.
        """
        if not self.is_message_downloaded(message_id):
            return False
        
        if self.use_db:
            file_info = self.db.get_message(self.chat_id, message_id)
            if not file_info:
                return False
        else:
            # Migrate format if needed
            self._migrate_to_dict_format()
            file_info = self.state['downloaded_messages'].get(str(message_id))
            if not file_info:
                return False
        
        file_path = file_info.get('file_path') if self.use_db else file_info.get('path')
        expected_size = file_info.get('file_size') if self.use_db else file_info.get('size', 0)
        
        # Check if file exists
        if not file_path or not os.path.exists(file_path):
            log_debug(f"File not found for message {message_id}: {file_path}")
            return False
        
        # Check if file size is reasonable (not corrupted/incomplete)
        try:
            actual_size = os.path.getsize(file_path)
            if actual_size == 0:
                log_debug(f"[VALIDATION FAILED] File is empty (0 bytes) for message {message_id}: {file_path}")
                return False
            
            # If we have expected size, validate it matches (within 1% tolerance for metadata)
            if expected_size > 0:
                size_diff = abs(actual_size - expected_size)
                tolerance = expected_size * 0.01  # 1% tolerance
                if size_diff > tolerance and size_diff > 1024:  # Allow 1KB difference for small files
                    log_debug(f"[VALIDATION FAILED] File size mismatch for message {message_id}: expected {expected_size} bytes, got {actual_size} bytes (diff: {size_diff} bytes)")
                    return False
            
            log_debug(f"[VALIDATION OK] File valid for message {message_id}: {actual_size} bytes at {file_path}")
            return True
        except Exception as e:
            log_debug(f"[VALIDATION ERROR] Error validating file for message {message_id}: {e}")
            return False
    
    def is_message_downloaded(self, message_id):
        """
        Return True if the message is already downloaded and file is valid.
        """
        if self.use_db:
            return self.db.is_message_downloaded(self.chat_id, message_id)
        
        msg_id_str = str(message_id)
        # Handle both old format (list) and new format (dict)
        if isinstance(self.state['downloaded_messages'], list):
            return message_id in self.state['downloaded_messages']
        else:
            return msg_id_str in self.state['downloaded_messages']
    
    def is_message_skipped(self, message_id):
        """
        Return True if the message was skipped.
        """
        if self.use_db:
            status = self.db.get_message_status(self.chat_id, message_id)
            return status == 'skipped'
        
        return message_id in self.state['skipped_messages']
    
    def is_message_failed(self, message_id):
        """
        Return True if the message failed before.
        """
        if self.use_db:
            status = self.db.get_message_status(self.chat_id, message_id)
            return status == 'failed'
        
        return message_id in self.state['failed_messages']
    
    def update_file_path(self, old_path, new_path):
        """
        Update file path in state when a file is renamed.
        """
        if self.use_db:
            return self.db.update_file_path(old_path, new_path)
        
        if isinstance(self.state['downloaded_messages'], dict):
            for msg_id, file_info in self.state['downloaded_messages'].items():
                if file_info.get('path') == old_path:
                    file_info['path'] = new_path
                    file_info['filename'] = os.path.basename(new_path)
                    self._save_state()
                    return True
        return False
    
    def mark_downloaded(self, message_id, file_path=None, file_size=0, sample_hash=None, full_hash=None):
        """
        Mark a message as successfully downloaded, with file info and optional hashes.
        
        Args:
            message_id: Telegram message ID
            file_path: Path to downloaded file
            file_size: File size in bytes
            sample_hash: SHA-256 hash of first+last 64KB (optional)
            full_hash: Full SHA-256 hash (optional)
        """
        if self.use_db:
            try:
                # Add message to database
                filename = os.path.basename(file_path) if file_path else 'unknown'
                msg_rec_id = self.db.add_message(
                    self.chat_id, message_id, filename, file_path, 
                    file_size, sample_hash, full_hash
                )

                # Mark status as downloaded
                self.db.set_message_status(self.chat_id, message_id, 'downloaded')

                # Update hash indices
                if sample_hash and file_size > 0 and msg_rec_id:
                    self.db.register_file_hash(file_size, sample_hash, file_path, msg_rec_id, self.chat_id)
                    self.global_state.register_file(file_size, sample_hash, file_path)

                # Update chat stats
                stats = self.db.get_chat_stats(self.chat_id)
                self.db.update_chat_stats(
                    self.chat_id,
                    total_files=stats.get('total_files', 0) + 1,
                    total_bytes=stats.get('total_bytes', 0) + file_size,
                    last_message_id=message_id
                )

                log_debug(f"Marked message {message_id} as downloaded (SQL): {filename}")
            except sqlite3.IntegrityError as e:
                log_debug(f"[DB ERROR] Integrity error while marking downloaded for message {message_id}: {e}")
            except Exception as e:
                log_debug(f"[DB ERROR] Failed to mark downloaded for message {message_id}: {e}")
            return
        
        # JSON backend
        msg_id_str = str(message_id)
        
        # Migrate old format to new format if needed
        self._migrate_to_dict_format()
        
        # Add or update entry
        if msg_id_str not in self.state['downloaded_messages']:
            self.state['total_files'] += 1
            self.state['total_bytes'] += file_size
            log_debug(f"Marked message {message_id} as downloaded: {os.path.basename(file_path) if file_path else 'N/A'}")
        
        file_info = {
            'filename': os.path.basename(file_path) if file_path else 'unknown',
            'size': file_size,
            'path': file_path
        }
        
        # Add hash fields if provided
        if sample_hash:
            file_info['sample_hash'] = sample_hash
        if full_hash:
            file_info['full_hash'] = full_hash
        
        self.state['downloaded_messages'][msg_id_str] = file_info
        
        # Update hash index for duplicate detection
        if sample_hash and file_size > 0:
            self._update_hash_index(file_size, sample_hash, message_id)
            # Also update global hash index for cross-chat duplicate detection
            self.global_state.register_file(file_size, sample_hash, file_path)
        
        self.state['last_message_id'] = message_id
        self._save_state()
    
    def mark_skipped(self, message_id):
        """
        Mark a message as skipped.
        """
        if self.use_db:
            try:
                self.db.set_message_status(self.chat_id, message_id, 'skipped')
                self.db.update_chat_stats(self.chat_id, last_message_id=message_id)
                log_debug(f"Marked message {message_id} as skipped (SQL)")
            except sqlite3.IntegrityError as e:
                log_debug(f"[DB ERROR] Integrity error while marking skipped for message {message_id}: {e}")
            except Exception as e:
                log_debug(f"[DB ERROR] Failed to mark skipped for message {message_id}: {e}")
            return
        
        if message_id not in self.state['skipped_messages']:
            self.state['skipped_messages'].append(message_id)
            log_debug(f"Marked message {message_id} as skipped")
        
        self.state['last_message_id'] = message_id
        self._save_state()
    
    def mark_failed(self, message_id):
        """
        Mark a message as failed.
        """
        if self.use_db:
            try:
                self.db.set_message_status(self.chat_id, message_id, 'failed')
                self.db.update_chat_stats(self.chat_id, last_message_id=message_id)
                log_debug(f"Marked message {message_id} as failed (SQL)")
            except sqlite3.IntegrityError as e:
                log_debug(f"[DB ERROR] Integrity error while marking failed for message {message_id}: {e}")
            except Exception as e:
                log_debug(f"[DB ERROR] Failed to mark failed for message {message_id}: {e}")
            return
        
        if message_id not in self.state['failed_messages']:
            self.state['failed_messages'].append(message_id)
            log_debug(f"Marked message {message_id} as failed")
        
        self.state['last_message_id'] = message_id
        self._save_state()
    
    def mark_completed(self):
        """
        Mark the backup as completed.
        """
        if self.use_db:
            self.db.mark_chat_completed(self.chat_id)
            log_debug(f"Marked chat as completed (SQL)")
            return
        
        self.state['completed'] = True
        self.state['completed_at'] = datetime.now().isoformat()
        self._save_state()
    
    def get_stats(self):
        """
        Get current state statistics as a dict.
        """
        if self.use_db:
            chat_stats = self.db.get_chat_stats(self.chat_id)
            status_counts = self.db.get_status_counts(self.chat_id)
            
            return {
                'downloaded': status_counts.get('downloaded', 0),
                'skipped': status_counts.get('skipped', 0),
                'failed': status_counts.get('failed', 0),
                'total_files': chat_stats.get('total_files', 0),
                'total_bytes': chat_stats.get('total_bytes', 0),
                'last_message_id': chat_stats.get('last_message_id')
            }
        
        downloaded_count = len(self.state['downloaded_messages']) if isinstance(
            self.state['downloaded_messages'], (list, dict)
        ) else 0
        
        return {
            'downloaded': downloaded_count,
            'skipped': len(self.state['skipped_messages']),
            'failed': len(self.state['failed_messages']),
            'total_files': self.state['total_files'],
            'total_bytes': self.state['total_bytes'],
            'last_message_id': self.state['last_message_id']
        }
    
    def is_resuming(self):
        """
        Return True if this is a resume operation (previous state exists).
        """
        if self.use_db:
            stats = self.db.get_chat_stats(self.chat_id)
            return (stats.get('total_files', 0) > 0 or 
                   stats.get('last_message_id') is not None)
        
        downloaded_messages = self.state.get('downloaded_messages', [])
        has_downloads = False
        
        if isinstance(downloaded_messages, list):
            has_downloads = len(downloaded_messages) > 0
        elif isinstance(downloaded_messages, dict):
            has_downloads = len(downloaded_messages) > 0
        
        return has_downloads or self.state.get('last_message_id') is not None
    
    def get_resume_info(self):
        """Get information about resume state"""
        if not self.is_resuming():
            return None
        
        if self.use_db:
            stats = self.db.get_chat_stats(self.chat_id)
            status_counts = self.db.get_status_counts(self.chat_id)
            return {
                'started_at': stats.get('started_at'),
                'last_updated': stats.get('last_updated'),
                'downloaded': status_counts.get('downloaded', 0),
                'last_message_id': stats.get('last_message_id')
            }
        
        downloaded_messages = self.state.get('downloaded_messages', [])
        downloaded_count = len(downloaded_messages) if isinstance(
            downloaded_messages, (list, dict)
        ) else 0
        
        return {
            'started_at': self.state['started_at'],
            'last_updated': self.state['last_updated'],
            'downloaded': downloaded_count,
            'last_message_id': self.state['last_message_id']
        }
    
    def delete_state(self):
        """Delete state file (for fresh start)"""
        if os.path.exists(self.state_file):
            try:
                os.remove(self.state_file)
                log_debug(f"Deleted state file: {self.state_file}")
            except Exception as e:
                log_debug(f"Failed to delete state file: {e}")
    
    def _update_hash_index(self, file_size, sample_hash, message_id):
        """
        Update the hash index for fast duplicate lookup.
        
        Args:
            file_size: File size in bytes
            sample_hash: Sample hash of the file
            message_id: Message ID to add to index
        """
        if 'hash_index' not in self.state:
            self.state['hash_index'] = {}
        
        # Use tuple (size, hash) as key for precise matching
        key = f"{file_size}:{sample_hash}"
        
        if key not in self.state['hash_index']:
            self.state['hash_index'][key] = []
        
        msg_id_str = str(message_id)
        if msg_id_str not in self.state['hash_index'][key]:
            self.state['hash_index'][key].append(msg_id_str)
            log_debug(f"Added message {message_id} to hash index (size={file_size}, hash={sample_hash[:8]}...)")
    
    def find_duplicate(self, file_size, sample_hash):
        """
        Find if a file with the same size and hash already exists.
        Checks both local (this chat) and global (all chats) hash indices.
        
        Args:
            file_size: File size in bytes to match
            sample_hash: Sample hash to match
            
        Returns:
            tuple: (message_id, file_path) of existing file, or (None, None) if no duplicate
        """
        if self.use_db:
            # Check within same chat first
            result = self.db.find_duplicate_in_chat(self.chat_id, file_size, sample_hash)
            if result:
                msg_id, file_path = result
                if os.path.exists(file_path):
                    log_debug(f"Found duplicate in same chat (SQL): size={file_size}, hash={sample_hash[:8]}... -> message {msg_id}")
                    return msg_id, file_path
            
            # Check global index
            global_path = self.db.find_duplicate_by_hash(file_size, sample_hash)
            if global_path and os.path.exists(global_path):
                log_debug(f"Found duplicate across chats (SQL): size={file_size}, hash={sample_hash[:8]}... -> {global_path}")
                return 'global', global_path
            
            return None, None
        
        # JSON backend
        # First check local hash index (this chat)
        if 'hash_index' not in self.state:
            self.state['hash_index'] = {}
        
        key = f"{file_size}:{sample_hash}"
        existing_msg_ids = self.state['hash_index'].get(key, [])
        
        # Return first valid match from this chat
        for msg_id_str in existing_msg_ids:
            file_info = self.state['downloaded_messages'].get(msg_id_str)
            if file_info and file_info.get('path'):
                # Verify file still exists
                if os.path.exists(file_info['path']):
                    log_debug(f"Found duplicate in same chat: size={file_size}, hash={sample_hash[:8]}... -> message {msg_id_str}")
                    return msg_id_str, file_info['path']
        
        # Check global hash index (across all chats)
        global_path = self.global_state.find_duplicate(file_size, sample_hash)
        if global_path and os.path.exists(global_path):
            log_debug(f"Found duplicate across chats: size={file_size}, hash={sample_hash[:8]}... -> {global_path}")
            return 'global', global_path
        
        return None, None
    
    def mark_duplicate(self, duplicate_msg_id, canonical_msg_id):
        """
        Mark a message as a duplicate of another message.
        
        Args:
            duplicate_msg_id: The message ID that is a duplicate
            canonical_msg_id: The message ID of the original file (or 'global' for cross-chat)
        """
        if self.use_db:
            # For cross-chat duplicates, canonical_msg_id might be 'global'
            try:
                if canonical_msg_id == 'global':
                    # Mark as duplicate but don't track specific canonical message
                    self.db.mark_duplicate(self.chat_id, duplicate_msg_id, self.chat_id, -1)
                else:
                    self.db.mark_duplicate(self.chat_id, duplicate_msg_id, self.chat_id, canonical_msg_id)
                log_debug(f"Marked message {duplicate_msg_id} as duplicate of {canonical_msg_id} (SQL)")
            except sqlite3.IntegrityError as e:
                log_debug(f"[DB ERROR] Integrity error while marking duplicate for message {duplicate_msg_id}: {e}")
            except Exception as e:
                log_debug(f"[DB ERROR] Failed to mark duplicate for message {duplicate_msg_id}: {e}")
            return
        
        if 'duplicate_map' not in self.state:
            self.state['duplicate_map'] = {}
        
        self.state['duplicate_map'][str(duplicate_msg_id)] = str(canonical_msg_id)
        log_debug(f"Marked message {duplicate_msg_id} as duplicate of {canonical_msg_id}")
        self._save_state()
    
    def is_duplicate(self, message_id):
        """
        Check if a message is marked as a duplicate.
        
        Returns:
            str: Canonical message ID if duplicate, None otherwise
        """
        if self.use_db:
            dup_info = self.db.get_duplicate_info(self.chat_id, message_id)
            if dup_info:
                return str(dup_info['canonical_msg_id'])
            return None
        
        if 'duplicate_map' not in self.state:
            return None
        return self.state['duplicate_map'].get(str(message_id))
    
    def compute_file_hash(self, file_path, full=False):
        """
        Compute hash for an existing file.
        
        Args:
            file_path: Path to the file
            full: If True, compute full hash; otherwise compute sample hash
            
        Returns:
            str: Hash hex digest or None on failure
        """
        if not os.path.exists(file_path):
            return None
        
        if full:
            return utils.hash_file(file_path)
        else:
            return utils.sample_hash_file(file_path)
    
    def validate_file_with_hash(self, message_id, recompute=False):
        """
        Validate file and optionally verify its hash matches stored hash.
        
        Args:
            message_id: Message ID to validate
            recompute: If True, recompute hash and verify against stored value
            
        Returns:
            bool: True if file is valid (and hash matches if recompute=True)
        """
        # First do standard validation
        if not self.validate_downloaded_file(message_id):
            return False
        
        # If not recomputing hash, we're done
        if not recompute:
            return True
        
        # Get file info
        file_info = self.state['downloaded_messages'].get(str(message_id))
        if not file_info:
            return False
        
        stored_hash = file_info.get('sample_hash')
        if not stored_hash:
            # No hash stored, can't verify
            return True
        
        # Recompute and compare
        file_path = file_info.get('path')
        if not file_path:
            return False
        
        computed_hash = self.compute_file_hash(file_path, full=False)
        if computed_hash != stored_hash:
            log_debug(f"Hash mismatch for message {message_id}: stored={stored_hash[:8]}..., computed={computed_hash[:8] if computed_hash else 'None'}...")
            return False
        
        return True
    
    def rebuild_hash_index(self):
        """
        Rebuild hash index from existing downloaded_messages.
        Useful after loading old state files or manual state modifications.
        """
        log_debug("Rebuilding hash index from downloaded messages...")
        self.state['hash_index'] = {}
        
        count = 0
        for msg_id_str, file_info in self.state['downloaded_messages'].items():
            sample_hash = file_info.get('sample_hash')
            file_size = file_info.get('size', 0)
            
            if sample_hash and file_size > 0:
                self._update_hash_index(file_size, sample_hash, msg_id_str)
                count += 1
        
        log_debug(f"Rebuilt hash index with {count} entries")
        self._save_state()


class GlobalStateManager:
    """
    Manages a global hash index across all chats for cross-chat duplicate detection.
    This allows detecting when the same file exists in multiple different chats.
    Supports both SQLite and JSON backends.
    """
    
    def __init__(self, output_dir):
        """
        Initialize global state manager.
        
        Args:
            output_dir: Base directory where all backups are stored
        """
        self.output_dir = output_dir
        self.state_file = os.path.join(output_dir, ".backup_state_global.json")
        
        # Use SQL backend if enabled
        self.use_db = config.DB_ENABLE
        self.db = None
        
        if self.use_db:
            try:
                db_path = config.DB_PATH or os.path.join(output_dir, "telegram_backup.db")
                self.db = DatabaseManager(db_path)
                log_debug("Using SQLite backend for global state")
            except Exception as e:
                log_debug(f"Failed to initialize database for global state: {e}")
                if config.DB_LEGACY_JSON_FALLBACK:
                    self.use_db = False
                    self.db = None
                else:
                    raise
        
        if not self.use_db:
            self.state = self._load_state()
            log_debug("Using JSON backend for global state")
    
    def _load_state(self):
        """Load existing global state or create new one."""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    loaded_state = json.load(f)
                log_debug(f"Loaded global state from {self.state_file}")
                return loaded_state
            except Exception as e:
                log_debug(f"Failed to load global state: {e}. Creating new state.")
        
        log_debug("Creating new global state")
        return {
            'created_at': datetime.now().isoformat(),
            'last_updated': None,
            'hash_index': {},  # Dict: {(size, hash): file_path} maps to first occurrence
            'version': '1.0'
        }
    
    def _save_state(self):
        """Save the current global state to file."""
        self.state['last_updated'] = datetime.now().isoformat()
        try:
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(self.state, f, indent=2)
            log_debug(f"Global state saved to {self.state_file}")
        except Exception as e:
            log_debug(f"Error saving global state: {e}")
    
    def register_file(self, file_size, sample_hash, file_path):
        """
        Register a file in the global hash index.
        Only stores the first occurrence of each unique file.
        
        Args:
            file_size: File size in bytes
            sample_hash: Sample hash of the file
            file_path: Absolute path to the file
        """
        if self.use_db:
            self.db.register_file_hash(file_size, sample_hash, file_path)
            return
        
        if 'hash_index' not in self.state:
            self.state['hash_index'] = {}
        
        key = f"{file_size}:{sample_hash}"
        
        # Only store if not already present (keep first occurrence)
        if key not in self.state['hash_index']:
            self.state['hash_index'][key] = file_path
            log_debug(f"Registered in global index: size={file_size}, hash={sample_hash[:8]}... -> {os.path.basename(file_path)}")
            self._save_state()
        else:
            # File already registered, this is a duplicate
            log_debug(f"File already in global index: size={file_size}, hash={sample_hash[:8]}...")
    
    def find_duplicate(self, file_size, sample_hash):
        """
        Find if a file with the same size and hash exists globally.
        
        Args:
            file_size: File size in bytes
            sample_hash: Sample hash to match
            
        Returns:
            str: Path to existing file, or None if no duplicate
        """
        if self.use_db:
            file_path = self.db.find_duplicate_by_hash(file_size, sample_hash)
            if file_path and os.path.exists(file_path):
                return file_path
            return None
        
        if 'hash_index' not in self.state:
            return None
        
        key = f"{file_size}:{sample_hash}"
        file_path = self.state['hash_index'].get(key)
        
        if file_path and os.path.exists(file_path):
            return file_path
        elif file_path:
            # File was registered but no longer exists, remove from index
            log_debug(f"Global index entry points to missing file: {file_path}")
            del self.state['hash_index'][key]
            self._save_state()
        
        return None
    
    def rebuild_from_directory(self, backup_dir):
        """
        Rebuild global hash index by scanning all files in backup directory.
        This is useful for migrating existing backups.
        
        Args:
            backup_dir: Root backup directory to scan
        """
        log_debug(f"Rebuilding global hash index from {backup_dir}...")
        self.state['hash_index'] = {}
        
        count = 0
        for root, _, files in os.walk(backup_dir):
            # Skip hidden files and duplicates folder
            if 'duplicates' in root or '/.backup_state' in root:
                continue
            
            for fname in files:
                if fname.startswith('.'):
                    continue
                
                fpath = os.path.join(root, fname)
                if not os.path.isfile(fpath):
                    continue
                
                try:
                    size = os.path.getsize(fpath)
                    sample_hash = utils.sample_hash_file(fpath)
                    
                    if sample_hash:
                        key = f"{size}:{sample_hash}"
                        # Only register first occurrence
                        if key not in self.state['hash_index']:
                            self.state['hash_index'][key] = fpath
                            count += 1
                except Exception as e:
                    log_debug(f"Error processing {fpath}: {e}")
                    continue
        
        log_debug(f"Rebuilt global hash index with {count} unique files")
        self._save_state()
        return count
