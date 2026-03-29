import logging
import os

from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

# Load .env before importing local modules that might rely on environment variables
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import TEMPLATE_DIR, UPLOAD_DIR
from app.routes.admin import router as admin_router, public_router as admin_public_router
from app.routes.sticker import router as sticker_router
from app.services.cleanup import cleanup
from app.services.meme_fetcher import run_reddit_fetch, run_giphy_fetch

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Stikerly API")

ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "ALLOWED_ORIGINS",
        "http://localhost:5173,http://localhost:5174,http://localhost:8080",
    ).split(",")
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
app.mount("/templates-static", StaticFiles(directory=TEMPLATE_DIR), name="templates-static")

app.include_router(sticker_router)
app.include_router(admin_public_router)
app.include_router(admin_router)

scheduler = BackgroundScheduler()


def _auto_fetch_reddit():
    """Scheduled job: refresh Reddit meme templates."""
    subreddits = [
        s.strip()
        for s in os.environ.get(
            "MEME_REDDIT_SUBREDDITS", "MemeEconomy,memes,dankmemes"
        ).split(",")
        if s.strip()
    ]
    limit = int(os.environ.get("MEME_REDDIT_LIMIT", "15"))
    timeframe = os.environ.get("MEME_REDDIT_TIMEFRAME", "day")
    result = run_reddit_fetch(subreddits=subreddits, limit_per_subreddit=limit, timeframe=timeframe)
    logger.info("Reddit auto-fetch complete: %s", result)


def _auto_fetch_giphy():
    """Scheduled job: refresh GIPHY meme templates (only if key is set)."""
    api_key = os.environ.get("GIPHY_API_KEY", "")
    if not api_key:
        return
    limit = int(os.environ.get("MEME_GIPHY_LIMIT", "10"))
    result = run_giphy_fetch(api_key=api_key, limit=limit)
    logger.info("GIPHY auto-fetch complete: %s", result)


@app.on_event("startup")
def startup_event():
    scheduler.add_job(cleanup, "cron", hour=2, minute=0)

    # Fetch memes every 12 hours (offset so they don't clash).
    scheduler.add_job(_auto_fetch_reddit, "interval", hours=12, id="reddit_fetch")
    scheduler.add_job(_auto_fetch_giphy, "interval", hours=12,
                      minutes=30, id="giphy_fetch")

    scheduler.start()
    logger.info("Scheduler started (cleanup + meme auto-fetch).")

    # Kick off an initial fetch in the background so templates are populated
    # immediately on first boot without waiting 12 hours.
    import threading
    threading.Thread(target=_auto_fetch_reddit, daemon=True).start()
    threading.Thread(target=_auto_fetch_giphy, daemon=True).start()


@app.on_event("shutdown")
def shutdown_event():
    scheduler.shutdown()
    logger.info("Scheduler shut down.")
