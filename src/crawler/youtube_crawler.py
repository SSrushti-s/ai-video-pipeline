import os
import json
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
import aiohttp

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
        if os.path.exists(self.avatar_cache_file):
            try:
                with open(self.avatar_cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_avatar_cache(self):
        try:
            os.makedirs(os.path.dirname(self.avatar_cache_file), exist_ok=True)
            with open(self.avatar_cache_file, "w", encoding="utf-8") as f:
                json.dump(self._avatar_cache, f, indent=2)
        except Exception as e:
            logger.debug(f"Failed to persist avatar cache: {e}")

    async def _get_channel_avatar(self, session: aiohttp.ClientSession, channel: dict) -> str:
        channel_name = channel.get("name", "AI")
        channel_id = channel.get("channel_id")

        if channel.get("avatar"):
            return channel["avatar"]
        if channel_id and channel_id in self._avatar_cache:
            return self._avatar_cache[channel_id]

        if channel_id:
            url = f"https://www.youtube.com/channel/{channel_id}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Cookie": "SOCS=CAESEwgDEgk2MTQ1NzU4ODQaAmVuIAEaBgiA_LyaBg; CONSENT=YES+cb.20230531-04-p0.en+FX+999"
            }
            try:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=6)) as resp:
                    if resp.status == 200:
                        html = await resp.text()
                        m = re.search(r'<meta property="og:image" content="([^"]+)"', html)
                        if m and "yt3" in m.group(1):
                            avatar_url = m.group(1)
                            self._avatar_cache[channel_id] = avatar_url
                            self._save_avatar_cache()
                            return avatar_url
            except Exception:
                pass

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
                
                views = 0
                if media_group is not None:
                    comm = media_group.find('media:community', ns)
                    if comm is not None:
                        stats = comm.find('media:statistics', ns)
                        if stats is not None and stats.attrib.get('views'):
                            try:
                                views = int(stats.attrib['views'])
                            except ValueError:
                                views = 0

                if vid is not None and title is not None:
                    videos.append({
                        "video_id": vid.text,
                        "title": title.text,
                        "published_at": published.text if published is not None else None,
                        "description": desc.text if desc is not None else "",
                        "views": views,
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

    async def _fetch_accurate_video_metrics(self, session: aiohttp.ClientSession, vid: str, default_views: int) -> dict:
        """
        Extracts duration, views, and likes directly.
        Bypasses EU/Cloud datacenter consent walls via SOCS cookies + InnerTube fallback.
        """
        url = f"https://www.youtube.com/watch?v={vid}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            # Bypasses YouTube/Google Consent walls on Datacenter (Azure/GitHub) IPs
            "Cookie": "SOCS=CAESEwgDEgk2MTQ1NzU4ODQaAmVuIAEaBgiA_LyaBg; CONSENT=YES+cb.20230531-04-p0.en+FX+999"
        }
        duration = 0
        views = default_views
        likes = 0

        # Step 1: Watch page inspection with consent cookies
        try:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    html = await resp.text()

                    m_sec = re.search(r'"lengthSeconds":"(\d+)"', html)
                    if m_sec:
                        duration = int(m_sec.group(1))

                    m_views = re.search(r'"viewCount":"(\d+)"', html)
                    if m_views:
                        views = int(m_views.group(1))

                    m_likes = re.search(r'"likeCount":"?(\d+)"?', html)
                    if m_likes:
                        likes = int(m_likes.group(1))
        except Exception:
            pass

        # Step 2: InnerTube Player API fallback (Guaranteed clean JSON if HTML redirected)
        if duration == 0:
            try:
                it_url = "https://www.youtube.com/youtubei/v1/player?prettyPrint=false"
                payload = {
                    "context": {
                        "client": {
                            "clientName": "WEB",
                            "clientVersion": "2.20240313.01.00",
                            "hl": "en",
                            "gl": "US"
                        }
                    },
                    "videoId": vid
                }
                async with session.post(it_url, json=payload, headers={"User-Agent": headers["User-Agent"]}, timeout=aiohttp.ClientTimeout(total=6)) as resp:
                    if resp.status == 200:
                        res = await resp.json()
                        vd = res.get("videoDetails", {})
                        duration = int(vd.get("lengthSeconds", 0) or 0)
                        views = int(vd.get("viewCount", views) or views)
            except Exception:
                pass

        # Filter out Shorts (clips under 2 minutes)
        is_short = (0 < duration < 120)

        return {
            "duration": duration,
            "views": views,
            "likes": likes,
            "is_short": is_short
        }

    async def fetch_ai_videos(self, target_count: int = 50) -> list[YouTubeVideoRecord]:
        logger.info("Scanning YouTube RSS feeds for new AI videos...")
        records = []

        async with aiohttp.ClientSession() as session:
            for channel in AI_CHANNELS_POOL:
                if len(records) >= target_count:
                    break

                channel_videos = await self._fetch_channel_rss(session, channel)
                
                for item in channel_videos:
                    if len(records) >= target_count:
                        break

                    vid = item["video_id"]
                    
                    # 1. Deduplication check against Neon DB / local cache
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

                    # 4. Extract accurate metrics
                    metrics = await self._fetch_accurate_video_metrics(session, vid, item["views"])

                    # 5. Skip Shorts
                    if metrics["is_short"]:
                        await self.seen_store.mark_seen(vid, session)
                        continue

                    # 6. Resolve channel avatar
                    avatar_url = await self._get_channel_avatar(session, channel)

                    category = classify_tool_category(item["title"], item["description"])
                    tool = extract_tool_name(item["title"], item["description"])
                    thumbnail_url = f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"

                    record = YouTubeVideoRecord(
                        id=vid,
                        slug=self._generate_slug(item["title"], vid),
                        title=item["title"],
                        description=item["description"],
                        toolName=tool,
                        toolCategory=category,
                        youtubeId=vid,
                        thumbnail=thumbnail_url,
                        durationSeconds=metrics["duration"],
                        views=metrics["views"],
                        likes=metrics["likes"],
                        publishedAt=pub_dt.strftime("%Y-%m-%d"),
                        author=AuthorData(name=channel["name"], avatar=avatar_url),
                        channelId=item["channel_id"],
                        tags=[category],
                        accent="#4a4b50"
                    )

                    records.append(record)
                    await self.seen_store.mark_seen(vid, session)
                    logger.info(
                        f"✅ Found AI video: {record.title[:35]}... ({vid}) "
                        f"[duration={metrics['duration']}s, views={metrics['views']}, likes={metrics['likes']}]"
                    )

        return records
