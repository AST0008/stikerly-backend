import logging
import time
from pathlib import Path

from app.config import UPLOAD_DIR

logger = logging.getLogger(__name__)

MAX_AGE_HOURS = 24


def cleanup():
    try:
        logger.info("Running cleanup job...")
        now = time.time()
        upload_path = Path(UPLOAD_DIR)

        for file in upload_path.iterdir():
            if file.is_file() and file.suffix in {".png", ".jpg", ".jpeg", ".webp"}:
                file_age = (now - file.stat().st_mtime) / 3600
                if file_age > MAX_AGE_HOURS:
                    file.unlink()
                    logger.info(f"Deleted old file: {file.name} (age: {file_age:.1f}h)")

        logger.info("Cleanup job completed.")
    except Exception:
        logger.exception("Cleanup job failed.")
