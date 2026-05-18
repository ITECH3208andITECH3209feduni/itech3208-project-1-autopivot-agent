"use client";

import { useState, useEffect } from "react";
import axios from "axios";

export default function UploadBox({
  setPreviewImage,
  setFinalPreview
}) {

  const [image, setImage] = useState(null);

  const [bgRemovedImage, setBgRemovedImage] = useState(null);

  const [plateRemovedImage, setPlateRemovedImage] = useState(null);

  const [finalImage, setFinalImage] = useState(null);

  const [loading, setLoading] = useState(false);

  // ======================================
  // HANDLE CLIPBOARD PASTE
  // ======================================

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

        // LIVE HERO PREVIEW

        setPreviewImage(
          URL.createObjectURL(file)
        );

        // RESET OLD OUTPUTS

        setBgRemovedImage(null);

        setPlateRemovedImage(null);

        setFinalImage(null);

        setFinalPreview(null);

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

      // LIVE HERO PREVIEW

      setPreviewImage(
        URL.createObjectURL(file)
      );

      // RESET OLD OUTPUTS

      setBgRemovedImage(null);

      setPlateRemovedImage(null);

      setFinalImage(null);

      setFinalPreview(null);

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

    setLoading(true);

    const formData = new FormData();

    formData.append("image", image);

    try {

      await axios.post(
        "http://localhost:5000/process-car",
        formData
      );

      // FORCE REFRESH

      const timestamp = Date.now();

      const bgUrl =
        `http://localhost:5000/outputs/background-output.png?t=${timestamp}`;

      const plateUrl =
        `http://localhost:5000/outputs/plate-removed.png?t=${timestamp}`;

      const finalUrl =
        `http://localhost:5000/outputs/final-output.png?t=${timestamp}`;

      // UPDATE STAGES

      setBgRemovedImage(bgUrl);

      setPlateRemovedImage(plateUrl);

      setFinalImage(finalUrl);

      // UPDATE HERO LIVE PREVIEW

      setFinalPreview(finalUrl);

    } catch (error) {

      console.log(error);

      alert("Processing Failed");

    }

    setLoading(false);

  };

  return (

    <div className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-blue-950 text-white p-8 rounded-3xl shadow-2xl">

      <div className="max-w-7xl mx-auto">

        {/* HERO */}

        <div className="text-center mb-14">

          <h1 className="text-6xl font-black tracking-tight bg-gradient-to-r from-blue-400 to-cyan-300 text-transparent bg-clip-text">
            AutoPivot Agent
          </h1>

          <p className="text-slate-300 text-xl mt-5 max-w-3xl mx-auto leading-relaxed">
            AI-powered vehicle merchandising platform for background
            removal, number plate protection, branding, and dealership-ready
            automotive imagery.
          </p>

        </div>

        {/* FEATURE CARDS */}

        <div className="grid grid-cols-1 md:grid-cols-5 gap-5 mb-14">

          {[
            "RMBG-2.0 Background Removal",
            "YOLOS Plate Detection",
            "OpenCV Logo Placement",
            "Transparent PNG Processing",
            "HD Vehicle Export"
          ].map((feature, index) => (

            <div
              key={index}
              className="bg-white/10 backdrop-blur-md border border-white/10 rounded-2xl p-5 text-center shadow-xl hover:scale-105 transition"
            >

              <p className="font-semibold text-slate-200">
                {feature}
              </p>

            </div>

          ))}

        </div>

        {/* MAIN GRID */}

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-10">

          {/* LEFT PANEL */}

          <div className="bg-white/10 backdrop-blur-xl border border-white/10 rounded-3xl p-8 shadow-2xl">

            <h2 className="text-3xl font-bold mb-6">
              Upload Vehicle Image
            </h2>

            <div
              onDrop={handleDrop}
              onDragOver={handleDragOver}
              className="border-2 border-dashed border-blue-400 rounded-3xl p-14 flex flex-col items-center justify-center cursor-pointer hover:bg-white/5 transition"
            >

              <input
                type="file"
                id="fileUpload"
                className="hidden"
                onChange={(e) => {

                  const file = e.target.files[0];

                  if (!file) return;

                  setImage(file);

                  // LIVE HERO PREVIEW

                  setPreviewImage(
                    URL.createObjectURL(file)
                  );

                  // RESET OLD OUTPUTS

                  setBgRemovedImage(null);

                  setPlateRemovedImage(null);

                  setFinalImage(null);

                  setFinalPreview(null);

                }}
              />

              <label
                htmlFor="fileUpload"
                className="cursor-pointer text-center"
              >

                <div className="text-6xl mb-4">
                  🚘
                </div>

                <h3 className="text-2xl font-bold text-white">
                  Drag & Drop Vehicle Image
                </h3>

                <p className="text-slate-300 mt-4">
                  Upload · Paste · Screenshot · Web Images
                </p>

                <p className="text-blue-300 mt-3 text-sm">
                  JPG · PNG · WEBP
                </p>

                <p className="text-slate-400 mt-2 text-sm">
                  Ctrl + V supported
                </p>

              </label>

            </div>

            {image && (

              <div className="mt-8">

                <button
                  onClick={processCar}
                  disabled={loading}
                  className="w-full bg-gradient-to-r from-blue-600 to-cyan-500 hover:from-blue-500 hover:to-cyan-400 transition px-6 py-5 rounded-2xl font-bold text-lg shadow-xl"
                >

                  {loading
                    ? "⚡ Running RMBG-2.0 + YOLOS AI Pipeline..."
                    : "Generate Final Vehicle Result"}

                </button>

              </div>

            )}

          </div>

          {/* RIGHT PANEL */}

          <div className="space-y-8">

            {/* ORIGINAL */}

            {image && (

              <div className="bg-white/10 backdrop-blur-xl border border-white/10 rounded-3xl p-6 shadow-2xl">

                <h2 className="text-2xl font-bold mb-5 text-blue-300">
                  Original Vehicle
                </h2>

                <img
                  src={URL.createObjectURL(image)}
                  alt="original"
                  className="rounded-2xl shadow-xl"
                />

              </div>

            )}

            {/* BG REMOVED */}

            {bgRemovedImage && (

              <div className="bg-white/10 backdrop-blur-xl border border-white/10 rounded-3xl p-6 shadow-2xl">

                <h2 className="text-2xl font-bold mb-5 text-cyan-300">
                  Stage 1 — Background Removed
                </h2>

                <div className="bg-slate-300 rounded-2xl p-5">

                  <img
                    src={bgRemovedImage}
                    alt="background removed"
                    className="rounded-2xl shadow-xl"
                  />

                </div>

              </div>

            )}

            {/* PLATE REMOVED */}

            {plateRemovedImage && (

              <div className="bg-white/10 backdrop-blur-xl border border-white/10 rounded-3xl p-6 shadow-2xl">

                <h2 className="text-2xl font-bold mb-5 text-yellow-300">
                  Stage 2 — Number Plate Removed
                </h2>

                <div className="bg-slate-300 rounded-2xl p-5">

                  <img
                    src={plateRemovedImage}
                    alt="plate removed"
                    className="rounded-2xl shadow-xl"
                  />

                </div>

              </div>

            )}

            {/* FINAL */}

            {finalImage && (

              <div className="bg-white/10 backdrop-blur-xl border border-white/10 rounded-3xl p-6 shadow-2xl">

                <h2 className="text-2xl font-bold mb-5 text-green-300">
                  Stage 3 — Final AI Branded Result
                </h2>

                <div className="bg-slate-300 rounded-2xl p-5">

                  <img
                    src={finalImage}
                    alt="final vehicle"
                    className="rounded-2xl shadow-xl"
                  />

                </div>

                <a
                  href={finalImage}
                  download="autopivot-final-result.png"
                  className="block text-center bg-gradient-to-r from-green-600 to-emerald-500 hover:from-green-500 hover:to-emerald-400 transition px-6 py-5 rounded-2xl mt-6 font-bold text-lg shadow-xl"
                >
                  Download Final Vehicle Image
                </a>

              </div>

            )}

          </div>

        </div>

      </div>

    </div>

  );

}