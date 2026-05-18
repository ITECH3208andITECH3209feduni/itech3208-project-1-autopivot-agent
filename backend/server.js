const express = require("express");
const cors = require("cors");
const multer = require("multer");
const axios = require("axios");
const FormData = require("form-data");
const fs = require("fs");
const path = require("path");

const app = express();

app.use(cors());

// ======================================
// CREATE OUTPUTS FOLDER IF NOT EXISTS
// ======================================

if (!fs.existsSync("outputs")) {

  fs.mkdirSync("outputs");

}

// ======================================
// EXPOSE OUTPUT IMAGES
// ======================================

app.use("/outputs", express.static("outputs"));

// ======================================
// MULTER SETUP
// ======================================

const upload = multer({
  dest: "uploads/",
});

// ======================================
// TEST ROUTE
// ======================================

app.get("/", (req, res) => {

  res.send("Backend Running");

});

// ======================================
// FINAL CAR PROCESSING ROUTE
// ======================================

app.post("/process-car", upload.single("image"), async (req, res) => {

  try {

    console.log("======================================");
    console.log("STEP 1: Request received");

    // ======================================
    // SAVE ORIGINAL PREVIEW
    // ======================================

    const originalBuffer = fs.readFileSync(req.file.path);

    fs.writeFileSync(
      "outputs/original-preview.png",
     originalBuffer
    );

    console.log("STEP 2: Original image saved");

    // ======================================
    // REMOVE BACKGROUND
    // ======================================

    const bgForm = new FormData();

    bgForm.append(
      "image",
      fs.createReadStream(req.file.path)
    );

    console.log("STEP 3: Sending image to RMBG AI");

    const bgResponse = await axios.post(
      "http://127.0.0.1:8000/remove-bg",
      bgForm,
      {
        headers: bgForm.getHeaders(),
        responseType: "arraybuffer",
        maxBodyLength: Infinity,
        maxContentLength: Infinity,
      }
    );

    // ======================================
    // SAVE BACKGROUND REMOVED OUTPUT
    // ======================================

    fs.writeFileSync(
      "outputs/background-output.png",
      bgResponse.data
    );

    console.log("STEP 4: Background removed image saved");

    // ======================================
    // SEND TO NUMBER PLATE AI
    // ======================================

    const plateForm = new FormData();

    plateForm.append(
      "image",
      fs.createReadStream(
        "outputs/background-output.png"
      )
    );

    console.log("STEP 5: Sending image to plate AI");

    const plateResponse = await axios.post(
      "http://127.0.0.1:9000/blur-plate",
      plateForm,
      {
        headers: plateForm.getHeaders(),
        responseType: "arraybuffer",
        maxBodyLength: Infinity,
        maxContentLength: Infinity,
      }
    );

    // ======================================
    // SAVE FINAL OUTPUT
    // ======================================

    fs.writeFileSync(
      "outputs/final-output.png",
      plateResponse.data
    );

    console.log("STEP 6: Final AI result saved");

    // ======================================
    // CLEAN TEMP FILE
    // ======================================

    fs.unlinkSync(req.file.path);

    console.log("STEP 7: Temp upload deleted");

    console.log("======================================");

    // ======================================
    // RETURN SUCCESS
    // ======================================

    res.json({
      success: true,
      message: "AI vehicle processing complete",
      original:
        "http://localhost:5000/outputs/original-preview.png",

      backgroundRemoved:
        "http://localhost:5000/outputs/background-output.png",

      final:
        "http://localhost:5000/outputs/final-output.png",
    });

  } catch (error) {

    console.log("======================================");
    console.log("PROCESSING ERROR:");

    if (error.response) {

      console.log(error.response.data);

    } else {

      console.log(error.message);

    }

    console.log("======================================");

    res.status(500).json({
      success: false,
      error: "Car processing failed",
    });

  }

});

// ======================================
// START SERVER
// ======================================

app.listen(5000, () => {

  console.log("======================================");
  console.log("AutoPivot Backend Running");
  console.log("Server running on port 5000");
  console.log("======================================");

});