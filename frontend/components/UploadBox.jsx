"use client";

import { useState } from "react";
import axios from "axios";

export default function UploadBox() {

  const [image, setImage] = useState(null);

  const [processedImage, setProcessedImage] = useState(null);

  const processCar = async () => {

    if (!image) {

      alert("Please select an image");

      return;

    }

    const formData = new FormData();

    formData.append("image", image);

    try {

      const response = await axios.post(
        "http://localhost:5000/process-car",
        formData,
        {
          responseType: "blob",
        }
      );

      const imageUrl = URL.createObjectURL(response.data);

      setProcessedImage(imageUrl);

    } catch (error) {

      console.log(error);

      alert("Processing Failed");

    }

  };

  return (

    <div className="bg-white p-8 rounded-2xl shadow-lg w-full max-w-4xl">

      <label className="border-2 border-dashed border-blue-300 rounded-xl p-16 flex flex-col items-center justify-center cursor-pointer hover:bg-blue-50 transition">

        <input
          type="file"
          className="hidden"
          onChange={(e) => {
            setImage(e.target.files[0]);
            setProcessedImage(null);
          }}
        />

        <p className="text-blue-900 text-xl font-bold">
          Upload Vehicle Image
        </p>

        <p className="text-blue-500 mt-2">
          JPG · PNG · WEBP
        </p>

      </label>

      {image && (

        <div className="mt-8">

          <h2 className="text-xl font-bold text-blue-900 mb-4">
            Original Image
          </h2>

          <img
            src={URL.createObjectURL(image)}
            alt="original"
            className="rounded-xl border shadow-md"
          />

          <button
            onClick={processCar}
            className="bg-blue-900 text-white px-6 py-4 rounded-xl mt-6 w-full hover:bg-blue-700 text-lg font-semibold"
          >
            Generate Final Car Result
          </button>

        </div>

      )}

      {processedImage && (

        <div className="mt-10">

          <h2 className="text-2xl font-bold text-green-700 mb-4">
            Final AI Processed Vehicle
          </h2>

          <img
            src={processedImage}
            alt="processed"
            className="rounded-xl border shadow-lg"
          />

          <a
            href={processedImage}
            download="final-car-result.png"
            className="block text-center bg-green-600 text-white px-6 py-4 rounded-xl mt-6 hover:bg-green-500 text-lg font-semibold"
          >
            Download Final Image
          </a>

        </div>

      )}

    </div>

  );
}