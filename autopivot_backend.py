from huggingface_hub import login
from PIL import Image
import torch
from torchvision import transforms
from transformers import AutoModelForImageSegmentation, pipeline
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import io, base64, numpy as np, cv2, logging, uvicorn

HF_TOKEN = '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'
PORT = 8000

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

login(token=HF_TOKEN)

device = 'cuda' if torch.cuda.is_available() else 'cpu'

rmbg_model = AutoModelForImageSegmentation.from_pretrained(
    'briaai/RMBG-2.0',
    trust_remote_code=True
).eval().to(device)

image_size = (1024, 1024)
transform_image = transforms.Compose([
    transforms.Resize(image_size),
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
])

plate_detector = pipeline(
    'object-detection',
    model='nickmuchi/yolos-small-finetuned-license-plate-detection'
)

app = FastAPI(title='AutoPivot - RMBG-2.0 + YOLOS small model')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)


def remove_background_rmbg(image):
    image_rgb = image.convert('RGB')
    input_tensor = transform_image(image_rgb).unsqueeze(0).to(device)
    with torch.no_grad():
        preds = rmbg_model(input_tensor)[-1].sigmoid().cpu()
    pred = preds[0].squeeze()
    mask = transforms.ToPILImage()(pred)
    mask = mask.resize(image_rgb.size)
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
    return {'status': 'online', 'models': {'bg': 'RMBG-2.0', 'plate': 'YOLOS small model'}, 'device': device}


@app.get('/health')
async def health():
    return {'status': 'ready', 'device': device}


@app.post('/remove-background')
async def remove_background(file: UploadFile = File(...)):
    try:
        logger.info(f'BG removal: {file.filename}')
        contents = await file.read()
        image = Image.open(io.BytesIO(contents))
        result = remove_background_rmbg(image)
        buf = io.BytesIO()
        result.save(buf, format='PNG')
        b64 = base64.b64encode(buf.getvalue()).decode()
        logger.info('Background removed')
        return {'success': True, 'processed_image': b64}
    except Exception as e:
        logger.error(f'Error: {e}')
        raise HTTPException(500, str(e))


@app.post('/process-vehicle')
async def process_vehicle(file: UploadFile = File(...)):
    try:
        logger.info(f'One-step processing: {file.filename}')
        contents = await file.read()
        image = Image.open(io.BytesIO(contents))

        bg_removed = remove_background_rmbg(image)
        final_img, plates = hide_number_plates_rgba(bg_removed)

        buf = io.BytesIO()
        final_img.save(buf, format='PNG')
        b64 = base64.b64encode(buf.getvalue()).decode()

        logger.info(f'One-step complete. Plates hidden: {len(plates)}')
        return {
            'success': True,
            'processed_image': b64,
            'plates_detected': len(plates),
            'background_removed': True,
            'transparency_preserved': True,
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
    print('=' * 70)
    print(f'Backend running locally on port {PORT}')
    print(f'In a SECOND terminal, run:')
    print(f'   ngrok http --url=unchanged-making-delicious.ngrok-free.dev {PORT}')
    print(f'Your public URL: https://unchanged-making-delicious.ngrok-free.dev')
    print('=' * 70)
    uvicorn.run(app, host='0.0.0.0', port=PORT, log_level='info')
