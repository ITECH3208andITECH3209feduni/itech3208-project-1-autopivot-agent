from flask import Flask, request, send_file
from transformers import YolosImageProcessor, YolosForObjectDetection
from PIL import Image
import torch
import cv2
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

        roi = image_np[y1:y2, x1:x2]

        if roi.size > 0:

            blurred = cv2.GaussianBlur(
                roi,
                (99, 99),
                30
            )

            image_np[y1:y2, x1:x2] = blurred

    output = Image.fromarray(image_np)

    img_io = io.BytesIO()

    output.save(img_io, format="PNG")

    img_io.seek(0)

    return send_file(
        img_io,
        mimetype="image/png"
    )

if __name__ == "__main__":

    app.run(port=9000)