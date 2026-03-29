import logging
import os
import io
import cloudinary
import cloudinary.uploader
import requests

import cv2
import numpy as np
from deepface import DeepFace
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from PIL import Image
from rembg import remove

from app.config import ALLOWED_EXTENSIONS, TARGET_SIZE, UPLOAD_DIR
from app.database import templates_collection
from app.services.face import add_edge_blur, crop_center, detect_faces, load_face_detection_model
from app.services.meme_manager import get_meme_template

logger = logging.getLogger(__name__)

router = APIRouter(tags=["sticker"])

face_detection_model = load_face_detection_model()


def _validate_extension(filename: str):
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")


@router.get("/")
def read_root():
    return {"status": "ok"}


@router.get("/templates", summary="List all available meme templates (public)")
def list_templates_public():
    """Returns all templates. No auth required — used by the frontend."""
    return list(templates_collection.find({}, {"_id": 0}))


@router.post("/create-sticker")
def create_sticker(
    request: Request,
    file: UploadFile = File(...),
    template_id: str = Form(None),
):
    _validate_extension(file.filename)

    image = Image.open(file.file).convert("RGB")
    image_array = np.array(image)
    objs = DeepFace.analyze(img_path=image_array, actions=["emotion"])
    dominant_emotion = objs[0]["dominant_emotion"]
    logger.info(f"Detected emotion: {dominant_emotion}")

    try:
        selected_template, template_image_path = get_meme_template(template_id, dominant_emotion)
        logger.info(f"Using template: {selected_template['name']}")
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))

    file.file.seek(0)
    input_image = Image.open(file.file)
    output_rgba = remove(input_image)

    base_filename = os.path.splitext(file.filename)[0]
    temp_path = os.path.join(UPLOAD_DIR, f"temp_{base_filename}.png")
    final_face_path = os.path.join(UPLOAD_DIR, f"cropped_{base_filename}.png")

    try:
        output_rgba.save(temp_path, format="PNG")
        annotated_image, results = detect_faces(temp_path, face_detection_model)

        if not results or not results.detections:
            raise HTTPException(status_code=422, detail="No face detected in uploaded image.")

        detection = max(results.detections, key=lambda d: d.score[0])

        img_h, img_w = annotated_image.shape[:2]
        cropped_face = crop_center(annotated_image, detection, img_w, img_h)

        if cropped_face.shape[2] == 4:
            cropped_face_rgb = cv2.cvtColor(cropped_face, cv2.COLOR_BGRA2RGBA)
        else:
            cropped_face_rgb = cv2.cvtColor(cropped_face, cv2.COLOR_BGR2RGB)

        blurred = add_edge_blur(Image.fromarray(cropped_face_rgb))
        blurred.save(final_face_path, format="PNG")

        if template_image_path.startswith("http://") or template_image_path.startswith("https://"):
            resp = requests.get(template_image_path)
            resp.raise_for_status()
            meme_bg_file = io.BytesIO(resp.content)
            meme_bg = Image.open(meme_bg_file).convert("RGBA")
        else:
            meme_bg = Image.open(template_image_path).convert("RGBA")
            
        user_face = Image.open(final_face_path).convert("RGBA")

        slot = selected_template["face_slot"]
        if not slot:
            raise HTTPException(status_code=400, detail="Selected template does not have a defined face slot.")
        target_w, target_h = slot["width"], slot["height"]
        paste_x, paste_y = slot["x"], slot["y"]
        rotation = slot.get("rotation", 0)

        user_face = user_face.resize((target_w, target_h), Image.Resampling.LANCZOS)

        if rotation != 0:
            user_face = user_face.rotate(rotation, expand=True, resample=Image.Resampling.BICUBIC)
            paste_x -= (user_face.width - target_w) // 2
            paste_y -= (user_face.height - target_h) // 2

        meme_bg.paste(user_face, (paste_x, paste_y), user_face)

        meme_bg.thumbnail((TARGET_SIZE, TARGET_SIZE), Image.Resampling.LANCZOS)
        sticker_bg = Image.new("RGBA", (TARGET_SIZE, TARGET_SIZE), (255, 255, 255, 0))
        cx = (TARGET_SIZE - meme_bg.width) // 2
        cy = (TARGET_SIZE - meme_bg.height) // 2
        sticker_bg.paste(meme_bg, (cx, cy))

        img_byte_arr = io.BytesIO()
        sticker_bg.save(img_byte_arr, format="WEBP", quality=80, method=6)
        img_byte_arr.seek(0)
        
        response = cloudinary.uploader.upload(
            img_byte_arr, 
            public_id=f"sticker_{base_filename}",
            folder="stickers",
            resource_type="image", 
            format="webp"
        )
        
        print("Cloudinary upload response:", response)
        
        final_meme_url = response["secure_url"]
        print(f"Final sticker URL: {final_meme_url}")

        base_url = str(request.base_url).rstrip("/")
        return {
            "status": "Success! WhatsApp Sticker Ready.",
            "meme_selected": selected_template["name"],
            "final_meme_url": final_meme_url,
        }

    finally:
        for path in (temp_path, final_face_path):
            if os.path.exists(path):
                os.remove(path)
