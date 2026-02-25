from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
import logging
import os

from fastapi.staticfiles import StaticFiles
import mediapipe as mp

from meme_manager import get_meme_template

logger = logging.getLogger(__name__)

mp_face_detection = mp.solutions.face_detection
mp_drawing = mp.solutions.drawing_utils
import cv2



from PIL import Image
from rembg import remove


app = FastAPI()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

ALLOWED_ORIGINS = [
    origin.strip() 
    for origin in os.environ.get(
        "ALLOWED_ORIGINS", 
        "http://localhost:5173,http://localhost:5174,http://localhost:8080"
    ).split(",")
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)




TARGET_SIZE = 512
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}



def _validate_file_extension(filename: str):
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")


def load_face_detection_model():
    face_detection = mp_face_detection.FaceDetection(model_selection=1, min_detection_confidence=0.2)
    return face_detection


def detect_faces(image_path, face_detection):
    logger.info(f"Processing image: {image_path}")
    image = cv2.imread(image_path, cv2.IMREAD_UNCHANGED)
    if image is None or image.size == 0:
        logger.warning("Failed to load image or image is empty")
        return None, None
    logger.debug(f"Image shape: {image.shape}")

    # Convert to 3-channel BGR for MediaPipe (which rejects 4-channel input)
    if image.shape[2] == 4:
        image_bgr = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    else:
        image_bgr = image

    results = face_detection.process(cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB))
    return image, results


def crop_center(image, detection, img_width, img_height):
    bboxC = detection.location_data.relative_bounding_box
    x_min = int(bboxC.xmin * img_width)
    y_min = int(bboxC.ymin * img_height)
    width = int(bboxC.width * img_width)
    height = int(bboxC.height * img_height)


    # add some padding to the bounding box
    padding = 40
    x_min = max(0, x_min - padding)
    y_min = max(0, y_min - padding)
    width = min(width + 2 * padding, img_width - x_min)
    height = min(height + 2 * padding, img_height - y_min)
    
    cropped_image = image[y_min:y_min + height, x_min:x_min + width]
    return cropped_image

face_detection = load_face_detection_model()

@app.get("/")
def read_root():
    return {"Hello": "World"}

@app.post("/upload")
async def upload_image(file: UploadFile = File(...)):
    _validate_file_extension(file.filename)

    input_ = Image.open(file.file)
    output = remove(input_)

    output_path = os.path.join(UPLOAD_DIR, f"output_{file.filename}")
    output.save(output_path)

    if not os.path.exists(output_path):
        raise HTTPException(status_code=500, detail="Failed to save the processed image.")

    try:
        annotated_image, results = detect_faces(output_path, face_detection)
    except Exception as e:
        logger.exception("Face detection failed")
        raise HTTPException(status_code=500, detail="Face detection failed.")

    print("results:", results)
    
    
    
    if results and results.detections:
        detection = results.detections[0]
        
        
        # multiple faces detected, use the larfest one (most likely the main subject)
        for det in results.detections[1:]:
            print("results.detections:", results.detections)
            if det.score[0] > detection.score[0]:
                print(f"Found a better detection with confidence {det.score[0]:.2f} > {detection.score[0]:.2f}")
                detection = det
        
        
        img_width, img_height = annotated_image.shape[1], annotated_image.shape[0]
        cropped_image = crop_center(annotated_image, detection, img_width, img_height)

        cropped_path = os.path.join(UPLOAD_DIR, f"cropped_{file.filename}")
        cv2.imwrite(cropped_path, cropped_image)
        logger.info(f"Cropped face saved: {cropped_path}")
    else:
        logger.info("No faces detected.")

    return {"filename": file.filename}


@app.post("/create-sticker")
def create_sticker(request: Request, file: UploadFile = File(...), template_id: str = Form(None)):
    _validate_file_extension(file.filename)

    try:
        selected_template, image_path = get_meme_template(template_id)
        logger.info(f"Processing meme: {selected_template['name']}")
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Read the uploaded file and remove background
    input_ = Image.open(file.file)
    output_rgba = remove(input_)

    base_filename = os.path.splitext(file.filename)[0]
    temp_path = os.path.join(UPLOAD_DIR, f"temp_{base_filename}.png")
    final_face_path = os.path.join(UPLOAD_DIR, f"cropped_{base_filename}.png")

    try:
        output_rgba.save(temp_path, format="PNG")

        annotated_image, results = detect_faces(temp_path, face_detection)
        
        print("results:", results)
    
    
    
        if results and results.detections:
            detection = results.detections[0]
            
            
            # multiple faces detected, use the larfest one (most likely the main subject)
            for det in results.detections[1:]:
                print("results.detections:", results.detections)
                if det.score[0] > detection.score[0]:
                    print(f"Found a better detection with confidence {det.score[0]:.2f} > {detection.score[0]:.2f}")
                    detection = det
                else:
                    print(f"Keeping current detection with confidence {detection.score[0]:.2f} over {det.score[0]:.2f}")
        

        if not results or not results.detections:
            raise HTTPException(status_code=422, detail="No face detected in uploaded image.")

        detection = results.detections[0]
        img_width, img_height = annotated_image.shape[1], annotated_image.shape[0]
        cropped_face = crop_center(annotated_image, detection, img_width, img_height)

        cv2.imwrite(final_face_path, cropped_face)

        meme_bg = Image.open(image_path).convert("RGBA")
        user_face = Image.open(final_face_path).convert("RGBA")

        # Get the target dimensions from template
        target_width = selected_template['face_slot']['width']
        target_height = selected_template['face_slot']['height']
        paste_x = selected_template['face_slot']['x']
        paste_y = selected_template['face_slot']['y']
        rotation_angle = selected_template['face_slot'].get('rotation', 0)

        # Resize the user's face
        user_face = user_face.resize((target_width, target_height), Image.Resampling.LANCZOS)

        # Rotate the user's face if the meme requires a head tilt
        if rotation_angle != 0:
            user_face = user_face.rotate(rotation_angle, expand=True, resample=Image.Resampling.BICUBIC)
            offset_x = (user_face.width - target_width) // 2
            offset_y = (user_face.height - target_height) // 2
            paste_x -= offset_x
            paste_y -= offset_y

        # Paste face onto meme using alpha channel as mask
        meme_bg.paste(user_face, (paste_x, paste_y), user_face)

        # Fit into WhatsApp sticker dimensions (512x512)
        meme_bg.thumbnail((TARGET_SIZE, TARGET_SIZE), Image.Resampling.LANCZOS)
        whatsapp_sticker = Image.new("RGBA", (TARGET_SIZE, TARGET_SIZE), (255, 255, 255, 0))

        center_x = (TARGET_SIZE - meme_bg.width) // 2
        center_y = (TARGET_SIZE - meme_bg.height) // 2
        whatsapp_sticker.paste(meme_bg, (center_x, center_y))

        # Save as optimized WebP
        final_sticker_name = f"sticker_{base_filename}.webp"
        final_sticker_path = os.path.join(UPLOAD_DIR, final_sticker_name)
        whatsapp_sticker.save(final_sticker_path, format="WEBP", quality=80, method=6)

        # Build URL from request instead of hardcoding
        base_url = str(request.base_url).rstrip("/")
        image_url = f"{base_url}/uploads/{final_sticker_name}"

        return {
            "status": "Success! WhatsApp Sticker Ready.",
            "meme_selected": selected_template['name'],
            "final_meme_url": image_url
        }

    finally:
        # Clean up temporary files
        for path in (temp_path, final_face_path):
            if os.path.exists(path):
                os.remove(path)
    