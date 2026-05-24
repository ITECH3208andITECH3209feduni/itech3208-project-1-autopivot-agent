// Main JavaScript Logic for AutoPivot Full Pipeline Interface
// Developed by Vadim Rudoi, Akhanda Bhandari and Suraj Purella

const BACKEND_URL = window.location.origin;

let currentFile = null;
const imageFileInput = document.getElementById('image-file-input');
const imageUploadZone = document.getElementById('image-upload-zone');
const processButton = document.getElementById('process-button');
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
const processingStats = document.getElementById('processing-stats');

// New UI Elements
const pipelineOptions = document.getElementById('pipeline-options');
const processingModeSelect = document.getElementById('processing-mode');
const bgUploadGroup = document.getElementById('bg-upload-group');
const plateUploadGroup = document.getElementById('plate-upload-group');
const bgFileInput = document.getElementById('bg-file-input');
const plateFileInput = document.getElementById('plate-file-input');

// Toggle visible options based on selected mode
processingModeSelect.addEventListener('change', (e) => 
{
  const mode = e.target.value;
  if (mode === '/process-vehicle') 
  {
    bgUploadGroup.style.display = 'block';
    plateUploadGroup.style.display = 'block';
  } 
  else if (mode === '/remove-background') 
  {
    bgUploadGroup.style.display = 'none';
    plateUploadGroup.style.display = 'none';
  } 
  else if (mode === '/detect-and-hide') 
  {
    bgUploadGroup.style.display = 'none';
    plateUploadGroup.style.display = 'block';
  }
});

imageFileInput.addEventListener('change', event => 
{
  const file = event.target.files[0];
  if (file) loadFile(file);
});

imageUploadZone.addEventListener('dragover', event => 
{
  event.preventDefault();
  imageUploadZone.classList.add('is-drag-active');
});

imageUploadZone.addEventListener('dragleave', () => 
{
  imageUploadZone.classList.remove('is-drag-active');
});

imageUploadZone.addEventListener('drop', event => 
{
  event.preventDefault();
  imageUploadZone.classList.remove('is-drag-active');
  const file = event.dataTransfer.files[0];
  if (file) loadFile(file);
});

processButton.addEventListener('click', processImage);

window.scrollToSection = function(id) 
{
  const el = document.getElementById(id);
  if (!el) return;
  window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - 80, behavior: 'smooth' });
};

function loadFile(file) 
{
  if (!file.type.startsWith('image/')) 
  {
    return showErr('Please upload a JPG, PNG, or WEBP image.');
  }
  if (file.size > 10 * 1024 * 1024) 
  {
    return showErr('File too large — max 10MB.');
  }

  currentFile = file;
  const reader = new FileReader();
  reader.onload = event => 
  {
    const url = event.target.result;
    originalImagePreview.src = url;
    processedImagePreview.style.display = 'none';
    processedImagePlaceholder.style.display = 'block';
    processedStatusBadge.textContent = 'Awaiting';
    processedStatusBadge.className = 'status-badge';
    downloadButton.classList.remove('is-visible');
    imageComparisonGrid.classList.add('is-visible');
    pipelineOptions.style.display = 'block'; // Show options once image is loaded
    processingStats.style.display = 'none';
    processButton.disabled = false;
    progressContainer.classList.remove('is-visible');
    errorMessageBar.classList.remove('is-visible');
  };
  reader.readAsDataURL(file);
}

async function processImage() 
{
  if (!currentFile) return;
  if (!BACKEND_URL) 
  {
    return showErr('Backend URL is not configured. Set BACKEND_URL in app.js.');
  }

  errorMessageBar.classList.remove('is-visible');
  setLoading(true);

  try 
  {
    await executePipeline();
  } 
  catch (err) 
  {
    showErr(err.message || 'Something went wrong. Please try again.');
  }

  setLoading(false);
}

async function executePipeline() 
{
  setProgress(10, 'Preparing assets...');

  const endpoint = processingModeSelect.value;
  const form = new FormData();
  form.append('file', currentFile, currentFile.name);

  // Append optional files based on mode
  if (endpoint === '/process-vehicle' || endpoint === '/detect-and-hide') 
  {
    if (plateFileInput.files[0]) 
    {
      form.append('plate_overlay', plateFileInput.files[0], plateFileInput.files[0].name);
    }
  }
  if (endpoint === '/process-vehicle') 
  {
    if (bgFileInput.files[0]) 
    {
      form.append('background', bgFileInput.files[0], bgFileInput.files[0].name);
    }
  }

  setProgress(30, 'Uploading & Server Processing...');

  const response = await fetch(`${BACKEND_URL.replace(/\/$/, '')}${endpoint}`, 
  {
    method: 'POST',
    body: form
  });

  if (!response.ok) 
  {
    const body = await response.text();
    throw new Error(`Server error ${response.status}: ${body}`);
  }

  setProgress(80, 'Rendering results...');
  const json = await response.json();

  if (!json.success) 
  {
    throw new Error(json.message || 'Backend failed to process the image.');
  }

  setProgress(100, 'Done!');
  
  // Render Image
  const dataUrl = `data:image/png;base64,${json.processed_image}`;
  processedImagePreview.src = dataUrl;
  processedImagePreview.style.display = 'block';
  processedImagePlaceholder.style.display = 'none';
  processedStatusBadge.textContent = '✓ Done';
  processedStatusBadge.className = 'status-badge is-complete';
  downloadButton.href = dataUrl;
  downloadButton.classList.add('is-visible');

  // Render Stats from Backend
  renderStats(json, endpoint);
}

function renderStats(json, endpoint) 
{
  processingStats.innerHTML = '';
  let statsHTML = '';

  if (endpoint === '/process-vehicle') 
  {
    statsHTML += `<div class="stats-row"><span>Vehicle:</span> <strong>${json.vehicle.class} (${(json.vehicle.score * 100).toFixed(1)}%)</strong></div>`;
    statsHTML += `<div class="stats-row"><span>Plates Detected:</span> <strong>${json.plates_detected} (${json.plate_treatment})</strong></div>`;
    statsHTML += `<div class="stats-row"><span>AI BG Model:</span> <strong>${json.bg_model_used.split('/')[1]}</strong></div>`;
  } 
  else if (endpoint === '/remove-background') 
  {
    statsHTML += `<div class="stats-row"><span>AI BG Model:</span> <strong>${json.bg_model_used.split('/')[1]}</strong></div>`;
  } 
  else if (endpoint === '/detect-and-hide') 
  {
    statsHTML += `<div class="stats-row"><span>Plates Detected:</span> <strong>${json.plates_detected} (${json.plate_treatment})</strong></div>`;
  }

  processingStats.innerHTML = statsHTML;
  processingStats.style.display = 'block';
}

function setLoading(on) 
{
  processButton.disabled = on || !currentFile;
  processButton.textContent = on ? 'Processing…' : 'Process Image';
  processingModeSelect.disabled = on;
  bgFileInput.disabled = on;
  plateFileInput.disabled = on;
}

function setProgress(percent, label) 
{
  progressContainer.classList.add('is-visible');
  progressIndicator.style.width = percent + '%';
  progressStatusText.textContent = label;
  progressPercentage.textContent = percent + '%';
}

function showErr(message) 
{
  errorMessageBar.textContent = '⚠ ' + message;
  errorMessageBar.classList.add('is-visible');
}