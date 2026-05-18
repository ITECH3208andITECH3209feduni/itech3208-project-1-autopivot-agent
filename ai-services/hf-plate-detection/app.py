from flask import Flask, request, send_file
from transformers import YolosImageProcessor, YolosForObjectDetection
from PIL import Image, ImageDraw
import torch
import numpy as np
import io
import os

app = Flask(__name__)

print("Loading YOLOS plate detection model...")

processor = YolosImageProcessor.from_pretrained(
    "nickmuchi/yolos-small-finetuned-license-plate-detection"
)

model = YolosForObjectDetection.from_pretrained(
    "nickmuchi/yolos-small-finetuned-license-plate-detection"
)

print("YOLOS model loaded successfully")

# ======================================
# LOAD LOGO
# ======================================

logo = Image.open("assets/logo.png").convert("RGBA")

# ======================================
# PROCESS PLATE
# ======================================

@app.route("/blur-plate", methods=["POST"])
def blur_plate():

    file = request.files["image"]

    # IMPORTANT
    # KEEP TRANSPARENCY

    image = Image.open(file.stream).convert("RGBA")

    inputs = processor(
        images=image.convert("RGB"),
        return_tensors="pt"
    )

    outputs = model(**inputs)

    target_sizes = torch.tensor([image.size[::-1]])

    results = processor.post_process_object_detection(
        outputs,
        threshold=0.5,
        target_sizes=target_sizes
    )[0]

    # ======================================
    # CREATE WHITE PLATE VERSION
    # ======================================

    plate_removed_image = image.copy()

    draw = ImageDraw.Draw(plate_removed_image)

    for score, label, box in zip(
        results["scores"],
        results["labels"],
        results["boxes"]
    ):

        box = [int(i) for i in box.tolist()]

        x1, y1, x2, y2 = box

        plate_width = x2 - x1
        plate_height = y2 - y1

        if plate_width > 0 and plate_height > 0:

            # ======================================
            # DRAW WHITE PLATE
            # ======================================

            draw.rectangle(
                [x1, y1, x2, y2],
                fill=(255, 255, 255, 255)
            )

    # SAVE INTERMEDIATE RESULT

    os.makedirs("outputs", exist_ok=True)

    plate_removed_image.save(
        "../../backend/outputs/plate-removed.png"
    )

    # ======================================
    # FINAL RESULT WITH LOGO
    # ======================================

    final_image = plate_removed_image.copy()

    for score, label, box in zip(
        results["scores"],
        results["labels"],
        results["boxes"]
    ):

        box = [int(i) for i in box.tolist()]

        x1, y1, x2, y2 = box

        plate_width = x2 - x1
        plate_height = y2 - y1

        if plate_width > 0 and plate_height > 0:

            resized_logo = logo.resize(
                (plate_width, plate_height)
            )

            final_image.paste(
                resized_logo,
                (x1, y1),
                resized_logo
            )

    # SAVE FINAL OUTPUT

    final_image.save(
        "../../backend/outputs/final-output.png"
    )

    # ======================================
    # RETURN FINAL OUTPUT
    # ======================================

    img_io = io.BytesIO()

    final_image.save(img_io, format="PNG")

    img_io.seek(0)

    return send_file(
        img_io,
        mimetype="image/png"
    )

# ======================================
# START SERVER
# ======================================

if __name__ == "__main__":

    app.run(port=9000)