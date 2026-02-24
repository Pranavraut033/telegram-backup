"""
Persistent transfer state for cumulative auto-transfer thresholds.
"""
import json
import os
from datetime import datetime


class TransferState:
    def __init__(self, output_dir):
        self.output_dir = output_dir
        self.state_file = os.path.join(output_dir, ".cloud_transfer_state.json")
        self.state = self._load_state()

    def _load_state(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        return {
            "cumulative_bytes_since_transfer": 0,
            "last_transfer_at": None,
            "last_transfer_mode": None,
            "last_transfer_bytes": 0
        }

    def _save_state(self):
        os.makedirs(self.output_dir, exist_ok=True)
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2)

    def add_downloaded_bytes(self, count):
        current = int(self.state.get("cumulative_bytes_since_transfer", 0) or 0)
        self.state["cumulative_bytes_since_transfer"] = max(0, current + int(count or 0))
        self._save_state()
        return self.state["cumulative_bytes_since_transfer"]

    def get_cumulative_bytes(self):
        return int(self.state.get("cumulative_bytes_since_transfer", 0) or 0)

    def mark_transfer_completed(self, mode):
        self.state["last_transfer_at"] = datetime.now().isoformat()
        self.state["last_transfer_mode"] = mode
        self.state["last_transfer_bytes"] = int(self.state.get("cumulative_bytes_since_transfer", 0) or 0)
        self.state["cumulative_bytes_since_transfer"] = 0
        self._save_state()
