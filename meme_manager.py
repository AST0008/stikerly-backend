import json
import logging
import os
from random import choice

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DB = os.path.join(BASE_DIR, "assets", "templates.json")
TEMPLATE_DIR = os.path.join(BASE_DIR, "assets", "templates")


def get_meme_template(template_id: str = None):
    """
    Loads meme templates from JSON.
    If an ID is provided, returns that specific meme.
    If no ID, returns a random 'trending' meme.
    """
    with open(TEMPLATE_DB, 'r') as f:
        templates = json.load(f)

    selected_template = None

    if template_id:
        for t in templates:
            if t['id'] == template_id:
                selected_template = t
                break
    else:
        selected_template = choice(templates)

    if not selected_template:
        raise ValueError(f"Template not found: {template_id}")

    image_path = os.path.join(TEMPLATE_DIR, selected_template['filename'])
    if not os.path.isfile(image_path):
        raise FileNotFoundError(f"Template image missing: {selected_template['filename']}")

    return selected_template, image_path



                
    