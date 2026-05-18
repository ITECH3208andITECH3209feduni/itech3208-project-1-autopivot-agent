"use client";

import { useState } from "react";
import UploadBox from "@/components/UploadBox";

export default function Home() {

  const [previewImage, setPreviewImage] = useState(null);

  const [finalPreview, setFinalPreview] = useState(null);

  return (

    <main className="min-h-screen bg-white text-[#0d1f3c] overflow-x-hidden">

      {/* NAVBAR */}

      <nav className="fixed top-0 left-0 right-0 z-50 bg-white/95 backdrop-blur-xl border-b border-gray-200 border-t-4 border-yellow-500 h-[70px] px-10 flex items-center justify-between">

        <div className="text-2xl font-black tracking-tight cursor-pointer">
          <span className="text-yellow-500">AUTO</span>PIVOT
        </div>

        <div className="hidden md:flex gap-10 text-sm text-gray-600 font-medium">

          <a href="#tool" className="hover:text-yellow-500 transition">
            Try it free
          </a>

          <a href="#features" className="hover:text-yellow-500 transition">
            Features
          </a>

        </div>

      </nav>

      {/* HERO */}

      <section className="pt-40 pb-24 px-8 lg:px-24 bg-gradient-to-br from-white to-slate-100">

        <div className="grid lg:grid-cols-2 gap-20 items-center">

          {/* LEFT */}

          <div>

            <div className="inline-block px-4 py-2 rounded-full bg-yellow-100 border border-yellow-300 text-xs font-bold tracking-widest uppercase text-yellow-700 mb-6">

              RMBG-2.0 + YOLOS AI

            </div>

            <h1 className="text-6xl lg:text-7xl font-black leading-tight tracking-tight">

              Vehicle imaging,
              <br />

              <span className="italic text-yellow-500">
                reimagined.
              </span>

            </h1>

            <p className="mt-8 text-lg text-slate-600 leading-relaxed max-w-xl">

              AI-powered automotive merchandising platform with
              background removal, number plate privacy protection,
              branding automation, and marketplace-ready exports.

            </p>

            <div className="flex gap-4 mt-10">

              <a
                href="#tool"
                className="bg-[#0d1f3c] hover:bg-[#162d58] transition text-white px-8 py-4 rounded-xl font-bold shadow-xl"
              >
                Try it free →
              </a>

              <a
                href="#features"
                className="border border-gray-300 hover:border-yellow-500 hover:bg-yellow-50 transition px-8 py-4 rounded-xl font-semibold"
              >
                Explore features
              </a>

            </div>

            {/* TECH BADGES */}

            <div className="flex gap-10 mt-12">

              <div>

                <div className="text-3xl font-black text-yellow-500">
                  ✂️
                </div>

                <p className="text-sm text-gray-500 mt-1">
                  RMBG-2.0
                </p>

              </div>

              <div>

                <div className="text-3xl font-black text-yellow-500">
                  🔒
                </div>

                <p className="text-sm text-gray-500 mt-1">
                  YOLOS AI
                </p>

              </div>

              <div>

                <div className="text-3xl font-black text-yellow-500">
                  ⚡
                </div>

                <p className="text-sm text-gray-500 mt-1">
                  Fast Export
                </p>

              </div>

            </div>

          </div>

          {/* HERO PREVIEW */}

          <div className="bg-white border border-gray-200 rounded-3xl shadow-2xl overflow-hidden">

            {/* TOP BAR */}

            <div className="bg-[#0d1f3c] px-6 py-4 flex items-center justify-between">

              <div className="flex gap-2">

                <div className="w-3 h-3 rounded-full bg-white/30"></div>
                <div className="w-3 h-3 rounded-full bg-white/30"></div>
                <div className="w-3 h-3 rounded-full bg-white/30"></div>

              </div>

              <span className="text-white font-bold text-sm">
                AI Result Preview
              </span>

              <div className="bg-yellow-500/20 border border-yellow-400/30 text-yellow-400 px-3 py-1 rounded-full text-xs font-bold">
                LIVE
              </div>

            </div>

            {/* IMAGE PREVIEW */}

            <div className="p-8 bg-slate-100 min-h-[420px] flex items-center justify-center">

              <div className="grid grid-cols-2 gap-6 w-full">

                {/* ORIGINAL */}

                <div className="bg-white rounded-2xl overflow-hidden shadow-lg">

                  <div className="px-4 py-3 bg-slate-100 border-b text-xs font-bold uppercase tracking-wider text-gray-500 text-center">
                    Original
                  </div>

                  <div className="h-72 bg-slate-200 flex items-center justify-center overflow-hidden p-4">

                    {previewImage ? (

                      <img
                        src={previewImage}
                        alt="original preview"
                        className="w-full h-full object-contain"
                      />

                    ) : (

                      <div className="text-slate-400 text-sm">
                        Upload image to preview
                      </div>

                    )}

                  </div>

                </div>

                {/* FINAL */}

                <div className="bg-white rounded-2xl overflow-hidden shadow-lg">

                  <div className="px-4 py-3 bg-slate-100 border-b text-xs font-bold uppercase tracking-wider text-gray-500 text-center">
                    Processed
                  </div>

                  <div className="h-72 bg-slate-200 flex items-center justify-center overflow-hidden p-4">

                    {finalPreview ? (

                      <img
                        src={finalPreview}
                        alt="processed preview"
                        className="w-full h-full object-contain"
                      />

                    ) : (

                      <div className="text-slate-400 text-sm">
                        AI result will appear here
                      </div>

                    )}

                  </div>

                </div>

              </div>

            </div>

          </div>

        </div>

      </section>

      {/* TOOL SECTION */}

      <section
        id="tool"
        className="py-24 px-6 lg:px-20 bg-gradient-to-b from-slate-100 to-white"
      >

        <div className="text-center mb-16">

          <p className="uppercase tracking-[4px] text-yellow-500 text-xs font-bold mb-4">
            AI Studio
          </p>

          <h2 className="text-5xl font-black">
            Process your vehicle photos
          </h2>

          <p className="text-gray-500 mt-5 text-lg">
            RMBG-2.0 + YOLOS + Logo Replacement
          </p>

        </div>

        <UploadBox
          setPreviewImage={setPreviewImage}
          setFinalPreview={setFinalPreview}
        />

      </section>

      {/* FEATURES */}

      <section
        id="features"
        className="py-24 px-6 lg:px-20 bg-gradient-to-b from-white to-slate-100"
      >

        <div className="text-center mb-16">

          <p className="uppercase tracking-[4px] text-yellow-500 text-xs font-bold mb-4">
            Features
          </p>

          <h2 className="text-5xl font-black">
            AI pipeline features
          </h2>

        </div>

        <div className="grid md:grid-cols-3 gap-8">

          {[
            ["✂️", "RMBG-2.0", "State-of-the-art AI background removal"],
            ["🔒", "YOLOS Detection", "Automatic Australian plate detection"],
            ["🎨", "Logo Branding", "AutoPivot branded replacements"],
            ["⚡", "Fast Processing", "GPU accelerated AI pipeline"],
            ["📦", "PNG Export", "Transparent marketplace-ready images"],
            ["🧠", "AI Workflow", "End-to-end automated processing"]
          ].map((item, index) => (

            <div
              key={index}
              className="bg-white border border-gray-200 rounded-3xl p-8 shadow-lg hover:shadow-2xl hover:-translate-y-2 transition"
            >

              <div className="text-5xl mb-6">
                {item[0]}
              </div>

              <h3 className="text-2xl font-bold mb-4">
                {item[1]}
              </h3>

              <p className="text-gray-500 leading-relaxed">
                {item[2]}
              </p>

            </div>

          ))}

        </div>

      </section>

      {/* FOOTER */}

      <footer className="bg-[#0d1f3c] text-white py-10 px-8 flex flex-col md:flex-row items-center justify-between">

        <div className="text-xl font-black">
          <span className="text-yellow-500">AUTO</span>PIVOT
        </div>

        <p className="text-sm text-white/40 mt-4 md:mt-0">
          RMBG-2.0 · YOLOS · © 2026 AutoPivot
        </p>

      </footer>

    </main>

  );

}