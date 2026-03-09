"""
Manual test script for the meme fetching feature.
Run from the project root:
    python scripts/test_meme_fetch.py
"""
import json
import logging
import os
import sys

# Suppress TF / mediapipe noise
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
logging.disable(logging.WARNING)

# Make sure the project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

# Re-enable logging for our own output after imports are done
logging.disable(logging.NOTSET)
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

from app.services.meme_fetcher import run_reddit_fetch, run_giphy_fetch
from app.database import templates_collection

SEP = "─" * 60


def print_summary(result: dict):
    print(json.dumps(result, indent=2))


def print_samples(limit: int = 8):
    docs = list(
        templates_collection.find(
            {"auto_fetched": True},
            {"_id": 0, "id": 1, "name": 1, "source": 1, "filename": 1, "face_slot": 1},
        ).sort([("_id", -1)]).limit(limit)
    )
    if not docs:
        print("  (none)")
        return
    for d in docs:
        face = "✓ face" if d.get("face_slot") else "  none"
        print(f"  [{face}]  [{d['source']:<18}]  {d['name'][:55]}")


def main():
    before = templates_collection.count_documents({"auto_fetched": True})
    print(f"\n{SEP}")
    print(f"  Auto-fetched templates before test: {before}")
    print(SEP)

    # ── Reddit ──────────────────────────────────────────────────────────────
    print("\n📥  Reddit  (r/memes + r/dankmemes — 3 posts each, timeframe=day)")
    print(SEP)
    result = run_reddit_fetch(
        subreddits=["memes", "dankmemes"],
        limit_per_subreddit=3,
        timeframe="day",
    )
    print_summary(result)

    # ── GIPHY ────────────────────────────────────────────────────────────────
    api_key = os.environ.get("GIPHY_API_KEY", "")
    if api_key:
        print("\n📥  GIPHY  (trending — 3 GIFs)")
        print(SEP)
        result = run_giphy_fetch(api_key=api_key, limit=3)
        print_summary(result)

        print("\n📥  GIPHY  (search: 'funny cat' — 3 GIFs)")
        print(SEP)
        result = run_giphy_fetch(api_key=api_key, query="funny cat", limit=3)
        print_summary(result)
    else:
        print("\n⚠️  GIPHY_API_KEY not set — skipping GIPHY tests.")

    # ── After ────────────────────────────────────────────────────────────────
    after = templates_collection.count_documents({"auto_fetched": True})
    print(f"\n{SEP}")
    print(f"  Auto-fetched templates after test : {after}  (+{after - before} new)")
    print(SEP)
    print("\n  Most recently saved:")
    print_samples(8)
    print()


if __name__ == "__main__":
    main()
