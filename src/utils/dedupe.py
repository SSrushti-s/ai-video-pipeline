import os
import logging
from src.db.database import Database
from config.settings import SEEN_FILE

logger = logging.getLogger("graphone.dedupe")

class SeenStore:
    def __init__(self, db: Database | None = None):
        self.db = db
        self._seen: set[str] = set()
        self._load_local_seen()

    def _load_local_seen(self):
        """Load seen video IDs from local file if it exists."""
        if os.path.exists(SEEN_FILE):
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    cleaned = line.strip()
                    if cleaned:
                        self._seen.add(cleaned)

    def _persist_local_seen(self, video_id: str):
        """Append seen video ID to local file."""
        os.makedirs(os.path.dirname(SEEN_FILE), exist_ok=True)
        with open(SEEN_FILE, "a", encoding="utf-8") as f:
            f.write(f"{video_id}\n")

    async def is_seen(self, video_id: str, session=None) -> bool:
        # Check local memory / local file first
        if video_id in self._seen:
            return True

        # Check DB if database is active
        if self.db and self.db.pool:
            existing = await self.db.get_existing_video_ids([video_id])
            if video_id in existing:
                self._seen.add(video_id)
                return True

        return False

    async def mark_seen(self, video_id: str, session=None):
        self._seen.add(video_id)
        self._persist_local_seen(video_id)