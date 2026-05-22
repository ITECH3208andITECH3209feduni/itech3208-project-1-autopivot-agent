from huggingface_hub import login
from PIL import Image
import torch
from torchvision import transforms
from transformers import AutoModelForImageSegmentation, pipeline
from ultralytics import YOLO
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import io, base64, numpy as np, cv2, logging, uvicorn
import os

HF_TOKEN = os.getenv("HF_TOKEN")
PORT = 8000

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if HF_TOKEN:
    login(token=HF_TOKEN)

device = 'cuda' if torch.cuda.is_available() else 'cpu'


logger.info('Loading YOLO26 vehicle detector: yolo26n.pt')
vehicle_detector = YOLO('yolo26n.pt')


logger.info('Loading BiRefNet background removal model: ZhengPeng7/BiRefNet')
birefnet_model = AutoModelForImageSegmentation.from_pretrained(
    'ZhengPeng7/BiRefNet',
    trust_remote_code=True,
    torch_dtype=torch.float32
).eval().to(device).float()

image_size = (1024, 1024)
transform_image = transforms.Compose([
    transforms.Resize(image_size),
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
])

logger.info('Loading YOLOS plate detector: nickmuchi/yolos-small-finetuned-license-plate-detection')
plate_detector = pipeline(
    'object-detection',
    model='nickmuchi/yolos-small-finetuned-license-plate-detection'
)

app = FastAPI(title='AutoPivot - YOLO26 + BiRefNet + YOLOS')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)


def detect_vehicle_yolo26(image, conf_threshold=0.35):
    """Detect the largest vehicle in the uploaded image using YOLO26."""
    image_rgb = image.convert('RGB')

    results = vehicle_detector(image_rgb, conf=conf_threshold, verbose=False)

    # COCO vehicle classes commonly detected by YOLO models.
    vehicle_classes = {'car', 'truck', 'bus', 'motorcycle'}
    detected_vehicles = []

    for result in results:
        names = result.names
        for box in result.boxes:
            class_id = int(box.cls[0])
            class_name = names[class_id]
            confidence = float(box.conf[0])

            if class_name in vehicle_classes:
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                area = max(0, x2 - x1) * max(0, y2 - y1)
                detected_vehicles.append({
                    'class': class_name,
                    'score': confidence,
                    'box': {
                        'xmin': int(x1),
                        'ymin': int(y1),
                        'xmax': int(x2),
                        'ymax': int(y2)
                    },
                    'area': area
                })

    if not detected_vehicles:
        return None

    
    return max(detected_vehicles, key=lambda v: v['area'])


def crop_vehicle_area(image, vehicle, padding_ratio=0.08):
    """Crop around the detected vehicle so BiRefNet focuses on the car/vehicle."""
    image_rgb = image.convert('RGB')
    width, height = image_rgb.size
    box = vehicle['box']

    x1 = int(box['xmin'])
    y1 = int(box['ymin'])
    x2 = int(box['xmax'])
    y2 = int(box['ymax'])

    box_w = max(1, x2 - x1)
    box_h = max(1, y2 - y1)
    pad_x = int(box_w * padding_ratio)
    pad_y = int(box_h * padding_ratio)

    x1 = max(0, x1 - pad_x)
    y1 = max(0, y1 - pad_y)
    x2 = min(width, x2 + pad_x)
    y2 = min(height, y2 + pad_y)

    return image_rgb.crop((x1, y1, x2, y2))


def remove_background_birefnet(image):
    image_rgb = image.convert('RGB')
    input_tensor = transform_image(image_rgb).unsqueeze(0).to(device).float()

    with torch.no_grad():
        output = birefnet_model(input_tensor)

        # BiRefNet usually returns a list/tuple of predictions.
        if isinstance(output, (list, tuple)):
            pred = output[-1]
        else:
            pred = output

        pred = pred.sigmoid().cpu()[0].squeeze()

    mask = transforms.ToPILImage()(pred)
    mask = mask.resize(image_rgb.size, Image.Resampling.LANCZOS)

    result = image_rgb.copy()
    result.putalpha(mask)
    return result


def hide_number_plates_rgba(img):
    if img.mode != 'RGBA':
        img = img.convert('RGBA')

    arr = np.array(img)
    rgb = img.convert('RGB')
    detections = plate_detector(rgb)
    plates = [d for d in detections if d['score'] > 0.3]

    for p in plates:
        box = p['box']
        x1 = max(0, int(box['xmin']) - 5)
        y1 = max(0, int(box['ymin']) - 5)
        x2 = min(arr.shape[1], int(box['xmax']) + 5)
        y2 = min(arr.shape[0], int(box['ymax']) + 5)
        cv2.rectangle(arr, (x1, y1), (x2, y2), (255, 255, 255, 255), -1)

    return Image.fromarray(arr, 'RGBA'), plates


@app.get('/')
async def root():
    return {
        'status': 'online',
        'models': {
            'vehicle': 'YOLO26 yolo26n.pt',
            'bg': 'ZhengPeng7/BiRefNet',
            'plate': 'YOLOS small model'
        },
        'device': device
    }


@app.get('/health')
async def health():
    return {
        'status': 'ready',
        'device': device,
        'vehicle_model': 'yolo26n.pt',
        'bg_model': 'ZhengPeng7/BiRefNet',
        'plate_model': 'nickmuchi/yolos-small-finetuned-license-plate-detection'
    }


@app.post('/remove-background')
async def remove_background(file: UploadFile = File(...)):
    try:
        logger.info(f'BG removal with BiRefNet: {file.filename}')
        contents = await file.read()
        image = Image.open(io.BytesIO(contents))
        result = remove_background_birefnet(image)
        buf = io.BytesIO()
        result.save(buf, format='PNG')
        b64 = base64.b64encode(buf.getvalue()).decode()
        logger.info('Background removed with BiRefNet')
        return {'success': True, 'processed_image': b64}
    except Exception as e:
        logger.error(f'Error: {e}')
        raise HTTPException(500, str(e))


@app.post('/process-vehicle')
async def process_vehicle(file: UploadFile = File(...)):
    try:
        logger.info(f'One-step processing with YOLO26 + BiRefNet + YOLOS: {file.filename}')
        contents = await file.read()
        image = Image.open(io.BytesIO(contents))

        vehicle = detect_vehicle_yolo26(image)

        if vehicle is None:
            logger.info('No vehicle detected. Processing stopped.')
            return {
                'success': False,
                'message': 'No car or vehicle detected. Please upload a clear vehicle image.',
                'vehicle_detected': False,
                'plates_detected': 0,
                'background_removed': False,
                'transparency_preserved': False,
                'detections': []
            }

        logger.info(f"Vehicle detected: {vehicle['class']} with confidence {vehicle['score']:.2f}")

       
        vehicle_crop = crop_vehicle_area(image, vehicle)
        bg_removed = remove_background_birefnet(vehicle_crop)
        final_img, plates = hide_number_plates_rgba(bg_removed)

        buf = io.BytesIO()
        final_img.save(buf, format='PNG')
        b64 = base64.b64encode(buf.getvalue()).decode()

        logger.info(f'One-step complete. Plates hidden: {len(plates)}')
        return {
            'success': True,
            'processed_image': b64,
            'vehicle_detected': True,
            'vehicle_model': 'YOLO26 yolo26n.pt',
            'vehicle': {
                'class': vehicle['class'],
                'score': float(vehicle['score']),
                'box': vehicle['box']
            },
            'plates_detected': len(plates),
            'background_removed': True,
            'transparency_preserved': True,
            'bg_model': 'ZhengPeng7/BiRefNet',
            'detections': [
                {
                    'score': float(d['score']),
                    'box': {
                        'xmin': int(d['box']['xmin']),
                        'ymin': int(d['box']['ymin']),
                        'xmax': int(d['box']['xmax']),
                        'ymax': int(d['box']['ymax'])
                    }
                } for d in plates
            ]
        }
    except Exception as e:
        logger.error(f'Error: {e}')
        raise HTTPException(500, str(e))


@app.post('/detect-and-hide')
async def detect_and_hide(file: UploadFile = File(...)):
    try:
        logger.info(f'Plate detection: {file.filename}')
        contents = await file.read()
        img = Image.open(io.BytesIO(contents))
        if img.mode != 'RGBA':
            img = img.convert('RGBA')
        arr = np.array(img)
        rgb = img.convert('RGB')
        detections = plate_detector(rgb)
        plates = [d for d in detections if d['score'] > 0.3]
        if not plates:
            return {'success': False, 'message': 'No plates', 'plates_detected': 0}
        logger.info(f'Found {len(plates)} plate(s)')
        for p in plates:
            box = p['box']
            x1 = max(0, int(box['xmin']) - 5)
            y1 = max(0, int(box['ymin']) - 5)
            x2 = min(arr.shape[1], int(box['xmax']) + 5)
            y2 = min(arr.shape[0], int(box['ymax']) + 5)
            cv2.rectangle(arr, (x1, y1), (x2, y2), (255, 255, 255, 255), -1)
        proc = Image.fromarray(arr, 'RGBA')
        buf = io.BytesIO()
        proc.save(buf, format='PNG')
        b64 = base64.b64encode(buf.getvalue()).decode()
        logger.info('Done')
        return {
            'success': True,
            'plates_detected': len(plates),
            'processed_image': b64,
            'detections': [{'score': float(d['score']), 'box': {'xmin': int(d['box']['xmin']), 'ymin': int(d['box']['ymin']), 'xmax': int(d['box']['xmax']), 'ymax': int(d['box']['ymax'])}} for d in plates],
            'transparency_preserved': True
        }
    except Exception as e:
        logger.error(f'Error: {e}')
        raise HTTPException(500, str(e))


if __name__ == '__main__':
    print(f'Backend running locally on http://127.0.0.1:{PORT}')
    print(f'Device: {device}')
    print('Vehicle model: YOLO26 yolo26n.pt')
    print('Background model: ZhengPeng7/BiRefNet')
    print('Plate model: nickmuchi/yolos-small-finetuned-license-plate-detection')
    uvicorn.run(app, host='0.0.0.0', port=PORT, log_level='info')
