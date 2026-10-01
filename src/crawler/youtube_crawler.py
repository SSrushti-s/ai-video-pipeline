import os
import json
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
import aiohttp
import yt_dlp

from config.settings import FRESHNESS
from src.schemas.video_model import YouTubeVideoRecord, AuthorData
from config.channels import AI_CHANNELS_POOL
from src.classifiers.tool_classifier import classify_tool_category, extract_tool_name
from src.utils.dedupe import SeenStore

logger = logging.getLogger("graphone.youtube_crawler")

MIXED_CONTENT_CHANNELS = {
    "freeCodeCamp.org", "Tech With Tim", "codebasics", "Corey Schafer",
    "MIT OpenCourseWare", "Lex Fridman", "The Verge", "Simplilearn", "Edureka"
}

class YouTubeVideoCrawler:
    def __init__(self, seen_store: SeenStore | None = None):
        self.seen_store = seen_store or SeenStore()
        self.avatar_cache_file = "data/channel_avatars.json"
        self._avatar_cache = self._load_avatar_cache()

    def _load_avatar_cache(self) -> dict[str, str]:
        """Loads cached channel avatars from disk to avoid redundant network calls."""
        if os.path.exists(self.avatar_cache_file):
            try:
                with open(self.avatar_cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_avatar_cache(self):
        """Persists discovered channel avatars to disk."""
        try:
            os.makedirs(os.path.dirname(self.avatar_cache_file), exist_ok=True)
            with open(self.avatar_cache_file, "w", encoding="utf-8") as f:
                json.dump(self._avatar_cache, f, indent=2)
        except Exception as e:
            logger.debug(f"Failed to persist avatar cache: {e}")

    async def _get_channel_avatar(self, session: aiohttp.ClientSession, channel: dict) -> str:
        """
        Retrieves the channel avatar via:
        1. Explicit "avatar" key in youtube_channels.py (if provided)
        2. Local disk cache (data/channel_avatars.json)
        3. YouTube channel page og:image metadata (auto-fetched once)
        4. Safe fallback identicon
        """
        channel_name = channel.get("name", "AI")
        channel_id = channel.get("channel_id")

        # 1. Check if manually provided in youtube_channels.py
        if channel.get("avatar"):
            return channel["avatar"]

        # 2. Check local disk cache
        if channel_id and channel_id in self._avatar_cache:
            return self._avatar_cache[channel_id]

        # 3. Auto-fetch official YouTube channel avatar from og:image
        if channel_id:
            url = f"https://www.youtube.com/channel/{channel_id}"
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            try:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    if resp.status == 200:
                        html = await resp.text()
                        m = re.search(r'<meta property="og:image" content="([^"]+)"', html)
                        if m and "yt3" in m.group(1):
                            avatar_url = m.group(1)
                            self._avatar_cache[channel_id] = avatar_url
                            self._save_avatar_cache()
                            return avatar_url
            except Exception as e:
                logger.debug(f"Could not auto-fetch avatar for {channel_name}: {e}")

        # 4. Fallback if network blocked
        return f"https://api.dicebear.com/7.x/identicon/svg?seed={channel_name}"

    def _generate_slug(self, title: str, video_id: str) -> str:
        clean = re.sub(r'[^a-zA-Z0-9\s-]', '', title).lower()
        clean = re.sub(r'[\s-]+', '-', clean).strip('-')
        return f"{clean[:30]}-{video_id[:6]}"

    async def _fetch_channel_rss(self, session: aiohttp.ClientSession, channel: dict) -> list[dict]:
        channel_id = channel.get("channel_id")
        if not channel_id:
            return []
        
        rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        try:
            async with session.get(rss_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return []
                xml_data = await resp.text()
                
            root = ET.fromstring(xml_data)
            ns = {
                'atom': 'http://www.w3.org/2005/Atom',
                'yt': 'http://www.youtube.com/xml/schemas/2015',
                'media': 'http://search.yahoo.com/mrss/'
            }
            
            videos = []
            for entry in root.findall('atom:entry', ns):
                vid = entry.find('yt:videoId', ns)
                title = entry.find('atom:title', ns)
                published = entry.find('atom:published', ns)
                media_group = entry.find('media:group', ns)
                desc = media_group.find('media:description', ns) if media_group is not None else None
                
                if vid is not None and title is not None:
                    videos.append({
                        "video_id": vid.text,
                        "title": title.text,
                        "published_at": published.text if published is not None else None,
                        "description": desc.text if desc is not None else "",
                        "channel_name": channel["name"],
                        "channel_id": channel_id
                    })
            return videos
        except Exception:
            return []

    def _is_ai_relevant(self, title: str, description: str, channel_name: str) -> bool:
        tool_category = classify_tool_category(title, description)
        tool_name = extract_tool_name(title, description)
        
        if tool_category != "general-ai" or tool_name != "General AI Tools":
            return True
            
        if channel_name not in MIXED_CONTENT_CHANNELS:
            return True
            
        ai_keywords = ["ai", "artificial intelligence", "llm", "gpt", "agent", "neural", "machine learning"]
        text = f"{title} {description}".lower()
        return any(re.search(rf"\b{re.escape(k)}\b", text) for k in ai_keywords)

    async def fetch_ai_videos(self, target_count: int = 50) -> list[YouTubeVideoRecord]:
        logger.info("Scanning YouTube RSS feeds for new AI videos...")
        records = []
        
        full_opts = {
            'quiet': True,
            'skip_download': True,
            'js_runtimes': {'node': {}},
            'extractor_args': {'youtube': {'player_client': ['android', 'web']}},
        }

        async with aiohttp.ClientSession() as session:
            for channel in AI_CHANNELS_POOL:
                if len(records) >= target_count:
                    break

                channel_videos = await self._fetch_channel_rss(session, channel)
                
                for item in channel_videos:
                    if len(records) >= target_count:
                        break

                    vid = item["video_id"]
                    
                    # 1. Deduplication check
                    if await self.seen_store.is_seen(vid, session):
                        continue

                    # 2. AI validation
                    if not self._is_ai_relevant(item["title"], item["description"], channel["name"]):
                        continue

                    # 3. Check video freshness
                    try:
                        pub_dt = datetime.fromisoformat(item["published_at"].replace("Z", "+00:00"))
                    except Exception:
                        pub_dt = datetime.now(timezone.utc)

                    age_hours = (datetime.now(timezone.utc) - pub_dt).total_seconds() / 3600
                    if age_hours > FRESHNESS.max_age_hours:
                        await self.seen_store.mark_seen(vid, session)
                        continue

                    # 4. Resolve author avatar (auto-fetched or cached)
                    avatar_url = await self._get_channel_avatar(session, channel)

                    # 5. Extract rich metadata using yt-dlp only for this new AI video
                    view_count, like_count, duration = 0, 0, 0
                    thumbnail_url = f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"

                    try:
                        with yt_dlp.YoutubeDL(full_opts) as ydl:
                            info = ydl.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
                            duration = int(info.get('duration', 0) or 0)
                            view_count = int(info.get('view_count', 0) or 0)
                            like_count = int(info.get('like_count', 0) or 0)
                            
                            thumbnails = info.get('thumbnails', [])
                            if thumbnails:
                                thumbnail_url = thumbnails[-1].get('url', thumbnail_url)
                    except Exception as e:
                        logger.warning(f"Could not extract yt-dlp metadata for {vid}, using defaults: {e}")

                    # Skip shorts or clips under 2 minutes
                    if duration > 0 and duration < 120:
                        await self.seen_store.mark_seen(vid, session)
                        continue

                    category = classify_tool_category(item["title"], item["description"])
                    tool = extract_tool_name(item["title"], item["description"])

                    record = YouTubeVideoRecord(
                        id=vid,
                        slug=self._generate_slug(item["title"], vid),
                        title=item["title"],
                        description=item["description"],
                        toolName=tool,
                        toolCategory=category,
                        youtubeId=vid,
                        thumbnail=thumbnail_url,
                        durationSeconds=duration,
                        views=view_count,
                        likes=like_count,
                        publishedAt=pub_dt.strftime("%Y-%m-%d"),
                        author=AuthorData(name=channel["name"], avatar=avatar_url),
                        channelId=item["channel_id"],
                        tags=[category],
                        accent="#4a4b50"
                    )

                    records.append(record)
                    await self.seen_store.mark_seen(vid, session)
                    logger.info(f"Found new AI video: {record.title} ({vid})")

        return records
