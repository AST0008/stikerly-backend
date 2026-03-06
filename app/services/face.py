import logging
from typing import Optional

import cv2
import mediapipe as mp
import numpy as np
from PIL import Image, ImageFilter

from app.models.template import FaceSlot

logger = logging.getLogger(__name__)

mp_face_detection = mp.solutions.face_detection


def load_face_detection_model():
    return mp_face_detection.FaceDetection(model_selection=1, min_detection_confidence=0.2)


def detect_faces(image_path: str, face_detection):
    logger.info(f"Detecting faces in: {image_path}")
    image = cv2.imread(image_path, cv2.IMREAD_UNCHANGED)
    if image is None or image.size == 0:
        logger.warning("Failed to load image or image is empty.")
        return None, None

    image_bgr = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR) if image.shape[2] == 4 else image
    results = face_detection.process(cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB))
    return image, results


def crop_center(image, detection, img_width: int, img_height: int):
    bb = detection.location_data.relative_bounding_box
    x = int(bb.xmin * img_width)
    y = int(bb.ymin * img_height)
    w = int(bb.width * img_width)
    h = int(bb.height * img_height)

    padding = 40
    x = max(0, x - padding)
    y = max(0, y - padding)
    w = min(w + 2 * padding, img_width - x)
    h = min(h + 2 * padding, img_height - y)

    return image[y : y + h, x : x + w]


def add_edge_blur(image: Image.Image, feather_width: int = 12) -> Image.Image:
    image = image.convert("RGBA")
    r, g, b, a = image.split()
    a_feathered = a.filter(ImageFilter.GaussianBlur(feather_width))
    image.putalpha(a_feathered)
    return image


def detect_face_slot_from_path(image_path: str) -> Optional[FaceSlot]:
    image = cv2.imread(image_path)
    if image is None:
        return None

    img_h, img_w = image.shape[:2]
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    with mp_face_detection.FaceDetection(model_selection=1, min_detection_confidence=0.3) as detector:
        results = detector.process(rgb)

    if not results.detections:
        return None

    detection = max(results.detections, key=lambda d: d.score[0])
    bb = detection.location_data.relative_bounding_box

    return FaceSlot(
        x=max(0, int(bb.xmin * img_w)),
        y=max(0, int(bb.ymin * img_h)),
        width=int(bb.width * img_w),
        height=int(bb.height * img_h),
        rotation=0,
    )
