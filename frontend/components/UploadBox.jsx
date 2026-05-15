"use client";

import { useState, useEffect } from "react";
import axios from "axios";

export default function UploadBox() {

  const [image, setImage] = useState(null);

  const [bgRemovedImage, setBgRemovedImage] = useState(null);

  const [finalImage, setFinalImage] = useState(null);

  // ======================================
  // HANDLE CLIPBOARD PASTE
  // ======================================

  useEffect(() => {

    const handlePaste = (event) => {

      const items = event.clipboardData.items;

      for (let item of items) {

        if (item.type.startsWith("image")) {

          const file = item.getAsFile();

          setImage(file);

          setBgRemovedImage(null);

          setFinalImage(null);

        }

      }

    };

    window.addEventListener("paste", handlePaste);

    return () => {

      window.removeEventListener("paste", handlePaste);

    };

  }, []);

  // ======================================
  // DRAG & DROP
  // ======================================

  const handleDrop = (event) => {

    event.preventDefault();

    const file = event.dataTransfer.files[0];

    if (file) {

      setImage(file);

      setBgRemovedImage(null);

      setFinalImage(null);

    }

  };

  const handleDragOver = (event) => {

    event.preventDefault();

  };

  // ======================================
  // PROCESS CAR
  // ======================================

  const processCar = async () => {

    if (!image) {

      alert("Please select an image");

      return;

    }

    const formData = new FormData();

    formData.append("image", image);

    try {

      await axios.post(
        "http://localhost:5000/process-car",
        formData
      );

      // LOAD GENERATED OUTPUTS

      setBgRemovedImage(
        "http://localhost:5000/outputs/background-output.png"
      );

      setFinalImage(
        "http://localhost:5000/outputs/final-output.png"
      );

    } catch (error) {

      console.log(error);

      alert("Processing Failed");

    }

  };

  return (

    <div className="bg-white p-8 rounded-2xl shadow-lg w-full max-w-5xl">

      {/* ====================================== */}
      {/* UPLOAD AREA */}
      {/* ====================================== */}

      <div
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        className="border-2 border-dashed border-blue-300 rounded-xl p-16 flex flex-col items-center justify-center cursor-pointer hover:bg-blue-50 transition"
      >

        <input
          type="file"
          id="fileUpload"
          className="hidden"
          onChange={(e) => {

            setImage(e.target.files[0]);

            setBgRemovedImage(null);

            setFinalImage(null);

          }}
        />

        <label
          htmlFor="fileUpload"
          className="cursor-pointer text-center"
        >

          <p className="text-blue-900 text-2xl font-bold">
            Upload, Drag & Drop, or Paste Vehicle Image
          </p>

          <p className="text-blue-500 mt-3">
            JPG · PNG · WEBP
          </p>

          <p className="text-blue-400 mt-3 text-sm">
            Ctrl + V to paste screenshots or copied internet images
          </p>

        </label>

      </div>

      {/* ====================================== */}
      {/* ORIGINAL IMAGE */}
      {/* ====================================== */}

      {image && (

        <div className="mt-10">

          <h2 className="text-2xl font-bold text-blue-900 mb-4">
            Original Vehicle Image
          </h2>

          <img
            src={URL.createObjectURL(image)}
            alt="original"
            className="rounded-xl border shadow-lg"
          />

          <button
            onClick={processCar}
            className="bg-blue-900 text-white px-6 py-4 rounded-xl mt-6 w-full hover:bg-blue-700 text-lg font-semibold"
          >
            Generate Final Car Result
          </button>

        </div>

      )}

      {/* ====================================== */}
      {/* BACKGROUND REMOVED OUTPUT */}
      {/* ====================================== */}

      {bgRemovedImage && (

        <div className="mt-12">

          <h2 className="text-2xl font-bold text-blue-700 mb-4">
            Background Removed Result
          </h2>

          <div className="bg-gray-300 p-6 rounded-xl">

            <img
              src={bgRemovedImage}
              alt="background removed"
              className="rounded-xl shadow-lg"
            />

          </div>

        </div>

      )}

      {/* ====================================== */}
      {/* FINAL OUTPUT */}
      {/* ====================================== */}

      {finalImage && (

        <div className="mt-12">

          <h2 className="text-2xl font-bold text-green-700 mb-4">
            Final AI Processed Vehicle
          </h2>

          <div className="bg-gray-300 p-6 rounded-xl">

            <img
              src={finalImage}
              alt="final vehicle"
              className="rounded-xl shadow-lg"
            />

          </div>

          <a
            href={finalImage}
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