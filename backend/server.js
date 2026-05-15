const express = require("express");
const cors = require("cors");
const multer = require("multer");
const axios = require("axios");
const FormData = require("form-data");
const fs = require("fs");

const app = express();

app.use(cors());

// ======================================
// EXPOSE OUTPUT IMAGES
// ======================================

app.use("/outputs", express.static("outputs"));

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

    // ======================================
    // SAVE BACKGROUND REMOVED OUTPUT
    // ======================================

    fs.writeFileSync(
      "outputs/background-output.png",
      bgResponse.data
    );

    console.log("STEP 3: Background removed image saved");

    // ======================================
    // SEND IMAGE TO NUMBER PLATE AI
    // ======================================

    const plateForm = new FormData();

    plateForm.append(
      "image",
      fs.createReadStream("outputs/background-output.png")
    );

    console.log("STEP 4: Processing number plate");

    const plateResponse = await axios.post(
      "http://127.0.0.1:9000/blur-plate",
      plateForm,
      {
        headers: plateForm.getHeaders(),
        responseType: "arraybuffer",
      }
    );

    // ======================================
    // SAVE FINAL OUTPUT
    // ======================================

    fs.writeFileSync(
      "outputs/final-output.png",
      plateResponse.data
    );

    console.log("STEP 5: Final image saved");

    // ======================================
    // RETURN SUCCESS
    // ======================================

    res.json({
      message: "Processing complete",
    });

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