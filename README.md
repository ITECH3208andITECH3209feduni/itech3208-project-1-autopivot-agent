# AutoPivot Agent

AutoPivot Agent is a local demo web application for vehicle image processing. It allows a user to upload a vehicle photo, remove the background, hide the number plate, and optionally place a custom image/logo on the covered plate area.

## What the app does

- Upload one vehicle image from the browser
- Remove the image background using RMBG-2.0
- Detect and cover the number plate using the YOLOS small plate detection model
- Show the final processed image in the preview area
- Allow the user to drag and drop a small image/logo onto the covered plate area
- Download the final PNG result

## Project files

```text
autopivot_backend.py   
index.html             
style.css              
app.js                 
requirements.txt      
README.md              
```

## Backend

The backend is written in Python using FastAPI. It loads the AI models and provides API endpoints for image processing.

Main endpoint used by the frontend:

```text
POST /process-vehicle
```

This endpoint performs the full one-step process:

1. Receives the uploaded vehicle image
2. Removes the background using RMBG-2.0
3. Detects the number plate using the YOLOS small plate detection model
4. Covers the detected plate with a white rectangle
5. Returns the processed PNG image to the frontend


## Frontend

The frontend is built with HTML, CSS, and JavaScript. It runs in the browser using Live Server.

The user can:

1. Upload a vehicle image
2. Click **Process Photo**
3. View the original and final result
4. Drag and drop a custom plate image/logo
5. Download the final PNG

The frontend connects to the backend through:

```javascript
const BACKEND_URL = 'http://127.0.0.1:8000';
```

## Requirements

- Python 3.10 or newer
- VS Code or another code editor
- Live Server extension for running the frontend
- Enough RAM/CPU to run the models locally

Install the Python packages with:

```bash
pip install -r requirements.txt
```

## How to run the project

### 1. Start the backend

Open a terminal in the project folder and run:

```bash
python autopivot_backend.py
```

### 2. Start the frontend

Open `index.html` with Live Server in VS Code.

Then upload an image and click **Process Photo**.

## Current status

This version is working as a local prototype. The main completed features are:

- One-step vehicle image processing
- Background removal
- Number plate hiding
- Final result preview
- Drag-and-drop custom plate overlay
- PNG download

## Team/project note

This repository is a demo implementation and is intended for local testing and prototyping.
