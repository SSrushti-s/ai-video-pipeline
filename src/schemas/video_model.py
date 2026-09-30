from pydantic import BaseModel, Field, field_validator
from typing import List, Optional

class AuthorData(BaseModel):
    name: str
    avatar: str

class YouTubeVideoRecord(BaseModel):
    id: str
    slug: str
    title: str
    description: Optional[str] = None
    toolName: str 
    toolCategory: str 
    youtubeId: str
    thumbnail: str
    durationSeconds: int
    views: int = 0
    likes: int = 0
    publishedAt: str  # YYYY-MM-DD
    author: AuthorData
    channelId: str
    tags: List[str] = Field(default_factory=list)
    accent: str = "#4a4b50"

    @field_validator("toolCategory")
    @classmethod
    def validate_category(cls, v: str) -> str:
        valid = ["multimodal-ai", "robotics", "agents", "llm", "general-ai"]
        val_clean = v.lower().strip()
        if val_clean not in valid:
            return "general-ai"
        return val_clean