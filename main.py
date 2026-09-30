import os
import json
import asyncio
import logging
from config.settings import TARGET_COUNT, INGEST_TO_DB, OUTPUT_FILE
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
        logger.info("Database ingestion is ENABLED. Connecting to Neon DB...")
        db = Database()
        try:
            await db.connect()
        except Exception as e:
            logger.error(f"Cannot proceed with DB ingestion: {e}")
            return
    else:
        logger.info("🛡️ DRY-RUN MODE: Database ingestion is DISABLED. Results will be saved locally only.")

    # 1. Initialize crawler with local/DB dedupe
    seen_store = SeenStore(db=db)
    crawler = YouTubeVideoCrawler(seen_store=seen_store)

    # 2. Crawl and filter AI videos
    records = await crawler.fetch_ai_videos(target_count=TARGET_COUNT)
    
    if not records:
        logger.info("No new AI videos found matching the criteria.")
        if db:
            await db.close()
        return

    # 3. Always save local JSON copy for inspection
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    records_dict = [r.model_dump() for r in records]
    
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(records_dict, f, indent=2, ensure_ascii=False)
        
    logger.info(f"✅ Local copy saved successfully to: {OUTPUT_FILE}")
    logger.info(f"Total records extracted: {len(records)}")

    # 4. Ingest into Neon DB only if explicitly enabled
    if INGEST_TO_DB and db:
        logger.info("Ingesting records into Neon DB...")
        upserted = await db.upsert_records(records)
        logger.info(f"🚀 Ingested {upserted} records into Neon DB.")
        await db.close()
    else:
        logger.info("Inspect 'data/output_videos.json' to review data before pushing to Neon DB.")

if __name__ == "__main__":
    asyncio.run(main())