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
import os
from datetime import datetime

# Generates a string like "01_Oct" (Day_Month)
current_timestamp = datetime.now().strftime("%Y-%m-%d_%I%p").lower()

# Sets the default name to "data/output_videos_01_Oct.json"
OUTPUT_FILE = f"data/output_videos_{current_timestamp}.json"
SEEN_FILE = os.getenv("SEEN_FILE", "data/seen_ids.txt")
