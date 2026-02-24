"""
Rclone execution helpers for cloud transfer actions.
"""
import shlex
import shutil
import subprocess
import json
import os
from typing import List, Dict, Optional
from rich.console import Console
import config

console = Console()


class RcloneManager:
    def __init__(self, rclone_bin=None, extra_flags=None):
        self.rclone_bin = (rclone_bin or config.RCLONE_BIN).strip() or "rclone"
        self.extra_flags = extra_flags if extra_flags is not None else config.RCLONE_FLAGS

    def is_available(self):
        return shutil.which(self.rclone_bin) is not None

    def _build_base_command(self, action, source_path, remote_path):
        cmd = [self.rclone_bin, action, source_path, remote_path, "--progress"]
        if self.extra_flags:
            cmd.extend(shlex.split(self.extra_flags))
        return cmd

    def _run_command(self, cmd):
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            stdout = (result.stdout or "").strip()
            err_msg = stderr if stderr else stdout
            raise RuntimeError(err_msg or "rclone command failed")
        return result

    def copy_to_remote(self, source_path, remote_path):
        cmd = self._build_base_command("copy", source_path, remote_path)
        return self._run_command(cmd)

    def move_to_remote(self, source_path, remote_path):
        cmd = self._build_base_command("move", source_path, remote_path)
        return self._run_command(cmd)

    def sync_to_remote(self, source_path, remote_path):
        cmd = self._build_base_command("sync", source_path, remote_path)
        return self._run_command(cmd)
    
    def list_remote_files(self, remote_path: str, recursive: bool = True) -> List[Dict]:
        """
        List files in remote path with metadata.
        
        Args:
            remote_path: Remote path to list (e.g., "myremote:telegram-backup")
            recursive: Whether to list recursively
        
        Returns:
            List of dicts with keys: name, path, size, modtime, ishash (optional)
        """
        cmd = [self.rclone_bin, "lsjson"]
        if recursive:
            cmd.append("-R")
        cmd.extend(["--hash", "--no-mimetype", remote_path])
        
        if self.extra_flags:
            cmd.extend(shlex.split(self.extra_flags))
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode != 0:
                stderr = (result.stderr or "").strip()
                raise RuntimeError(f"rclone lsjson failed: {stderr}")
            
            # Parse JSON output
            files = json.loads(result.stdout)
            
            # Normalize to consistent format
            normalized = []
            for item in files:
                if item.get('IsDir', False):
                    continue  # Skip directories
                
                # Extract hash if available (SHA-256, MD5, etc.)
                hashes = item.get('Hashes', {})
                file_hash = hashes.get('SHA-256') or hashes.get('MD5') or hashes.get('SHA1')
                
                normalized.append({
                    'name': item.get('Name', ''),
                    'path': item.get('Path', ''),
                    'size': item.get('Size', 0),
                    'modtime': item.get('ModTime', ''),
                    'hash': file_hash,
                    'ishash': item.get('IsBucket', False)
                })
            
            return normalized
        except subprocess.TimeoutExpired:
            raise RuntimeError("rclone lsjson timed out (5 minutes)")
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Failed to parse rclone JSON output: {e}")
        except Exception as e:
            raise RuntimeError(f"Error listing remote files: {e}")

    def list_remote_dirs(self, remote_path: str, recursive: bool = False) -> List[str]:
        """
        List directories in a remote path.

        Args:
            remote_path: Remote path to list (e.g., "myremote:telegram-backup")
            recursive: Whether to list directories recursively

        Returns:
            List of directory paths relative to remote_path
        """
        cmd = [self.rclone_bin, "lsjson"]
        if recursive:
            cmd.append("-R")
        cmd.extend(["--dirs-only", "--no-mimetype", remote_path])

        if self.extra_flags:
            cmd.extend(shlex.split(self.extra_flags))

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode != 0:
                stderr = (result.stderr or "").strip()
                raise RuntimeError(f"rclone lsjson --dirs-only failed: {stderr}")

            items = json.loads(result.stdout)
            directories = []
            for item in items:
                if not item.get('IsDir', False):
                    continue
                dir_path = item.get('Path') or item.get('Name')
                if dir_path:
                    directories.append(dir_path)

            return directories
        except subprocess.TimeoutExpired:
            raise RuntimeError("rclone lsjson --dirs-only timed out (5 minutes)")
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Failed to parse rclone directory JSON output: {e}")
        except Exception as e:
            raise RuntimeError(f"Error listing remote directories: {e}")
    
    def check_remote_exists(self, remote_path: str) -> bool:
        """
        Check if a remote path exists.
        
        Args:
            remote_path: Full remote path to check
        
        Returns:
            bool: True if exists, False otherwise
        """
        cmd = [self.rclone_bin, "lsf", remote_path]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return result.returncode == 0 and bool(result.stdout.strip())
        except Exception:
            return False
    
    def get_remote_size(self, remote_path: str) -> Optional[int]:
        """
        Get size of a specific remote file.
        
        Args:
            remote_path: Full path to remote file
        
        Returns:
            int: File size in bytes, or None if not found
        """
        cmd = [self.rclone_bin, "size", "--json", remote_path]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                return None
            
            size_info = json.loads(result.stdout)
            return size_info.get('bytes', 0)
        except Exception:
            return None
