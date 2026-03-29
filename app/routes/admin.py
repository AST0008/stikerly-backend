import os
import shutil
import logging
import cloudinary
import cloudinary.uploader

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile

from app.config import TEMPLATE_DIR, ALLOWED_EXTENSIONS
from app.database import templates_collection
from app.models.template import SaveTemplateRequest, RedditFetchRequest, GiphyFetchRequest
from app.services.face import detect_face_slot_from_path
from app.services.meme_fetcher import run_reddit_fetch, run_giphy_fetch

logger = logging.getLogger(__name__)

ADMIN_KEY = os.getenv("ADMIN_KEY", "changeme")


def require_admin(x_admin_key: str = Header(...)):
    if x_admin_key != ADMIN_KEY:
        raise HTTPException(status_code=401, detail="Invalid admin key.")


router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])

# Public read-only router — same /admin prefix, no auth required.
public_router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/templates/upload")
def upload_template_image(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")

    # dest_path = os.path.join(TEMPLATE_DIR, file.filename)
    
    file.file.seek(0)
    file_bytes = file.file.read()
    
    # using cloudinary 
    result = cloudinary.uploader.upload(file_bytes, folder="stikerly_templates")
    
    # with open(dest_path, "wb") as f:
    #     shutil.copyfileobj(file.file, f)

    print(f"Uploaded {file.filename} to Cloudinary: {result['secure_url']}")
    
    import cv2
    import numpy as np
    nparr = np.frombuffer(file_bytes, np.uint8)
    image_cv = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    
    from app.services.face import mp_face_detection
    face_slot = None
    if image_cv is not None:
        img_h, img_w = image_cv.shape[:2]
        rgb = cv2.cvtColor(image_cv, cv2.COLOR_BGR2RGB)
        with mp_face_detection.FaceDetection(model_selection=1, min_detection_confidence=0.3) as detector:
            results = detector.process(rgb)
        if results and results.detections:
            from app.models.template import FaceSlot
            detection = max(results.detections, key=lambda d: d.score[0])
            bb = detection.location_data.relative_bounding_box
            face_slot = FaceSlot(
                x=max(0, int(bb.xmin * img_w)),
                y=max(0, int(bb.ymin * img_h)),
                width=int(bb.width * img_w),
                height=int(bb.height * img_h),
                rotation=0,
            )
            
    return {
        "filename": file.filename,
        "image_url": result["secure_url"],
        "face_slot": face_slot,
        "face_detected": face_slot is not None,
    }


@router.post("/templates")
def save_template(body: SaveTemplateRequest):
    doc = {
        "id": body.id,
        "name": body.name,
        "filename": body.filename,  # the frontend still sends filename, but maybe we should store image_url?
        "tags": body.tags,
        "face_slot": body.face_slot.model_dump(),
    }
    templates_collection.update_one({"id": body.id}, {"$set": doc}, upsert=True)

    return {"status": "saved", "template_id": body.id}


@public_router.get("/templates", summary="List all meme templates")
def list_templates():
    return list(templates_collection.find({}, {"_id": 0}))


@router.delete("/templates/{template_id}")
def delete_template(template_id: str, delete_file: bool = False):
    doc = templates_collection.find_one({"id": template_id})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Template not found: {template_id}")

    templates_collection.delete_one({"id": template_id})

    if delete_file:
        pass # To properly delete from Cloudinary we'd need the public_id
        # file_path = os.path.join(TEMPLATE_DIR, doc["filename"])
        # if os.path.exists(file_path):
        #     os.remove(file_path)

    return {"status": "deleted", "template_id": template_id}


# ---------------------------------------------------------------------------
# Meme feed endpoints
# ---------------------------------------------------------------------------

@router.post("/memes/fetch/reddit", summary="Fetch trending memes from Reddit")
def fetch_reddit(body: RedditFetchRequest):
    """
    Pull top posts from one or more subreddits, download the images,
    auto-detect face slots, and store them as templates.

    - **subreddits**: list of subreddit names, e.g. `["memes", "MemeEconomy"]`
    - **limit_per_subreddit**: posts to fetch per subreddit (1-100)
    - **timeframe**: `hour | day | week | month | year | all`
    """
    result = run_reddit_fetch(
        subreddits=body.subreddits,
        limit_per_subreddit=body.limit_per_subreddit,
        timeframe=body.timeframe,
    )
    return {"status": "done", **result}


@router.post("/memes/fetch/giphy", summary="Fetch trending memes from GIPHY")
def fetch_giphy(body: GiphyFetchRequest):
    """
    Pull trending (or searched) GIFs from GIPHY, convert to PNG,
    auto-detect face slots, and store them as templates.

    Requires a GIPHY API key – pass it in the request body or set the
    `GIPHY_API_KEY` environment variable.
    """
    api_key = body.api_key or os.getenv("GIPHY_API_KEY", "")
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail=(
                "A GIPHY API key is required. Pass it in the request body "
                "or set the GIPHY_API_KEY environment variable."
            ),
        )
    result = run_giphy_fetch(
        api_key=api_key,
        query=body.query,
        limit=body.limit,
        rating=body.rating,
    )
    return {"status": "done", **result}
