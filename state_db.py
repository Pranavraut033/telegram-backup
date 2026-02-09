"""
SQLite-based state management for Telegram backup.
Provides efficient storage and querying for large backups.
"""
import sqlite3
import os
import json
from datetime import datetime
from contextlib import contextmanager
from typing import Optional, Dict, List, Tuple, Any
import threading


class DatabaseManager:
    """
    Thread-safe SQLite database manager for backup state.
    Handles schema creation, connection pooling, and CRUD operations.
    """
    
    # Schema version for migrations
    SCHEMA_VERSION = 1
    
    def __init__(self, db_path: str):
        """
        Initialize database manager.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._local = threading.local()
        self._ensure_database()
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        if not hasattr(self._local, 'connection') or self._local.connection is None:
            self._local.connection = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                timeout=30.0
            )
            self._local.connection.row_factory = sqlite3.Row
            # Enable foreign keys
            self._local.connection.execute("PRAGMA foreign_keys = ON")
            # Enable Write-Ahead Logging for better concurrency
            self._local.connection.execute("PRAGMA journal_mode = WAL")
        return self._local.connection
    
    @contextmanager
    def get_cursor(self, commit: bool = False):
        """
        Context manager for database cursor with automatic commit/rollback.
        
        Args:
            commit: Whether to commit on successful completion
            
        Yields:
            sqlite3.Cursor
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            yield cursor
            if commit:
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
    
    def _ensure_database(self):
        """Create database and tables if they don't exist."""
        with self.get_cursor(commit=True) as cursor:
            # Schema version table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    description TEXT
                )
            """)
            
            # Check current schema version
            cursor.execute("SELECT MAX(version) FROM schema_version")
            result = cursor.fetchone()
            current_version = result[0] if result[0] is not None else 0
            
            if current_version < self.SCHEMA_VERSION:
                self._create_schema(cursor)
                cursor.execute(
                    "INSERT INTO schema_version (version, description) VALUES (?, ?)",
                    (self.SCHEMA_VERSION, "Initial schema with full duplicate detection support")
                )
    
    def _create_schema(self, cursor: sqlite3.Cursor):
        """Create all tables and indexes."""
        
        # Chats table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chats (
                chat_id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_name TEXT NOT NULL UNIQUE,
                chat_hash TEXT NOT NULL UNIQUE,
                started_at TIMESTAMP,
                last_updated TIMESTAMP,
                completed BOOLEAN DEFAULT FALSE,
                completed_at TIMESTAMP,
                total_files INTEGER DEFAULT 0,
                total_bytes INTEGER DEFAULT 0,
                last_message_id INTEGER
            )
        """)
        
        # Messages table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                filename TEXT,
                file_path TEXT,
                file_size INTEGER,
                sample_hash TEXT,
                full_hash TEXT,
                downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chat_id) REFERENCES chats(chat_id) ON DELETE CASCADE,
                UNIQUE(chat_id, message_id)
            )
        """)
        
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_sample_hash ON messages(sample_hash)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_file_path ON messages(file_path)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_chat_id ON messages(chat_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_file_size ON messages(file_size)")
        
        # File hashes table (global index)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS file_hashes (
                hash_key TEXT PRIMARY KEY,
                file_size INTEGER NOT NULL,
                sample_hash TEXT NOT NULL,
                first_occurrence_path TEXT,
                first_message_id INTEGER,
                first_chat_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (first_message_id) REFERENCES messages(id) ON DELETE SET NULL,
                FOREIGN KEY (first_chat_id) REFERENCES chats(chat_id) ON DELETE SET NULL
            )
        """)
        
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_hashes_sample_hash ON file_hashes(sample_hash)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_hashes_size ON file_hashes(file_size)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_hashes_composite ON file_hashes(file_size, sample_hash)")
        
        # Duplicates table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS duplicates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                duplicate_msg_id INTEGER NOT NULL,
                canonical_chat_id INTEGER NOT NULL,
                canonical_msg_id INTEGER NOT NULL,
                detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chat_id) REFERENCES chats(chat_id) ON DELETE CASCADE,
                FOREIGN KEY (canonical_chat_id) REFERENCES chats(chat_id) ON DELETE CASCADE,
                UNIQUE(chat_id, duplicate_msg_id)
            )
        """)
        
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_duplicates_canonical ON duplicates(canonical_chat_id, canonical_msg_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_duplicates_chat ON duplicates(chat_id)")
        
        # Message status table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS message_status (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                status_reason TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chat_id) REFERENCES chats(chat_id) ON DELETE CASCADE,
                UNIQUE(chat_id, message_id)
            )
        """)
        
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_message_status_status ON message_status(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_message_status_chat ON message_status(chat_id)")
    
    # ==================== Chat Operations ====================
    
    def get_or_create_chat(self, chat_name: str, chat_hash: str) -> int:
        """
        Get existing chat or create new one.
        
        Args:
            chat_name: Display name of the chat
            chat_hash: Unique hash identifier for the chat
            
        Returns:
            int: chat_id
        """
        with self.get_cursor(commit=True) as cursor:
            # Try to get existing
            cursor.execute("SELECT chat_id FROM chats WHERE chat_hash = ?", (chat_hash,))
            result = cursor.fetchone()
            
            if result:
                return result['chat_id']
            
            # Create new
            cursor.execute("""
                INSERT INTO chats (chat_name, chat_hash, started_at, last_updated)
                VALUES (?, ?, ?, ?)
            """, (chat_name, chat_hash, datetime.now().isoformat(), datetime.now().isoformat()))
            
            return cursor.lastrowid
    
    def get_chat_by_hash(self, chat_hash: str) -> Optional[Dict]:
        """Get chat by hash."""
        with self.get_cursor() as cursor:
            cursor.execute("SELECT * FROM chats WHERE chat_hash = ?", (chat_hash,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def update_chat_stats(self, chat_id: int, total_files: int = None, 
                          total_bytes: int = None, last_message_id: int = None):
        """Update chat statistics."""
        with self.get_cursor(commit=True) as cursor:
            updates = []
            params = []
            
            if total_files is not None:
                updates.append("total_files = ?")
                params.append(total_files)
            
            if total_bytes is not None:
                updates.append("total_bytes = ?")
                params.append(total_bytes)
            
            if last_message_id is not None:
                updates.append("last_message_id = ?")
                params.append(last_message_id)
            
            if updates:
                updates.append("last_updated = ?")
                params.append(datetime.now().isoformat())
                params.append(chat_id)
                
                query = f"UPDATE chats SET {', '.join(updates)} WHERE chat_id = ?"
                cursor.execute(query, params)
    
    def mark_chat_completed(self, chat_id: int):
        """Mark chat backup as completed."""
        with self.get_cursor(commit=True) as cursor:
            cursor.execute("""
                UPDATE chats 
                SET completed = TRUE, completed_at = ?, last_updated = ?
                WHERE chat_id = ?
            """, (datetime.now().isoformat(), datetime.now().isoformat(), chat_id))
    
    def get_chat_stats(self, chat_id: int) -> Dict:
        """Get chat statistics."""
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT 
                    total_files, total_bytes, last_message_id,
                    completed, completed_at, started_at, last_updated
                FROM chats WHERE chat_id = ?
            """, (chat_id,))
            
            row = cursor.fetchone()
            if not row:
                return {}
            
            return dict(row)
    
    # ==================== Message Operations ====================
    
    def add_message(self, chat_id: int, message_id: int, filename: str = None,
                   file_path: str = None, file_size: int = 0,
                   sample_hash: str = None, full_hash: str = None) -> int:
        """
        Add or update a downloaded message.
        
        Returns:
            int: message record id
        """
        with self.get_cursor(commit=True) as cursor:
            cursor.execute("""
                INSERT INTO messages 
                (chat_id, message_id, filename, file_path, file_size, sample_hash, full_hash, downloaded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, message_id) DO UPDATE SET
                    filename = excluded.filename,
                    file_path = excluded.file_path,
                    file_size = excluded.file_size,
                    sample_hash = excluded.sample_hash,
                    full_hash = excluded.full_hash,
                    downloaded_at = excluded.downloaded_at
            """, (chat_id, message_id, filename, file_path, file_size, sample_hash, 
                  full_hash, datetime.now().isoformat()))

            cursor.execute(
                "SELECT id FROM messages WHERE chat_id = ? AND message_id = ?",
                (chat_id, message_id)
            )
            row = cursor.fetchone()
            return row['id'] if row else cursor.lastrowid
    
    def get_message(self, chat_id: int, message_id: int) -> Optional[Dict]:
        """Get message info."""
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT * FROM messages 
                WHERE chat_id = ? AND message_id = ?
            """, (chat_id, message_id))
            
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def is_message_downloaded(self, chat_id: int, message_id: int) -> bool:
        """Check if message is downloaded."""
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT 1 FROM messages 
                WHERE chat_id = ? AND message_id = ?
            """, (chat_id, message_id))
            
            return cursor.fetchone() is not None
    
    def get_all_messages(self, chat_id: int) -> List[Dict]:
        """Get all messages for a chat."""
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT * FROM messages WHERE chat_id = ?
                ORDER BY message_id
            """, (chat_id,))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def update_file_path(self, old_path: str, new_path: str) -> bool:
        """Update file path for a message."""
        with self.get_cursor(commit=True) as cursor:
            cursor.execute("""
                UPDATE messages 
                SET file_path = ?, filename = ?
                WHERE file_path = ?
            """, (new_path, os.path.basename(new_path), old_path))
            
            return cursor.rowcount > 0
    
    # ==================== Hash Index Operations ====================
    
    def register_file_hash(self, file_size: int, sample_hash: str, 
                          file_path: str, message_id: int = None, 
                          chat_id: int = None):
        """
        Register file in global hash index.
        Only stores first occurrence.
        """
        hash_key = f"{file_size}:{sample_hash}"
        
        with self.get_cursor(commit=True) as cursor:
            # Check if already exists
            cursor.execute("SELECT hash_key FROM file_hashes WHERE hash_key = ?", (hash_key,))
            if cursor.fetchone():
                return  # Already registered
            
            cursor.execute("""
                INSERT INTO file_hashes 
                (hash_key, file_size, sample_hash, first_occurrence_path, first_message_id, first_chat_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (hash_key, file_size, sample_hash, file_path, message_id, chat_id))
    
    def find_duplicate_by_hash(self, file_size: int, sample_hash: str) -> Optional[str]:
        """
        Find duplicate file by size and hash.
        
        Returns:
            str: Path to first occurrence, or None
        """
        hash_key = f"{file_size}:{sample_hash}"
        
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT first_occurrence_path FROM file_hashes 
                WHERE hash_key = ?
            """, (hash_key,))
            
            row = cursor.fetchone()
            return row['first_occurrence_path'] if row else None
    
    def find_duplicate_in_chat(self, chat_id: int, file_size: int, 
                               sample_hash: str) -> Optional[Tuple[int, str]]:
        """
        Find duplicate within same chat.
        
        Returns:
            Tuple[int, str]: (message_id, file_path) or None
        """
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT message_id, file_path FROM messages
                WHERE chat_id = ? AND file_size = ? AND sample_hash = ?
                ORDER BY message_id
                LIMIT 1
            """, (chat_id, file_size, sample_hash))
            
            row = cursor.fetchone()
            return (row['message_id'], row['file_path']) if row else None
    
    # ==================== Duplicate Tracking ====================
    
    def mark_duplicate(self, chat_id: int, duplicate_msg_id: int,
                      canonical_chat_id: int, canonical_msg_id: int):
        """Mark a message as duplicate of another."""
        with self.get_cursor(commit=True) as cursor:
            cursor.execute("""
                INSERT INTO duplicates 
                (chat_id, duplicate_msg_id, canonical_chat_id, canonical_msg_id)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(chat_id, duplicate_msg_id) DO NOTHING
            """, (chat_id, duplicate_msg_id, canonical_chat_id, canonical_msg_id))
    
    def get_duplicate_info(self, chat_id: int, message_id: int) -> Optional[Dict]:
        """Get duplicate information for a message."""
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT canonical_chat_id, canonical_msg_id 
                FROM duplicates
                WHERE chat_id = ? AND duplicate_msg_id = ?
            """, (chat_id, message_id))
            
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_all_duplicates(self, chat_id: int = None) -> List[Dict]:
        """Get all duplicates, optionally filtered by chat."""
        with self.get_cursor() as cursor:
            if chat_id:
                cursor.execute("""
                    SELECT * FROM duplicates WHERE chat_id = ?
                    ORDER BY detected_at DESC
                """, (chat_id,))
            else:
                cursor.execute("SELECT * FROM duplicates ORDER BY detected_at DESC")
            
            return [dict(row) for row in cursor.fetchall()]
    
    # ==================== Message Status Operations ====================
    
    def set_message_status(self, chat_id: int, message_id: int, 
                          status: str, reason: str = None):
        """
        Set message status (downloaded, skipped, failed).
        """
        with self.get_cursor(commit=True) as cursor:
            cursor.execute("""
                INSERT INTO message_status 
                (chat_id, message_id, status, status_reason, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, message_id) DO UPDATE SET
                    status = excluded.status,
                    status_reason = excluded.status_reason,
                    updated_at = excluded.updated_at
            """, (chat_id, message_id, status, reason, datetime.now().isoformat()))
    
    def get_message_status(self, chat_id: int, message_id: int) -> Optional[str]:
        """Get message status."""
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT status FROM message_status
                WHERE chat_id = ? AND message_id = ?
            """, (chat_id, message_id))
            
            row = cursor.fetchone()
            return row['status'] if row else None
    
    def get_status_counts(self, chat_id: int) -> Dict[str, int]:
        """Get counts of messages by status."""
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT status, COUNT(*) as count
                FROM message_status
                WHERE chat_id = ?
                GROUP BY status
            """, (chat_id,))
            
            return {row['status']: row['count'] for row in cursor.fetchall()}
    
    def get_messages_by_status(self, chat_id: int, status: str) -> List[int]:
        """Get all message IDs with given status."""
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT message_id FROM message_status
                WHERE chat_id = ? AND status = ?
                ORDER BY message_id
            """, (chat_id, status))
            
            return [row['message_id'] for row in cursor.fetchall()]
    
    # ==================== Utility Operations ====================
    
    def vacuum(self):
        """Optimize database by vacuuming."""
        conn = self._get_connection()
        conn.execute("VACUUM")
        conn.commit()
    
    def get_database_size(self) -> int:
        """Get database file size in bytes."""
        return os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0
    
    def export_chat_to_json(self, chat_id: int) -> Dict:
        """
        Export chat state to JSON format (for backup/compatibility).
        
        Returns:
            Dict: JSON-compatible state dictionary
        """
        with self.get_cursor() as cursor:
            # Get chat info
            cursor.execute("SELECT * FROM chats WHERE chat_id = ?", (chat_id,))
            chat = cursor.fetchone()
            if not chat:
                return {}
            
            # Get all messages
            cursor.execute("""
                SELECT message_id, filename, file_size, file_path, sample_hash, full_hash
                FROM messages WHERE chat_id = ?
            """, (chat_id,))
            messages = cursor.fetchall()
            
            # Get status info
            cursor.execute("""
                SELECT message_id, status FROM message_status WHERE chat_id = ?
            """, (chat_id,))
            statuses = {row['message_id']: row['status'] for row in cursor.fetchall()}
            
            # Get duplicates
            cursor.execute("""
                SELECT duplicate_msg_id, canonical_msg_id FROM duplicates WHERE chat_id = ?
            """, (chat_id,))
            duplicates = {row['duplicate_msg_id']: row['canonical_msg_id'] 
                         for row in cursor.fetchall()}
            
            # Build JSON structure
            downloaded_messages = {}
            hash_index = {}
            
            for msg in messages:
                msg_id = str(msg['message_id'])
                downloaded_messages[msg_id] = {
                    'filename': msg['filename'],
                    'size': msg['file_size'],
                    'path': msg['file_path'],
                    'sample_hash': msg['sample_hash'],
                    'full_hash': msg['full_hash']
                }
                
                # Build hash index
                if msg['sample_hash'] and msg['file_size']:
                    key = f"{msg['file_size']}:{msg['sample_hash']}"
                    if key not in hash_index:
                        hash_index[key] = []
                    hash_index[key].append(msg_id)
            
            return {
                'chat_name': chat['chat_name'],
                'started_at': chat['started_at'],
                'last_updated': chat['last_updated'],
                'completed': bool(chat['completed']),
                'completed_at': chat['completed_at'],
                'downloaded_messages': downloaded_messages,
                'skipped_messages': [m for m, s in statuses.items() if s == 'skipped'],
                'failed_messages': [m for m, s in statuses.items() if s == 'failed'],
                'total_files': chat['total_files'],
                'total_bytes': chat['total_bytes'],
                'last_message_id': chat['last_message_id'],
                'hash_index': hash_index,
                'duplicate_map': duplicates
            }
    
    def close(self):
        """Close database connection."""
        if hasattr(self._local, 'connection') and self._local.connection:
            self._local.connection.close()
            self._local.connection = None
    
    # ==================== Migration and Utility Operations ====================
    
    def export_all_to_json(self, output_dir: str) -> List[str]:
        """
        Export all chats to JSON format for backup/portability.
        
        Args:
            output_dir: Directory to save JSON files
            
        Returns:
            List of created file paths
        """
        import os
        
        os.makedirs(output_dir, exist_ok=True)
        exported_files = []
        
        with self.get_cursor() as cursor:
            # Get all chats
            cursor.execute("SELECT chat_id, chat_name, chat_hash FROM chats")
            chats = cursor.fetchall()
            
            for chat in chats:
                chat_id = chat['chat_id']
                chat_hash = chat['chat_hash']
                
                # Export chat to JSON
                state_json = self.export_chat_to_json(chat_id)
                
                # Save to file
                filename = f".backup_state_{chat_hash}.json"
                filepath = os.path.join(output_dir, filename)
                
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(state_json, f, indent=2)
                
                exported_files.append(filepath)
        
        # Export global state
        global_state = self._export_global_state()
        global_filepath = os.path.join(output_dir, ".backup_state_global.json")
        with open(global_filepath, 'w', encoding='utf-8') as f:
            json.dump(global_state, f, indent=2)
        exported_files.append(global_filepath)
        
        return exported_files
    
    def _export_global_state(self) -> Dict:
        """Export global hash index to JSON format."""
        with self.get_cursor() as cursor:
            cursor.execute("SELECT hash_key, first_occurrence_path FROM file_hashes")
            hash_entries = cursor.fetchall()
            
            hash_index = {row['hash_key']: row['first_occurrence_path'] 
                         for row in hash_entries if row['first_occurrence_path']}
            
            return {
                'created_at': datetime.now().isoformat(),
                'last_updated': datetime.now().isoformat(),
                'hash_index': hash_index,
                'version': '1.0'
            }
    
    def get_stats_summary(self) -> Dict:
        """
        Get comprehensive statistics about the database.
        
        Returns:
            Dict with database statistics
        """
        with self.get_cursor() as cursor:
            # Chat counts
            cursor.execute("SELECT COUNT(*) as total, SUM(CASE WHEN completed THEN 1 ELSE 0 END) as completed FROM chats")
            chat_stats = dict(cursor.fetchone())
            
            # Message counts
            cursor.execute("SELECT COUNT(*) as total FROM messages")
            message_count = cursor.fetchone()['total']
            
            # Status counts
            cursor.execute("SELECT status, COUNT(*) as count FROM message_status GROUP BY status")
            status_counts = {row['status']: row['count'] for row in cursor.fetchall()}
            
            # Duplicate counts
            cursor.execute("SELECT COUNT(*) as total FROM duplicates")
            duplicate_count = cursor.fetchone()['total']
            
            # Hash index size
            cursor.execute("SELECT COUNT(*) as total FROM file_hashes")
            hash_count = cursor.fetchone()['total']
            
            # Total size
            cursor.execute("SELECT SUM(total_bytes) as total FROM chats")
            total_bytes = cursor.fetchone()['total'] or 0
            
            return {
                'chats': {
                    'total': chat_stats['total'],
                    'completed': chat_stats['completed']
                },
                'messages': {
                    'total': message_count,
                    'downloaded': status_counts.get('downloaded', 0),
                    'skipped': status_counts.get('skipped', 0),
                    'failed': status_counts.get('failed', 0)
                },
                'duplicates': duplicate_count,
                'hash_index_size': hash_count,
                'total_bytes': total_bytes,
                'database_size': self.get_database_size()
            }
    
    def cleanup_orphaned_records(self) -> Dict[str, int]:
        """
        Clean up orphaned records and validate foreign key integrity.
        
        Returns:
            Dict with counts of cleaned records
        """
        counts = {}
        
        with self.get_cursor(commit=True) as cursor:
            # Remove duplicates pointing to non-existent messages
            cursor.execute("""
                DELETE FROM duplicates 
                WHERE NOT EXISTS (
                    SELECT 1 FROM messages 
                    WHERE messages.chat_id = duplicates.canonical_chat_id 
                    AND messages.message_id = duplicates.canonical_msg_id
                )
                AND canonical_msg_id != -1
            """)
            counts['orphaned_duplicates'] = cursor.rowcount
            
            # Remove hash entries pointing to non-existent files
            cursor.execute("""
                DELETE FROM file_hashes 
                WHERE first_occurrence_path IS NOT NULL 
                AND NOT EXISTS (
                    SELECT 1 FROM messages 
                    WHERE messages.file_path = file_hashes.first_occurrence_path
                )
            """)
            counts['orphaned_hashes'] = cursor.rowcount
            
            # Remove message status for non-existent messages
            cursor.execute("""
                DELETE FROM message_status 
                WHERE NOT EXISTS (
                    SELECT 1 FROM chats 
                    WHERE chats.chat_id = message_status.chat_id
                )
            """)
            counts['orphaned_statuses'] = cursor.rowcount
        
        return counts
    
    def rebuild_hash_index_from_messages(self) -> int:
        """
        Rebuild global hash index from all messages in database.
        Useful for fixing inconsistencies.
        
        Returns:
            Number of hash entries created
        """
        count = 0
        
        with self.get_cursor(commit=True) as cursor:
            # Clear existing hash index
            cursor.execute("DELETE FROM file_hashes")
            
            # Rebuild from messages
            cursor.execute("""
                SELECT DISTINCT file_size, sample_hash, file_path, id, chat_id
                FROM messages
                WHERE sample_hash IS NOT NULL AND file_size > 0
                ORDER BY downloaded_at ASC
            """)
            
            seen_hashes = set()
            for row in cursor.fetchall():
                hash_key = f"{row['file_size']}:{row['sample_hash']}"
                
                # Only add first occurrence
                if hash_key not in seen_hashes:
                    cursor.execute("""
                        INSERT INTO file_hashes 
                        (hash_key, file_size, sample_hash, first_occurrence_path, first_message_id, first_chat_id)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (hash_key, row['file_size'], row['sample_hash'], 
                          row['file_path'], row['id'], row['chat_id']))
                    
                    seen_hashes.add(hash_key)
                    count += 1
        
        return count
    
    def get_duplicate_report(self, chat_id: int = None) -> List[Dict]:
        """
        Generate a detailed duplicate report.
        
        Args:
            chat_id: Optional chat_id to filter by
            
        Returns:
            List of duplicate entries with details
        """
        with self.get_cursor() as cursor:
            if chat_id:
                cursor.execute("""
                    SELECT 
                        d.duplicate_msg_id,
                        d.canonical_msg_id,
                        m1.file_path as dup_path,
                        m1.file_size as dup_size,
                        m2.file_path as canon_path,
                        c.chat_name
                    FROM duplicates d
                    LEFT JOIN messages m1 ON d.chat_id = m1.chat_id AND d.duplicate_msg_id = m1.message_id
                    LEFT JOIN messages m2 ON d.canonical_chat_id = m2.chat_id AND d.canonical_msg_id = m2.message_id
                    LEFT JOIN chats c ON d.chat_id = c.chat_id
                    WHERE d.chat_id = ?
                    ORDER BY d.detected_at DESC
                """, (chat_id,))
            else:
                cursor.execute("""
                    SELECT 
                        d.duplicate_msg_id,
                        d.canonical_msg_id,
                        m1.file_path as dup_path,
                        m1.file_size as dup_size,
                        m2.file_path as canon_path,
                        c.chat_name
                    FROM duplicates d
                    LEFT JOIN messages m1 ON d.chat_id = m1.chat_id AND d.duplicate_msg_id = m1.message_id
                    LEFT JOIN messages m2 ON d.canonical_chat_id = m2.chat_id AND d.canonical_msg_id = m2.message_id
                    LEFT JOIN chats c ON d.chat_id = c.chat_id
                    ORDER BY d.detected_at DESC
                """)
            
            return [dict(row) for row in cursor.fetchall()]
