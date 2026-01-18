"""
Utility functions for file and directory handling, naming, and formatting.
Simple, clear helpers for the backup tool.
"""
import os
import re
from pathlib import Path
from datetime import datetime


def sanitize_filename(filename):
    """
    Remove or replace invalid characters from a filename.
    Returns a safe string for saving files.
    """
    if not filename:
        return f"unnamed_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    # Replace invalid characters
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    # Remove leading/trailing spaces and dots
    filename = filename.strip('. ')
    # Limit length
    if len(filename) > 200:
        name, ext = os.path.splitext(filename)
        filename = name[:200-len(ext)] + ext
    
    return filename or "unnamed"


def sanitize_dirname(dirname):
    """
    Remove or replace invalid characters from a directory name.
    Returns a safe string for directory creation.
    """
    if not dirname:
        return "unnamed_chat"
    
    dirname = re.sub(r'[<>:"/\\|?*]', '_', dirname)
    dirname = dirname.strip('. ')
    return dirname[:100] or "unnamed_chat"


def create_directory(path):
    """
    Create a directory if it doesn't exist.
    Returns the path.
    """
    Path(path).mkdir(parents=True, exist_ok=True)
    return path


def get_file_extension(mime_type):
    """
    Get file extension from a MIME type string.
    Returns the extension or empty string.
    """
    mime_map = {
        'image/jpeg': '.jpg',
        'image/png': '.png',
        'image/gif': '.gif',
        'image/webp': '.webp',
        'video/mp4': '.mp4',
        'video/quicktime': '.mov',
        'audio/mpeg': '.mp3',
        'audio/ogg': '.ogg',
        'application/pdf': '.pdf',
        'application/zip': '.zip',
    }
    return mime_map.get(mime_type, '')


def file_exists(filepath):
    """
    Check if a file exists at the given path.
    """
    return os.path.exists(filepath)


def get_unique_filepath(directory, filename):
    """
    Generate a unique file path in the directory to avoid overwriting existing files.
    """
    base_path = os.path.join(directory, filename)
    
    if not file_exists(base_path):
        return base_path
    
    name, ext = os.path.splitext(filename)
    counter = 1
    
    while True:
        new_path = os.path.join(directory, f"{name}_{counter}{ext}")
        if not file_exists(new_path):
            return new_path
        counter += 1


def format_bytes(bytes_size):
    """
    Format a byte size as a human-readable string (e.g., KB, MB, GB).
    """
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.2f} TB"


def format_duration(seconds):
    """
    Format a duration in seconds as a human-readable string.
    """
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        return f"{seconds/60:.1f}m"
    else:
        return f"{seconds/3600:.1f}h"


def rename_old_topic_folders(chat_dir, topics):
    """
    Rename old topic folders from 'Topic #number' format to actual topic names.
    Returns a dict mapping old paths to new paths.
    """
    renamed_folders = {}
    
    if not os.path.exists(chat_dir):
        return renamed_folders
    
    # Build mapping of topic IDs to names
    topic_map = {}
    for topic in topics:
        topic_id = topic.get('id') if isinstance(topic, dict) else getattr(topic, 'id', None)
        topic_title = topic.get('title') if isinstance(topic, dict) else getattr(topic, 'title', None)
        
        if topic_id and topic_title:
            # Check if it's not the default "Topic {id}" format
            if topic_title != f"Topic {topic_id}":
                topic_map[topic_id] = topic_title
    
    # Scan existing directories for old format
    for item in os.listdir(chat_dir):
        item_path = os.path.join(chat_dir, item)
        
        if os.path.isdir(item_path):
            # Check if it matches "Topic #number" format
            match = re.match(r'^Topic\s+(\d+)$', item)
            if match:
                topic_id = int(match.group(1))
                
                # If we have a proper name for this topic, rename it
                if topic_id in topic_map:
                    new_name = sanitize_dirname(topic_map[topic_id])
                    new_path = os.path.join(chat_dir, new_name)
                    
                    # If new path doesn't exist, rename
                    if not os.path.exists(new_path):
                        try:
                            os.rename(item_path, new_path)
                            renamed_folders[item_path] = new_path
                        except Exception as e:
                            # If rename fails, we'll just use the new name going forward
                            pass
    
    return renamed_folders
