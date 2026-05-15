#!/usr/bin/env python3
"""
AutoPivot Plate Detection API - Python Script Version
======================================================

This script runs a FastAPI server with YOLOS plate detection.
Can be run on Google Colab or any server.

Usage:
    python autopivot_backend.py

Requirements:
    - ngrok token (for public URL)
    - See requirements at bottom of file
"""

# ============================================================================
# STEP 1: Install Dependencies
# ============================================================================

import subprocess
import sys

def install_packages():
    """Install required packages"""
    packages = [
        'fastapi',
        'uvicorn',
        'pyngrok',
        'python-multipart',
        'nest-asyncio',
        'transformers',
        'torch',
        'pillow',
        'opencv-python'
    ]
    
    print("📦 Installing packages...\n")
    for package in packages:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-q', package])
    print("✅ All packages installed!\n")

# Uncomment if running for first time
# install_packages()

# ============================================================================
# STEP 2: Setup ngrok
# ============================================================================

from pyngrok import ngrok, conf

# Your ngrok token (embedded)
NGROK_TOKEN = "3DYYJVSDgP5GwING9QcQPn0pxoX_2oqL4skAe3zc3sogA5jxA"

# Set ngrok token
conf.get_default().auth_token = NGROK_TOKEN
print("✅ Ngrok configured!")

# ============================================================================
# STEP 3: Load YOLOS Model
# ============================================================================

from transformers import pipeline
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

print("\n📦 Loading YOLOS plate detection model...")
print("⏳ This may take 1-2 minutes on first run...\n")

plate_detector = pipeline(
    "object-detection",
    model="nickmuchi/yolos-small-finetuned-license-plate-detection"
)

print("✅ Model loaded successfully!")
print("🚀 Ready to detect license plates!\n")

# ============================================================================
# STEP 4: Create FastAPI Server
# ============================================================================

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image
import io
import base64
import numpy as np
import cv2

# Create FastAPI app
app = FastAPI(
    title="AutoPivot Plate Detection API",
    description="AI-powered license plate detection using YOLOS",
    version="1.0.0"
)

# Enable CORS for all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "online",
        "service": "AutoPivot Plate Detection API",
        "model": "YOLOS License Plate Detection",
        "version": "1.0.0"
    }

@app.get("/health")
async def health_check():
    """Check if model is ready"""
    return {
        "status": "ready",
        "message": "Model loaded and ready to detect!",
        "platform": "Python Backend 🚀"
    }

@app.post("/detect-plates")
async def detect_plates(file: UploadFile = File(...)):
    """
    Detect license plates in an uploaded image
    Returns: JSON with detected plate locations
    """
    try:
        # Read uploaded image
        logger.info(f"Processing image: {file.filename}")
        contents = await file.read()
        image = Image.open(io.BytesIO(contents)).convert("RGB")
        
        # Run detection
        logger.info("Running plate detection...")
        detections = plate_detector(image)
        
        # Filter and format results
        plates = [
            {
                "score": float(det["score"]),
                "label": det["label"],
                "box": {
                    "xmin": int(det["box"]["xmin"]),
                    "ymin": int(det["box"]["ymin"]),
                    "xmax": int(det["box"]["xmax"]),
                    "ymax": int(det["box"]["ymax"])
                }
            }
            for det in detections
            if det["score"] > 0.3
        ]
        
        logger.info(f"✅ Detected {len(plates)} plate(s)")
        
        return {
            "success": True,
            "plates_detected": len(plates),
            "detections": plates,
            "image_size": {
                "width": image.width,
                "height": image.height
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Detection failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/detect-and-hide")
async def detect_and_hide_plates(file: UploadFile = File(...)):
    """
    Detect plates and return image with plates covered by white rectangles
    Preserves transparency if present in input
    Returns: Base64 encoded image with plates hidden
    """
    try:
        # Read uploaded image
        logger.info(f"Processing image: {file.filename}")
        contents = await file.read()
        image = Image.open(io.BytesIO(contents))
        
        # Check for transparency
        has_alpha = image.mode in ('RGBA', 'LA') or (image.mode == 'P' and 'transparency' in image.info)
        
        # Convert to RGBA if has transparency, otherwise RGB
        if has_alpha and image.mode != 'RGBA':
            image = image.convert('RGBA')
        elif not has_alpha and image.mode != 'RGB':
            image = image.convert('RGB')
        
        # Convert to numpy array
        img_array = np.array(image)
        
        # Run detection on RGB version
        rgb_image = image.convert('RGB')
        detections = plate_detector(rgb_image)
        
        # Filter plates
        plates = [det for det in detections if det["score"] > 0.3]
        
        if len(plates) == 0:
            logger.warning("No plates detected")
            return {
                "success": False,
                "message": "No license plates detected in the image",
                "plates_detected": 0
            }
        
        # Cover plates with white rectangles
        logger.info(f"Hiding {len(plates)} plate(s)...")
        for plate in plates:
            box = plate["box"]
            
            # Add padding to ensure full coverage
            padding = 5
            x1 = max(0, int(box["xmin"]) - padding)
            y1 = max(0, int(box["ymin"]) - padding)
            x2 = min(img_array.shape[1], int(box["xmax"]) + padding)
            y2 = min(img_array.shape[0], int(box["ymax"]) + padding)
            
            # Draw white rectangle (with alpha if image has transparency)
            if has_alpha:
                cv2.rectangle(img_array, (x1, y1), (x2, y2), (255, 255, 255, 255), -1)
            else:
                cv2.rectangle(img_array, (x1, y1), (x2, y2), (255, 255, 255), -1)
        
        # Convert back to PIL Image
        if has_alpha:
            processed_image = Image.fromarray(img_array, 'RGBA')
        else:
            processed_image = Image.fromarray(img_array, 'RGB')
        
        # Convert to base64
        buffered = io.BytesIO()
        processed_image.save(buffered, format="PNG")
        img_base64 = base64.b64encode(buffered.getvalue()).decode()
        
        logger.info("✅ Processing complete")
        
        return {
            "success": True,
            "plates_detected": len(plates),
            "processed_image": img_base64,
            "detections": [
                {
                    "score": float(det["score"]),
                    "box": {
                        "xmin": int(det["box"]["xmin"]),
                        "ymin": int(det["box"]["ymin"]),
                        "xmax": int(det["box"]["xmax"]),
                        "ymax": int(det["box"]["ymax"])
                    }
                }
                for det in plates
            ],
            "transparency_preserved": has_alpha
        }
        
    except Exception as e:
        logger.error(f"❌ Processing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

print("✅ FastAPI server configured!")

# ============================================================================
# STEP 5: Start Server with ngrok Tunnel
# ============================================================================

async def start_server():
    """Start the server with ngrok tunnel"""
    import nest_asyncio
    import uvicorn
    
    # Allow nested event loops (needed for Colab/Jupyter)
    nest_asyncio.apply()
    
    # Kill any existing tunnels
    try:
        ngrok.kill()
    except:
        pass
    
    # Start ngrok tunnel
    port = 8000
    public_url = ngrok.connect(port)
    
    print("\n" + "="*70)
    print("🚀 SERVER STARTED SUCCESSFULLY!")
    print("="*70)
    print(f"\n📡 Public URL: {public_url}")
    print(f"\n📋 Copy this URL and update your frontend:")
    print(f"   const BACKEND_URL = '{public_url}';")
    print("\n" + "="*70)
    print("\n⚡ API Endpoints:")
    print(f"   GET  {public_url}/          - Health check")
    print(f"   GET  {public_url}/health    - Model status")
    print(f"   POST {public_url}/detect-plates     - Detect only")
    print(f"   POST {public_url}/detect-and-hide   - Detect & hide")
    print("\n" + "="*70)
    print("\n🔥 Server is running! Keep this running.")
    print("💡 Press Ctrl+C to stop.")
    print("\n" + "="*70 + "\n")
    
    # Run server
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    import asyncio
    
    # Check if running in Jupyter/Colab
    try:
        get_ipython()
        # Running in notebook - use await
        print("Running in Jupyter/Colab environment")
        print("Execute: await start_server()")
    except NameError:
        # Running as script - use asyncio.run
        print("Running as Python script")
        asyncio.run(start_server())

# ============================================================================
# REQUIREMENTS.TXT
# ============================================================================
"""
Create a requirements.txt file with:

fastapi
uvicorn
pyngrok
python-multipart
nest-asyncio
transformers
torch
pillow
opencv-python
"""

# ============================================================================
# USAGE INSTRUCTIONS
# ============================================================================
"""
OPTION 1: Run as Python script
-------------------------------
1. Install packages: pip install -r requirements.txt
2. Run script: python autopivot_backend.py
3. Copy the ngrok URL
4. Update your frontend

OPTION 2: Run in Google Colab
------------------------------
1. Upload this file to Colab
2. Run all cells or:
   - import autopivot_backend
   - await autopivot_backend.start_server()
3. Copy the ngrok URL
4. Update your frontend

OPTION 3: Run in Jupyter
-------------------------
1. Load in Jupyter notebook
2. Run cells up to server start
3. Execute: await start_server()
4. Copy the ngrok URL
5. Update your frontend
"""
