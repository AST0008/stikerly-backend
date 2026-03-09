"""
meme_fetcher.py
---------------
Automatically pulls trending meme images from:
  - Reddit  (public JSON API, no auth required)
  - GIPHY   (requires a GIPHY_API_KEY env var)

Fetched images are downloaded to TEMPLATE_DIR, auto-analysed for a face
slot via MediaPipe, then upserted into MongoDB so they appear as normal
templates in the rest of the app.
"""

import hashlib
import logging
import os
from typing import Optional

import requests
from PIL import Image as PILImage

from app.config import ALLOWED_EXTENSIONS, TEMPLATE_DIR
from app.database import templates_collection
from app.services.face import detect_face_slot_from_path

logger = logging.getLogger(__name__)

# Reddit's API requires a descriptive User-Agent to avoid 429 errors.
_REDDIT_HEADERS = {"User-Agent": "stikerly-meme-fetcher/1.0 (by /u/stikerly_bot)"}

# Subreddits used when no override is supplied.
DEFAULT_SUBREDDITS = ["MemeEconomy", "memes", "dankmemes"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _url_hash(url: str) -> str:
    """Short deterministic ID derived from a URL."""
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def _already_saved(url: str) -> bool:
    return templates_collection.find_one({"source_url": url}, {"_id": 0}) is not None


def _download(url: str, dest_path: str) -> bool:
    """Download *url* to *dest_path*. Returns True on success."""
    try:
        resp = requests.get(url, headers=_REDDIT_HEADERS, timeout=20, stream=True)
        resp.raise_for_status()
        with open(dest_path, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=65536):
                fh.write(chunk)
        return True
    except Exception as exc:
        logger.error("Download failed [%s]: %s", url, exc)
        if os.path.exists(dest_path):
            os.remove(dest_path)
        return False


def _gif_to_png(gif_path: str, png_path: str) -> bool:
    """Extract first frame of a GIF and save as PNG. Returns True on success."""
    try:
        with PILImage.open(gif_path) as img:
            img.seek(0)
            img.convert("RGBA").save(png_path, "PNG")
        os.remove(gif_path)
        return True
    except Exception as exc:
        logger.error("GIF→PNG conversion failed [%s]: %s", gif_path, exc)
        for p in (gif_path, png_path):
            if os.path.exists(p):
                os.remove(p)
        return False


# ---------------------------------------------------------------------------
# Core: download + ingest one meme dict
# ---------------------------------------------------------------------------

def _ingest_meme(meme: dict) -> Optional[dict]:
    """
    Download the image, detect faces, upsert into DB.

    *meme* must have keys:
        url   – direct URL to the image
        ext   – file extension incl. dot (e.g. ".jpg")
        title – human-readable name (truncated to 80 chars)
        tags  – list[str]

    Optional keys: subreddit, score, reddit_id
    """
    url = meme["url"]

    if _already_saved(url):
        logger.debug("Skipping duplicate: %s", url)
        return None

    h = _url_hash(url)
    ext = meme.get("ext", ".jpg").lower()

    # We only store static image formats; GIFs get converted later.
    if ext not in ALLOWED_EXTENSIONS and ext != ".gif":
        logger.warning("Unsupported extension %s for %s, skipping.", ext, url)
        return None

    filename = f"meme_{h}{ext}"
    dest_path = os.path.join(TEMPLATE_DIR, filename)

    if not _download(url, dest_path):
        return None

    # Convert animated GIF → PNG (first frame)
    if ext == ".gif":
        png_filename = f"meme_{h}.png"
        png_path = os.path.join(TEMPLATE_DIR, png_filename)
        if not _gif_to_png(dest_path, png_path):
            return None
        filename = png_filename
        dest_path = png_path

    # Auto-detect face slot
    try:
        face_slot = detect_face_slot_from_path(dest_path)
    except Exception as exc:
        logger.warning("Face detection failed for %s: %s", filename, exc)
        face_slot = None

    template_id = f"meme_{h}"
    doc = {
        "id": template_id,
        "name": meme.get("title", template_id)[:80],
        "filename": filename,
        "tags": list(set(meme.get("tags", []))),
        "face_slot": face_slot.model_dump() if face_slot else None,
        "source": meme.get("source", "unknown"),
        "source_url": url,
        "auto_fetched": True,
    }
    templates_collection.update_one({"id": template_id}, {"$set": doc}, upsert=True)
    logger.info("Ingested meme template: %s", template_id)
    return doc


# ---------------------------------------------------------------------------
# Reddit
# ---------------------------------------------------------------------------

def _reddit_fetch_raw(subreddit: str, limit: int, timeframe: str) -> list[dict]:
    """
    Hit the public Reddit JSON endpoint and return a list of normalised meme
    dicts ready for `_ingest_meme`.
    """
    api_url = (
        f"https://www.reddit.com/r/{subreddit}/top.json"
        f"?limit={min(limit, 100)}&t={timeframe}"
    )
    try:
        resp = requests.get(api_url, headers=_REDDIT_HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception as exc:
        logger.error("Reddit API error for r/%s: %s", subreddit, exc)
        return []

    memes: list[dict] = []
    for post in resp.json()["data"]["children"]:
        data = post["data"]

        # Skip NSFW / non-image posts
        if data.get("over_18") or data.get("is_video"):
            continue

        img_url: str = data.get("url", "")
        raw_ext = os.path.splitext(img_url.split("?")[0])[1].lower()

        if raw_ext in ALLOWED_EXTENSIONS:
            ext = raw_ext
        else:
            # Fall back to Reddit's preview image (always JPEG)
            preview_images = data.get("preview", {}).get("images", [])
            if preview_images:
                img_url = preview_images[0]["source"]["url"].replace("&amp;", "&")
                ext = ".jpg"
            else:
                continue  # no usable image

        # Build a tag list from subreddit + flair
        tags = ["reddit", "trending", subreddit.lower()]
        flair = (data.get("link_flair_text") or "").lower()
        if flair:
            tags.append(flair)

        memes.append(
            {
                "url": img_url,
                "ext": ext,
                "title": data.get("title", ""),
                "tags": tags,
                "source": f"r/{subreddit}",
                "reddit_id": data.get("id", ""),
                "score": data.get("score", 0),
            }
        )

    return memes


def run_reddit_fetch(
    subreddits: Optional[list[str]] = None,
    limit_per_subreddit: int = 10,
    timeframe: str = "day",
) -> dict:
    """
    Fetch trending posts from one or more subreddits and ingest them.

    Args:
        subreddits           – list of subreddit names (without r/).
                               Defaults to DEFAULT_SUBREDDITS.
        limit_per_subreddit  – how many posts to request per subreddit (max 100).
        timeframe            – Reddit time window: hour | day | week | month | year | all.

    Returns a summary dict with keys: saved, skipped, errors.
    """
    if not subreddits:
        subreddits = DEFAULT_SUBREDDITS

    saved = skipped = errors = 0

    for sub in subreddits:
        try:
            raw = _reddit_fetch_raw(sub, limit_per_subreddit, timeframe)
            for meme in raw:
                result = _ingest_meme(meme)
                if result:
                    saved += 1
                else:
                    skipped += 1
        except Exception as exc:
            logger.error("Unhandled error fetching r/%s: %s", sub, exc)
            errors += 1

    return {"saved": saved, "skipped": skipped, "errors": errors}


# ---------------------------------------------------------------------------
# GIPHY
# ---------------------------------------------------------------------------

def _giphy_fetch_raw(api_key: str, query: str, limit: int, rating: str) -> list[dict]:
    """Return normalised meme dicts from GIPHY."""
    if query:
        url = (
            f"https://api.giphy.com/v1/gifs/search"
            f"?api_key={api_key}&q={requests.utils.quote(query)}"
            f"&limit={limit}&rating={rating}"
        )
    else:
        url = (
            f"https://api.giphy.com/v1/gifs/trending"
            f"?api_key={api_key}&limit={limit}&rating={rating}"
        )

    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
    except Exception as exc:
        logger.error("GIPHY API error: %s", exc)
        return []

    memes: list[dict] = []
    for gif in resp.json().get("data", []):
        images = gif.get("images", {})
        # Prefer a static still so we don't have to convert every time.
        still_url = (
            images.get("original_still", {}).get("url")
            or images.get("downsized_still", {}).get("url")
            or images.get("fixed_height_still", {}).get("url")
        )
        if not still_url:
            # Fallback: use original GIF (will be converted to PNG).
            still_url = images.get("original", {}).get("url", "")
            ext = ".gif"
        else:
            ext = ".gif"  # GIPHY stills are actually GIFs (single frame)

        if not still_url:
            continue

        title = gif.get("title", "giphy")
        tags = ["giphy", "trending"] + [
            t.strip().lower() for t in title.split()[:4] if t.strip()
        ]

        memes.append(
            {
                "url": still_url,
                "ext": ext,
                "title": title,
                "tags": tags,
                "source": "giphy",
                "giphy_id": gif.get("id", ""),
            }
        )

    return memes


def run_giphy_fetch(
    api_key: str,
    query: str = "",
    limit: int = 10,
    rating: str = "g",
) -> dict:
    """
    Fetch trending (or searched) GIFs from GIPHY and ingest them as PNG templates.

    Args:
        api_key – your GIPHY API key (from env var GIPHY_API_KEY).
        query   – search term; leave blank for trending.
        limit   – number of GIFs to request.
        rating  – GIPHY content rating: g | pg | pg-13 | r.

    Returns a summary dict with keys: saved, skipped, errors.
    """
    saved = skipped = errors = 0

    try:
        raw = _giphy_fetch_raw(api_key, query, limit, rating)
        for meme in raw:
            result = _ingest_meme(meme)
            if result:
                saved += 1
            else:
                skipped += 1
    except Exception as exc:
        logger.error("Unhandled error fetching from GIPHY: %s", exc)
        errors += 1

    return {"saved": saved, "skipped": skipped, "errors": errors}
