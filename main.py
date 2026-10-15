# In main.py:
import os
import json
import asyncio
import logging
from config.settings import TARGET_COUNT, INGEST_TO_DB, OUTPUT_FILE, DATABASE_URL
from src.db.database import Database
from src.utils.dedupe import SeenStore
from src.crawler.youtube_crawler import YouTubeVideoCrawler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("graphone.main")

async def main():
    logger.info("Initializing YouTube AI Video Ingestion Pipeline...")
    
    db = None
    if INGEST_TO_DB:
        if not DATABASE_URL:
            raise ValueError("🚨 ERROR: INGEST_TO_DB is true, but DATABASE_URL is empty! Check your GitHub Secrets.")
        
        logger.info("Database ingestion is ENABLED. Connecting to Neon DB...")
        db = Database()
        await db.connect()
    else:
        logger.info("🛡️ DRY-RUN MODE: Database ingestion is DISABLED.")

    seen_store = SeenStore(db=db)
    crawler = YouTubeVideoCrawler(seen_store=seen_store)

    records = await crawler.fetch_ai_videos(target_count=TARGET_COUNT)
    
    if not records:
        logger.info("No new AI videos found.")
        if db:
            await db.close()
        return

    # Always persist local copy
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump([r.model_dump() for r in records], f, indent=2, ensure_ascii=False)
        
    logger.info(f"Saved {len(records)} records to {OUTPUT_FILE}")

    # Ingest to Neon DB
    if INGEST_TO_DB and db:
        logger.info(f"Upserting {len(records)} records into Neon DB...")
        upserted = await db.upsert_records(records)
        logger.info(f"🚀 SUCCESS: Upserted {upserted} records into Neon DB!")
        await db.close()

if __name__ == "__main__":
    asyncio.run(main())
