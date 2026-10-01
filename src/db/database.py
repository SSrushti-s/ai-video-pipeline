import json
import logging
import asyncpg
from config.settings import DATABASE_URL
from src.schemas.video_model import YouTubeVideoRecord

logger = logging.getLogger("graphone.database")

class Database:
    def __init__(self):
        self.pool: asyncpg.Pool | None = None

    async def connect(self):
        if not DATABASE_URL:
            logger.warning("DATABASE_URL is not set. Database persistence disabled.")
            return

        # Strip query parameters that asyncpg handles via explicit kwargs
        clean_dsn = DATABASE_URL.split("?")[0]
        try:
            self.pool = await asyncpg.create_pool(
                dsn=clean_dsn,
                ssl="require",
                min_size=1,
                max_size=5
            )
            await self._init_table()
            logger.info("Connected to Neon DB successfully.")
        except Exception as e:
            logger.error(f"Failed to connect to Neon DB: {e}")
            raise

    async def _init_table(self):
        """Creates the videos table if it does not already exist."""
        query = """
        CREATE TABLE IF NOT EXISTS "YouTubeVideoRecord" (
            "id" TEXT PRIMARY KEY,
            "slug" TEXT NOT NULL,
            "title" TEXT NOT NULL,
            "description" TEXT,
            "toolName" TEXT NOT NULL,
            "toolCategory" TEXT NOT NULL,
            "youtubeId" TEXT UNIQUE NOT NULL,
            "thumbnail" TEXT NOT NULL,
            "durationSeconds" INTEGER NOT NULL,
            "views" INTEGER DEFAULT 0,
            "likes" INTEGER DEFAULT 0,
            "publishedAt" TEXT NOT NULL,
            "author" JSONB NOT NULL,
            "channelId" TEXT NOT NULL,
            "tags" JSONB NOT NULL,
            "accent" TEXT NOT NULL,
            "createdAt" TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            "updatedAt" TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
        """
        async with self.pool.acquire() as conn:
            await conn.execute(query)

    async def get_existing_video_ids(self, video_ids: list[str]) -> set[str]:
        """Check Neon DB for IDs that are already stored."""
        if not self.pool or not video_ids:
            return set()
        query = """
        SELECT "id" FROM "YouTubeVideoRecord"
        WHERE "id" = ANY($1::text[]);
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, video_ids)
            return {row["id"] for row in rows}

    async def upsert_records(self, records: list[YouTubeVideoRecord]) -> int:
        """Upsert records into Neon PostgreSQL."""
        if not self.pool or not records:
            return 0

        query = """
        INSERT INTO "YouTubeVideoRecord" (
            "id", "slug", "title", "description", "toolName", "toolCategory",
            "youtubeId", "thumbnail", "durationSeconds", "views", "likes",
            "publishedAt", "author", "channelId", "tags", "accent", "updatedAt"
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13::jsonb, $14, $15::jsonb, $16, NOW()
        )
       ON CONFLICT ("id") DO UPDATE SET
            "durationSeconds" = CASE 
                WHEN EXCLUDED."durationSeconds" > 0 THEN EXCLUDED."durationSeconds" 
                ELSE "YouTubeVideoRecord"."durationSeconds" 
            END,
            "views" = EXCLUDED."views",
            "likes" = EXCLUDED."likes",
            "thumbnail" = EXCLUDED."thumbnail",
            "updatedAt" = NOW();
        """

        upserted = 0
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                for r in records:
                    author_json = json.dumps(r.author.model_dump())
                    tags_json = json.dumps(r.tags)
                    await conn.execute(
                        query,
                        r.id, r.slug, r.title, r.description, r.toolName, r.toolCategory,
                        r.youtubeId, r.thumbnail, r.durationSeconds, r.views, r.likes,
                        r.publishedAt, author_json, r.channelId, tags_json, r.accent
                    )
                    upserted += 1

        logger.info(f"Successfully upserted {upserted} records into Neon DB.")
        return upserted

    async def close(self):
        if self.pool:
            await self.pool.close()
