# ingest.py
import json
import asyncio
import logging
from config.settings import OUTPUT_FILE
from src.schemas.video_model import YouTubeVideoRecord
from src.db.database import Database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("graphone.ingest")

async def push_local_to_neon():
    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
    except FileNotFoundError:
        logger.error(f"No file found at {OUTPUT_FILE}. Run main.py first.")
        return

    records = [YouTubeVideoRecord(**item) for item in raw_data]
    logger.info(f"Loaded {len(records)} validated records from {OUTPUT_FILE}.")

    db = Database()
    await db.connect()
    upserted = await db.upsert_records(records)
    await db.close()
    logger.info(f"🎉 Successfully pushed {upserted} records to Neon DB!")

if __name__ == "__main__":
    asyncio.run(push_local_to_neon())