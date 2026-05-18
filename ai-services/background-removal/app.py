from flask import Flask, request, send_file
from transformers import AutoModelForImageSegmentation
from torchvision import transforms
from PIL import Image
import torch
import io

app = Flask(__name__)

print("Loading RMBG-2.0 model...")

model = AutoModelForImageSegmentation.from_pretrained(
    "briaai/RMBG-2.0",
    trust_remote_code=True
)

model.eval()

print("RMBG-2.0 loaded successfully")

transform_image = transforms.Compose([
    transforms.Resize((1024, 1024)),
    transforms.ToTensor(),
])

@app.route("/remove-bg", methods=["POST"])
def remove_bg():

    file = request.files["image"]

    image = Image.open(file.stream).convert("RGB")

    original_size = image.size

    input_tensor = transform_image(image).unsqueeze(0)

    with torch.no_grad():

        prediction = model(input_tensor)[-1].sigmoid().cpu()[0].squeeze()

    mask = transforms.ToPILImage()(prediction)

    mask = mask.resize(original_size)

    image = image.convert("RGBA")

    image.putalpha(mask)

    img_io = io.BytesIO()

    image.save(img_io, format="PNG")

    img_io.seek(0)

    return send_file(
        img_io,
        mimetype="image/png"
    )

if __name__ == "__main__":

    app.run(port=8000)