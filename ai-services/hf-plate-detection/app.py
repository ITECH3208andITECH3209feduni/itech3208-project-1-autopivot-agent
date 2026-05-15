from flask import Flask, request, send_file
from transformers import YolosImageProcessor, YolosForObjectDetection
from PIL import Image
import torch
import numpy as np
import io

app = Flask(__name__)

print("Loading model...")

processor = YolosImageProcessor.from_pretrained(
    "nickmuchi/yolos-small-finetuned-license-plate-detection"
)

model = YolosForObjectDetection.from_pretrained(
    "nickmuchi/yolos-small-finetuned-license-plate-detection"
)

print("Model loaded")

# LOAD LOGO

logo = Image.open("assets/logo.png").convert("RGB")

@app.route("/blur-plate", methods=["POST"])
def blur_plate():

    file = request.files["image"]

    image = Image.open(file.stream).convert("RGB")

    inputs = processor(images=image, return_tensors="pt")

    outputs = model(**inputs)

    target_sizes = torch.tensor([image.size[::-1]])

    results = processor.post_process_object_detection(
        outputs,
        threshold=0.5,
        target_sizes=target_sizes
    )[0]

    image_np = np.array(image)

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

            resized_logo_np = np.array(resized_logo)

            image_np[y1:y2, x1:x2] = resized_logo_np

    output_image = Image.fromarray(image_np)

    img_io = io.BytesIO()

    output_image.save(img_io, format="PNG")

    img_io.seek(0)

    return send_file(
        img_io,
        mimetype="image/png"
    )

if __name__ == "__main__":

    app.run(port=9000)