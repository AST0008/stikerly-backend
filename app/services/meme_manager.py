import logging
import os
from random import choice

from app.database import templates_collection
from app.config import TEMPLATE_DIR

logger = logging.getLogger(__name__)


def get_meme_template(template_id: str = None, dominant_emotion: str = None):
    selected_template = None

    if template_id:
        selected_template = templates_collection.find_one({"id": template_id}, {"_id": 0})
    elif dominant_emotion:
        selected_template = templates_collection.find_one({"tags": dominant_emotion, "face_slot": {"$ne": None}}, {"_id": 0})
        if not selected_template:
            logger.info(f"No template for emotion '{dominant_emotion}', falling back to random.")
            all_templates = list(templates_collection.find({"face_slot": {"$ne": None}}, {"_id": 0}))
            selected_template = choice(all_templates) if all_templates else None

    # Fallback if somehow template_id is not provided and emotion matching also returned nothing
    if not selected_template and not template_id:
        all_templates = list(templates_collection.find({"face_slot": {"$ne": None}}, {"_id": 0}))
        selected_template = choice(all_templates) if all_templates else None

    if not selected_template:
        raise ValueError(f"Template not found: {template_id}")

    filename = selected_template.get("filename", "")
    if filename.startswith("http://") or filename.startswith("https://"):
        return selected_template, filename

    image_path = os.path.join(TEMPLATE_DIR, filename)
    if not os.path.isfile(image_path):
        raise FileNotFoundError(f"Template image missing: {filename}")

    return selected_template, image_path
