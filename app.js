// Main JavaScript Logic for Image Background Removal Interface
// Developed by Vadim Rudoi

const BACKEND_URL = window.location.origin;

let currentFile = null;
const imageFileInput = document.getElementById('image-file-input');
const imageUploadZone = document.getElementById('image-upload-zone');
const removeBackgroundButton = document.getElementById('remove-background-button');
const progressContainer = document.getElementById('progress-container');
const progressStatusText = document.getElementById('progress-status-text');
const progressPercentage = document.getElementById('progress-percentage');
const progressIndicator = document.getElementById('progress-indicator');
const errorMessageBar = document.getElementById('error-message-bar');
const imageComparisonGrid = document.getElementById('image-comparison-grid');
const originalImagePreview = document.getElementById('original-image-preview');
const processedImagePreview = document.getElementById('processed-image-preview');
const processedImagePlaceholder = document.getElementById('processed-image-placeholder');
const processedStatusBadge = document.getElementById('processed-status-badge');
const downloadButton = document.getElementById('download-button');

imageFileInput.addEventListener('change', event => {
  const file = event.target.files[0];
  if (file) loadFile(file);
});

imageUploadZone.addEventListener('dragover', event => {
  event.preventDefault();
  imageUploadZone.classList.add('is-drag-active');
});

imageUploadZone.addEventListener('dragleave', () => {
  imageUploadZone.classList.remove('is-drag-active');
});

imageUploadZone.addEventListener('drop', event => {
  event.preventDefault();
  imageUploadZone.classList.remove('is-drag-active');
  const file = event.dataTransfer.files[0];
  if (file) loadFile(file);
});

removeBackgroundButton.addEventListener('click', processImage);

window.scrollToSection = function(id) {
  const el = document.getElementById(id);
  if (!el) return;
  window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - 80, behavior: 'smooth' });
};

function loadFile(file) {
  if (!file.type.startsWith('image/')) {
    return showErr('Please upload a JPG, PNG, or WEBP image.');
  }
  if (file.size > 10 * 1024 * 1024) {
    return showErr('File too large — max 10MB.');
  }

  currentFile = file;
  const reader = new FileReader();
  reader.onload = event => {
    const url = event.target.result;
    originalImagePreview.src = url;
    processedImagePreview.style.display = 'none';
    processedImagePlaceholder.style.display = 'block';
    processedStatusBadge.textContent = 'Awaiting';
    processedStatusBadge.className = 'status-badge';
    downloadButton.classList.remove('is-visible');
    imageComparisonGrid.classList.add('is-visible');
    removeBackgroundButton.disabled = false;
    progressContainer.classList.remove('is-visible');
    errorMessageBar.classList.remove('is-visible');
  };
  reader.readAsDataURL(file);
}

async function processImage() {
  if (!currentFile) return;
  if (!BACKEND_URL) {
    return showErr('Backend URL is not configured. Set BACKEND_URL in app.js.');
  }

  errorMessageBar.classList.remove('is-visible');
  setLoading(true);

  try {
    await processBackground();
  } catch (err) {
    showErr(err.message || 'Something went wrong. Please try again.');
  }

  setLoading(false);
}

async function processBackground() {
  setProgress(10, 'Uploading image to backend...');

  const form = new FormData();
  form.append('file', currentFile, currentFile.name);

  const response = await fetch(`${BACKEND_URL.replace(/\/$/, '')}/remove-background`, {
    method: 'POST',
    body: form
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`Server error ${response.status}: ${body}`);
  }

  setProgress(60, 'Waiting for server processing...');
  const json = await response.json();

  if (!json.success) {
    throw new Error(json.message || 'Backend did not return a processed image.');
  }

  setProgress(100, 'Done!');
  const dataUrl = `data:image/png;base64,${json.processed_image}`;
  processedImagePreview.src = dataUrl;
  processedImagePreview.style.display = 'block';
  processedImagePlaceholder.style.display = 'none';
  processedStatusBadge.textContent = '✓ Done';
  processedStatusBadge.className = 'status-badge is-complete';
  downloadButton.href = dataUrl;
  downloadButton.classList.add('is-visible');
}

function setLoading(on) {
  removeBackgroundButton.disabled = on || !currentFile;
  removeBackgroundButton.textContent = on ? 'Processing…' : 'Remove Background';
}

function setProgress(percent, label) {
  progressContainer.classList.add('is-visible');
  progressIndicator.style.width = percent + '%';
  progressStatusText.textContent = label;
  progressPercentage.textContent = percent + '%';
}

function showErr(message) {
  errorMessageBar.textContent = '⚠ ' + message;
  errorMessageBar.classList.add('is-visible');
}
