from transformers import YolosImageProcessor, YolosForObjectDetection
from PIL import Image
import torch
import cv2
import numpy as np

# LOAD MODEL
processor = YolosImageProcessor.from_pretrained(
    "nickmuchi/yolos-small-finetuned-license-plate-detection"
)

model = YolosForObjectDetection.from_pretrained(
    "nickmuchi/yolos-small-finetuned-license-plate-detection"
)

# LOAD IMAGE
image = Image.open("test-car.jpg").convert("RGB")

# PROCESS IMAGE
inputs = processor(images=image, return_tensors="pt")

# RUN DETECTION
outputs = model(**inputs)

# POST PROCESS
target_sizes = torch.tensor([image.size[::-1]])

results = processor.post_process_object_detection(
    outputs,
    threshold=0.5,
    target_sizes=target_sizes
)[0]

# CONVERT TO OPENCV
image_np = np.array(image)

# LOOP DETECTIONS
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

# SAVE OUTPUT
output = Image.fromarray(image_np)

output.save("blurred-result.jpg")

print("DONE")