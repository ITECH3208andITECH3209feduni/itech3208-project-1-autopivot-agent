#!/usr/bin/env python3
"""
AutoPivot backend server.

Features:
- Server-side RMBG-2.0 background removal
- YOLOv8 vehicle detection
- YOLOS license plate detection
- Plate overlay / blank cover insertion

Run:
    python autopivot_backend.py

Optional ngrok exposure:
    python autopivot_backend.py --ngrok
"""

import io
import os
import base64
import logging
from typing import Optional

import numpy as np
import torch
from PIL import Image
from torchvision import transforms
from transformers import AutoModelForImageSegmentation, pipeline
from ultralytics import YOLO
import cv2
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Optional ngrok support
from pyngrok import ngrok, conf

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')
logger = logging.getLogger('autopivot-backend')

NGROK_TOKEN = os.environ.get('NGROK_TOKEN', '3DYYJVSDgP5GwING9QcQPn0pxoX_2oqL4skAe3zc3sogA5jxA')
conf.get_default().auth_token = NGROK_TOKEN

DEVICE = 'cuda' if torch.cuda.is_available() else 'cpu'
logger.info(f'Using device: {DEVICE}')

# Load RMBG-2.0 model for background removal
logger.info('Loading RMBG-2.0 model...')
rmbg_model = AutoModelForImageSegmentation.from_pretrained(
    'briaai/RMBG-2.0',
    trust_remote_code=True
).eval().to(DEVICE)

RMBG_IMAGE_SIZE = (1024, 1024)
transform_image = transforms.Compose([
    transforms.Resize(RMBG_IMAGE_SIZE),
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
])
logger.info('RMBG-2.0 loaded successfully.')

# Load YOLOS license plate detector
logger.info('Loading YOLOS plate detector...')
plate_detector = pipeline(
    'object-detection',
    model='nickmuchi/yolos-small-finetuned-license-plate-detection'
)
logger.info('YOLOS plate detector loaded successfully.')

# Load YOLO vehicle detector
logger.info('Loading YOLOv8 vehicle detector...')
vehicle_detector = YOLO('yolov8n.pt')
vehicle_detector.to(DEVICE)
logger.info('YOLO vehicle detector loaded successfully.')

VEHICLE_CLASSES = {
    'car', 'truck', 'bus', 'motorcycle', 'motorbike', 'bicycle', 'train', 'van'
}

app = FastAPI(
    title='AutoPivot Backend',
    description='RMBG-2.0 background removal + YOLO vehicle / plate detection + plate overlay',
    version='1.0.0'
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)


def pil_image_from_upload(upload: UploadFile) -> Image.Image:
    content = io.BytesIO(upload.file.read())
    image = Image.open(content)
    return image


def encode_image_to_base64(image: Image.Image) -> str:
    buffered = io.BytesIO()
    image.save(buffered, format='PNG')
    return base64.b64encode(buffered.getvalue()).decode('utf-8')


def parse_color(color: str):
    color = (color or 'white').strip().lower()
    if color.startswith('#'):
        color = color.lstrip('#')
        if len(color) == 3:
            color = ''.join([c*2 for c in color])
        if len(color) == 6:
            r, g, b = tuple(int(color[i:i+2], 16) for i in (0, 2, 4))
            return (r, g, b, 255)
    palette = {
        'white': (255, 255, 255, 255),
        'black': (0, 0, 0, 255),
        'gray': (192, 192, 192, 255),
        'grey': (192, 192, 192, 255),
        'silver': (220, 220, 220, 255),
        'red': (216, 56, 56, 255),
        'blue': (70, 130, 180, 255),
        'green': (76, 175, 80, 255)
    }
    return palette.get(color, (255, 255, 255, 255))


def remove_background_rmbg(image: Image.Image) -> Image.Image:
    rgb = image.convert('RGB')
    tensor = transform_image(rgb).unsqueeze(0).to(DEVICE)
    with torch.no_grad():
        preds = rmbg_model(tensor)[-1].sigmoid().cpu()
    mask = preds[0].squeeze(0)
    mask_img = transforms.ToPILImage()(mask.clamp(0, 1))
    mask_img = mask_img.resize(rgb.size, resample=Image.LANCZOS).convert('L')
    result = rgb.copy()
    result.putalpha(mask_img)
    return result


def detect_plates(image: Image.Image, score_threshold: float = 0.3):
    rgb = image.convert('RGB')
    detections = plate_detector(rgb)
    plates = []
    for det in detections:
        if det.get('score', 0) < score_threshold:
            continue
        label = det.get('label', '').lower()
        if not any(word in label for word in ['plate', 'license', 'licence', 'rego']):
            continue
        boxes = det.get('box') or {}
        plates.append({
            'label': det.get('label', 'license_plate'),
            'score': float(det.get('score', 0)),
            'box': {
                'xmin': int(boxes.get('xmin', 0)),
                'ymin': int(boxes.get('ymin', 0)),
                'xmax': int(boxes.get('xmax', 0)),
                'ymax': int(boxes.get('ymax', 0))
            }
        })
    return plates


def detect_vehicles(image: Image.Image, score_threshold: float = 0.3):
    rgb = image.convert('RGB')
    frame = np.array(rgb)
    results = vehicle_detector(frame, verbose=False)
    result = results[0]
    boxes = []
    if len(result.boxes):
        data = result.boxes.data.cpu().numpy()
        names = result.names
        for row in data:
            x1, y1, x2, y2, conf, cls_id = row
            label = names[int(cls_id)]
            if label not in VEHICLE_CLASSES:
                continue
            if float(conf) < score_threshold:
                continue
            boxes.append({
                'label': label,
                'score': float(conf),
                'box': {
                    'xmin': int(x1),
                    'ymin': int(y1),
                    'xmax': int(x2),
                    'ymax': int(y2)
                }
            })
    return boxes


@app.get('/')
async def root():
    return {
        'status': 'online',
        'models': {
            'bg': 'RMBG-2.0',
            'vehicle': 'YOLOv8',
            'plate': 'YOLOS'
        },
        'device': DEVICE
    }

@app.get('/health')
async def health():
    return {'status': 'ready', 'device': DEVICE}

@app.post('/remove-background')
async def remove_background(file: UploadFile = File(...)):
    try:
        logger.info(f'Removing background: {file.filename}')
        contents = await file.read()
        image = Image.open(io.BytesIO(contents))
        result = remove_background_rmbg(image)
        b64 = encode_image_to_base64(result)
        return {'success': True, 'processed_image': b64}
    except Exception as exc:
        logger.exception('Background removal failed')
        raise HTTPException(status_code=500, detail=str(exc))

@app.post('/detect-vehicles')
async def detect_vehicles_endpoint(file: UploadFile = File(...), min_score: float = Form(0.3)):
    try:
        logger.info(f'Vehicle detection: {file.filename}')
        contents = await file.read()
        image = Image.open(io.BytesIO(contents))
        vehicles = detect_vehicles(image, score_threshold=min_score)
        return {'success': True, 'vehicles_detected': len(vehicles), 'detections': vehicles}
    except Exception as exc:
        logger.exception('Vehicle detection failed')
        raise HTTPException(status_code=500, detail=str(exc))

@app.post('/detect-plates')
async def detect_plates_endpoint(file: UploadFile = File(...), min_score: float = Form(0.3)):
    try:
        logger.info(f'Plate detection: {file.filename}')
        contents = await file.read()
        image = Image.open(io.BytesIO(contents))
        plates = detect_plates(image, score_threshold=min_score)
        return {'success': True, 'plates_detected': len(plates), 'detections': plates}
    except Exception as exc:
        logger.exception('Plate detection failed')
        raise HTTPException(status_code=500, detail=str(exc))

@app.post('/overlay-plate')
async def overlay_plate(
    file: UploadFile = File(...),
    overlay: Optional[UploadFile] = File(None),
    overlay_color: str = Form('white'),
    min_score: float = Form(0.3)
):
    try:
        logger.info(f'Overlay plate request: {file.filename}')
        contents = await file.read()
        image = Image.open(io.BytesIO(contents))
        plates = detect_plates(image, score_threshold=min_score)
        if not plates:
            return {'success': False, 'message': 'No plates detected', 'plates_detected': 0}

        base = image.convert('RGBA')
        overlay_image = None
        if overlay is not None:
            overlay_bytes = await overlay.read()
            overlay_image = Image.open(io.BytesIO(overlay_bytes)).convert('RGBA')

        result = base.copy()
        cover_color = parse_color(overlay_color)

        for plate in plates:
            box = plate['box']
            x1 = max(0, box['xmin'])
            y1 = max(0, box['ymin'])
            x2 = min(base.width, box['xmax'])
            y2 = min(base.height, box['ymax'])
            width = max(1, x2 - x1)
            height = max(1, y2 - y1)

            if overlay_image is not None:
                cover = overlay_image.resize((width, height), Image.LANCZOS)
            else:
                cover = Image.new('RGBA', (width, height), cover_color)

            layer = Image.new('RGBA', result.size, (0, 0, 0, 0))
            layer.paste(cover, (x1, y1), cover)
            result = Image.alpha_composite(result, layer)

        b64 = encode_image_to_base64(result)
        return {
            'success': True,
            'plates_detected': len(plates),
            'processed_image': b64,
            'detections': plates
        }
    except Exception as exc:
        logger.exception('Plate overlay failed')
        raise HTTPException(status_code=500, detail=str(exc))


def start_ngrok(port: int = 8000) -> str:
    tunnel = ngrok.connect(port)
    logger.info(f'ngrok tunnel created: {tunnel.public_url}')
    return tunnel.public_url


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Run AutoPivot backend server')
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', default=8000, type=int)
    parser.add_argument('--ngrok', action='store_true', help='Start ngrok tunnel')
    args = parser.parse_args()

    if args.ngrok:
        public_url = start_ngrok(args.port)
        logger.info('Copy this URL into the frontend: BACKEND_URL=%s', public_url)

    uvicorn.run('autopivot_backend:app', host=args.host, port=args.port, log_level='info')
