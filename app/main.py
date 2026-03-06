import logging
import os

from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import TEMPLATE_DIR, UPLOAD_DIR
from app.routes.admin import router as admin_router
from app.routes.sticker import router as sticker_router
from app.services.cleanup import cleanup

load_dotenv()

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
app.include_router(admin_router)

scheduler = BackgroundScheduler()


@app.on_event("startup")
def startup_event():
    scheduler.add_job(cleanup, "cron", hour=2, minute=0)
    scheduler.start()
    logger.info("Scheduler started.")


@app.on_event("shutdown")
def shutdown_event():
    scheduler.shutdown()
    logger.info("Scheduler shut down.")
