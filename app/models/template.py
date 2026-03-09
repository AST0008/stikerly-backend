from typing import List, Optional
from pydantic import BaseModel, Field


class FaceSlot(BaseModel):
    x: int
    y: int
    width: int
    height: int
    rotation: float = 0


class SaveTemplateRequest(BaseModel):
    id: str
    name: str
    filename: str
    tags: List[str]
    face_slot: FaceSlot


# ---------------------------------------------------------------------------
# Meme fetch request models
# ---------------------------------------------------------------------------

class RedditFetchRequest(BaseModel):
    subreddits: List[str] = Field(
        default=["MemeEconomy", "memes", "dankmemes"],
        description="Subreddit names to fetch from (without the r/ prefix).",
    )
    limit_per_subreddit: int = Field(
        default=10,
        ge=1,
        le=100,
        description="How many top posts to request per subreddit.",
    )
    timeframe: str = Field(
        default="day",
        pattern="^(hour|day|week|month|year|all)$",
        description="Reddit time window for 'top' posts.",
    )


class GiphyFetchRequest(BaseModel):
    api_key: Optional[str] = Field(
        default=None,
        description=(
            "GIPHY API key. Falls back to the GIPHY_API_KEY environment variable "
            "when omitted."
        ),
    )
    query: str = Field(
        default="",
        description="Search term. Leave blank to fetch trending GIFs.",
    )
    limit: int = Field(default=10, ge=1, le=50)
    rating: str = Field(
        default="g",
        pattern="^(g|pg|pg-13|r)$",
        description="GIPHY content rating filter.",
    )
