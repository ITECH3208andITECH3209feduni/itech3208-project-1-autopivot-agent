const express = require("express");
const cors = require("cors");
const multer = require("multer");
const axios = require("axios");
const FormData = require("form-data");
const fs = require("fs");

const app = express();

app.use(cors());

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

    console.log("STEP 1: Request received");

    // ======================================
    // REMOVE BACKGROUND
    // ======================================

    const bgForm = new FormData();

    bgForm.append(
      "image",
      fs.createReadStream(req.file.path)
    );

    console.log("STEP 2: Removing background");

    const bgResponse = await axios.post(
      "http://127.0.0.1:8000/remove-bg",
      bgForm,
      {
        headers: bgForm.getHeaders(),
        responseType: "arraybuffer",
      }
    );

    // SAVE TEMP BACKGROUND-REMOVED IMAGE

    fs.writeFileSync(
      "outputs/temp-bg.png",
      bgResponse.data
    );

    console.log("STEP 3: Background removed");

    // ======================================
    // BLUR NUMBER PLATE
    // ======================================

    const plateForm = new FormData();

    plateForm.append(
      "image",
      fs.createReadStream("outputs/temp-bg.png")
    );

    console.log("STEP 4: Blurring number plate");

    const plateResponse = await axios.post(
      "http://127.0.0.1:9000/blur-plate",
      plateForm,
      {
        headers: plateForm.getHeaders(),
        responseType: "arraybuffer",
      }
    );

    // SAVE FINAL OUTPUT

    fs.writeFileSync(
      "outputs/final-output.png",
      plateResponse.data
    );

    console.log("STEP 5: Final image saved");

    // RETURN FINAL IMAGE TO FRONTEND

    res.set("Content-Type", "image/png");

    res.send(plateResponse.data);

  } catch (error) {

    console.log("PROCESSING ERROR:");
    console.log(error);

    res.status(500).json({
      error: "Car processing failed",
    });

  }

});


// ======================================
// START SERVER
// ======================================

app.listen(5000, () => {

  console.log("Server running on port 5000");

});