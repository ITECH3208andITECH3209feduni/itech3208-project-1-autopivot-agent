# AutoPivot Agent – Feature Branch

AutoPivot Agent is an AI-powered automotive merchandising platform designed to generate professional marketplace-ready vehicle images using modern web technologies and AI image processing pipelines.

This feature branch contains the latest Sprint 2 frontend redesign, backend restructuring, and AI workflow integration.

---

# System Architecture

```text
Frontend (Next.js)
        ↓
Express Backend
        ↓
Python AI Services
        ↓
Final Marketplace Vehicle Output
```

---

# Project Structure

```text
AUTOPIVOT/
│
├── ai-services/
│   ├── background-removal/
│   └── hf-plate-detection/
│
├── backend/
│   ├── controllers/
│   ├── routes/
│   ├── services/
│   ├── outputs/
│   ├── uploads/
│   ├── package.json
│   └── server.js
│
├── frontend/
│   ├── app/
│   ├── components/
│   ├── public/
│   ├── package.json
│   └── README.md
│
└── .gitignore
```

---

# Frontend

The frontend is built using:

- Next.js 16
- React
- JavaScript
- CSS

## Features

- Vehicle image upload
- Live AI result preview
- Multi-stage AI workflow visualization
- Responsive SaaS-style UI
- Downloadable marketplace vehicle image

---

# Backend

The backend is built using:

- Node.js
- Express.js
- Axios
- Multer

## Responsibilities

- Handle uploaded vehicle images
- Connect frontend with AI services
- Manage AI processing pipeline
- Save intermediate outputs
- Return processed results to frontend

---

# AI Services

The AI services are separated into modular Python Flask microservices.

---

# AI Service 1 – Background Removal

## Model Used

```text
briaai/RMBG-2.0
```

## Purpose

- Removes vehicle background
- Generates transparent PNG output
- Isolates the vehicle for further AI processing

## Workflow

```text
Vehicle Image
      ↓
RMBG-2.0
      ↓
Transparent Vehicle PNG
```

---

# AI Service 2 – Number Plate Detection

## Model Used

```text
nickmuchi/yolos-small-finetuned-license-plate-detection
```

## Purpose

- Detects vehicle number plates
- Generates bounding box coordinates
- Applies logo replacement and branding

## Workflow

```text
Transparent Vehicle PNG
        ↓
YOLOS Plate Detection
        ↓
Logo Replacement
        ↓
Final Branded Vehicle Output
```

---

# Current AI Pipeline

```text
Upload Vehicle Image
        ↓
Background Removal (RMBG-2.0)
        ↓
Number Plate Detection (YOLOS)
        ↓
Logo Replacement
        ↓
Final Marketplace Vehicle
```

---

# Git Ignore Configuration

The repository ignores generated and temporary files including:

```text
frontend/node_modules
frontend/.next
backend/node_modules
backend/uploads
backend/outputs
__pycache__
.env
```

This keeps the repository lightweight and deployment-ready.

---

# Installation

## Frontend

```bash
cd frontend
npm install
npm run dev
```

## Backend

```bash
cd backend
npm install
node server.js
```

## AI Services

```bash
pip install -r requirements.txt
python autopivot_backend.py
```

---

# Technologies Used

## Frontend
- Next.js
- React
- JavaScript

## Backend
- Node.js
- Express.js

## AI & Computer Vision
- Python
- Flask
- PyTorch
- Hugging Face Transformers
- RMBG-2.0
- YOLOS Small

---

# Sprint 2 Focus

- Frontend redesign
- Live AI preview integration
- AI workflow visualization
- Background removal pipeline
- Number plate detection pipeline
- Marketplace-ready branded vehicle generation
