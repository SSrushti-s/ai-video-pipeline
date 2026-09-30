import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class FreshnessConfig:
    max_age_hours: int = int(os.getenv("MAX_AGE_HOURS", 148))

FRESHNESS = FreshnessConfig()
DATABASE_URL = os.getenv("DATABASE_URL", "")
TARGET_COUNT = int(os.getenv("TARGET_COUNT", 50))

# Safe-mode toggles
INGEST_TO_DB = os.getenv("INGEST_TO_DB", "false").lower() == "true"
OUTPUT_FILE = os.getenv("OUTPUT_FILE", "data/output_videos.json")
SEEN_FILE = os.getenv("SEEN_FILE", "data/seen_ids.txt")