"""
Download state management for resume capability in Telegram backup.
Tracks progress and enables resuming downloads.
"""
import json
import os
from datetime import datetime
import hashlib
import config


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
                        downloaded[msg_id] = {
                            'filename': fname,
                            'size': size,
                            'path': fpath
                        }
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
        Loads or creates a JSON state file for tracking progress.
        """
        self.output_dir = output_dir
        self.chat_name = chat_name
        self.state_file = os.path.join(output_dir, f".backup_state_{self._sanitize_for_filename(chat_name)}.json")
        self.state = self._load_state()
    
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
            'downloaded_messages': {},  # Dict: {message_id: {"filename": str, "size": int, "path": str}}
            'skipped_messages': [],
            'failed_messages': [],
            'total_files': 0,
            'total_bytes': 0,
            'last_message_id': None
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
        
        # Migrate format if needed
        self._migrate_to_dict_format()
        
        file_info = self.state['downloaded_messages'].get(str(message_id))
        if not file_info:
            return False
        
        file_path = file_info.get('path')
        expected_size = file_info.get('size', 0)
        
        # Check if file exists
        if not file_path or not os.path.exists(file_path):
            log_debug(f"File not found for message {message_id}: {file_path}")
            return False
        
        # Check if file size is reasonable (not corrupted/incomplete)
        try:
            actual_size = os.path.getsize(file_path)
            if actual_size == 0:
                log_debug(f"File is empty for message {message_id}: {file_path}")
                return False
            
            # If we have expected size, validate it matches (within 1% tolerance for metadata)
            if expected_size > 0:
                size_diff = abs(actual_size - expected_size)
                tolerance = expected_size * 0.01  # 1% tolerance
                if size_diff > tolerance and size_diff > 1024:  # Allow 1KB difference for small files
                    log_debug(f"File size mismatch for message {message_id}: expected {expected_size}, got {actual_size}")
                    return False
            
            return True
        except Exception as e:
            log_debug(f"Error validating file for message {message_id}: {e}")
            return False
    
    def is_message_downloaded(self, message_id):
        """
        Return True if the message is already downloaded and file is valid.
        """
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
        return message_id in self.state['skipped_messages']
    
    def is_message_failed(self, message_id):
        """
        Return True if the message failed before.
        """
        return message_id in self.state['failed_messages']
    
    def update_file_path(self, old_path, new_path):
        """
        Update file path in state when a file is renamed.
        """
        if isinstance(self.state['downloaded_messages'], dict):
            for msg_id, file_info in self.state['downloaded_messages'].items():
                if file_info.get('path') == old_path:
                    file_info['path'] = new_path
                    file_info['filename'] = os.path.basename(new_path)
                    self._save_state()
                    return True
        return False
    
    def mark_downloaded(self, message_id, file_path=None, file_size=0):
        """
        Mark a message as successfully downloaded, with file info.
        """
        msg_id_str = str(message_id)
        
        # Migrate old format to new format if needed
        self._migrate_to_dict_format()
        
        # Add or update entry
        if msg_id_str not in self.state['downloaded_messages']:
            self.state['total_files'] += 1
            self.state['total_bytes'] += file_size
            log_debug(f"Marked message {message_id} as downloaded: {os.path.basename(file_path) if file_path else 'N/A'}")
        
        self.state['downloaded_messages'][msg_id_str] = {
            'filename': os.path.basename(file_path) if file_path else 'unknown',
            'size': file_size,
            'path': file_path
        }
        
        self.state['last_message_id'] = message_id
        self._save_state()
    
    def mark_skipped(self, message_id):
        """
        Mark a message as skipped.
        """
        if message_id not in self.state['skipped_messages']:
            self.state['skipped_messages'].append(message_id)
            log_debug(f"Marked message {message_id} as skipped")
        
        self.state['last_message_id'] = message_id
        self._save_state()
    
    def mark_failed(self, message_id):
        """
        Mark a message as failed.
        """
        if message_id not in self.state['failed_messages']:
            self.state['failed_messages'].append(message_id)
            log_debug(f"Marked message {message_id} as failed")
        
        self.state['last_message_id'] = message_id
        self._save_state()
    
    def mark_completed(self):
        """
        Mark the backup as completed.
        """
        self.state['completed'] = True
        self.state['completed_at'] = datetime.now().isoformat()
        self._save_state()
    
    def get_stats(self):
        """
        Get current state statistics as a dict.
        """
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
