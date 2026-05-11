from flask import Flask, request, send_file
from rembg import remove
from PIL import Image
import io

app = Flask(__name__)

@app.route("/remove-bg", methods=["POST"])
def remove_bg():

    file = request.files["image"]

    input_image = Image.open(file.stream)

    output_image = remove(input_image)

    img_io = io.BytesIO()

    output_image.save(img_io, format="PNG")

    img_io.seek(0)

    return send_file(
        img_io,
        mimetype="image/png"
    )

if __name__ == "__main__":

    app.run(port=8000)