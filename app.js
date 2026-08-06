// Main JavaScript Logic for AutoPivot Full Pipeline Interface
// Developed by Vadim Rudoi, Akhanda Bhandari and Suraj Purella

const API_META = document.querySelector('meta[name="autopivot-api-url"]');
const BACKEND_URL = (window.AUTO_PIVOT_API_URL || API_META?.content || window.location.origin).replace(/\/$/, '');
const USE_VERSIONED_API = Boolean(window.AUTO_PIVOT_API_URL || API_META?.content);
const API_PREFIX = window.AUTO_PIVOT_API_PREFIX ?? (USE_VERSIONED_API ? '/api/v1' : '');
const DEMO_IMAGE_URLS = USE_VERSIONED_API
  ? [`${BACKEND_URL}/static/assets/demo-car.jpg`, 'assets/demo-car.jpg']
  : ['/static/assets/demo-car.jpg', 'assets/demo-car.jpg'];
const FULL_PIPELINE_ENDPOINT = '/process-vehicle';
const MAX_UPLOAD_MB = 20;

let currentFile = null;
let isProcessing = false;
let isDemoStarting = false;
const imageFileInput = document.getElementById('image-file-input');
const imageUploadZone = document.getElementById('image-upload-zone');
const manualUploadButton = document.getElementById('manual-upload-button');
const demoNavLink = document.getElementById('demo-nav-link');
const tryDemoLink = document.getElementById('try-demo-link');
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
const resetCarButton = document.getElementById('reset-car-button');
const resetBgButton = document.getElementById('reset-bg-button');
const resetPlateButton = document.getElementById('reset-plate-button');
const resetAllButton = document.getElementById('reset-all-button');

// Toggle visible options based on selected mode
processingModeSelect.addEventListener('change', (e) => 
{
  updateModeUploads(e.target.value);
});

manualUploadButton.addEventListener('click', () => 
{
  if (isProcessing) return;
  imageFileInput.click();
});

demoNavLink.addEventListener('click', event => 
{
  event.preventDefault();
  runDemo();
});

tryDemoLink.addEventListener('click', event => 
{
  event.preventDefault();
  runDemo();
});

imageFileInput.addEventListener('change', event => 
{
  const file = event.target.files[0];
  if (file) 
  {
    loadFile(file).catch(err => showErr(err.message || 'Could not load the selected image.'));
  }
});

bgFileInput.addEventListener('change', () => 
{
  resetProcessedResult();
  updateResetButtons();
});

plateFileInput.addEventListener('change', () => 
{
  resetProcessedResult();
  updateResetButtons();
});

resetCarButton.addEventListener('click', resetCarUpload);
resetBgButton.addEventListener('click', resetBackgroundUpload);
resetPlateButton.addEventListener('click', resetPlateUpload);
resetAllButton.addEventListener('click', resetEverything);

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
  if (file) 
  {
    loadFile(file).catch(err => showErr(err.message || 'Could not load the dropped image.'));
  }
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
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024) 
  {
    return showErr(`File too large — max ${MAX_UPLOAD_MB}MB.`);
  }

  currentFile = file;
  return new Promise((resolve, reject) => 
  {
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
      updateResetButtons();
      resolve();
    };
    reader.onerror = () => reject(new Error('Could not read the selected image.'));
    reader.readAsDataURL(file);
  });
}

async function runDemo() 
{
  if (isProcessing || isDemoStarting) return;

  isDemoStarting = true;
  window.scrollToSection('demo-section');
  resetEverything();
  setDemoControlsDisabled(true);

  try 
  {
    setProgress(5, 'Loading demo image...');
    const blob = await fetchDemoImageBlob();
    const demoFile = new File([blob], 'demo-car.jpg', { type: blob.type || 'image/jpeg' });

    processingModeSelect.value = FULL_PIPELINE_ENDPOINT;
    updateModeUploads(FULL_PIPELINE_ENDPOINT);
    await loadFile(demoFile);
    await processImage();
  } 
  catch (err) 
  {
    showErr(err.message || 'Could not start the demo. Please try uploading a photo manually.');
  } 
  finally 
  {
    isDemoStarting = false;
    setDemoControlsDisabled(false);
  }
}

window.runDemo = runDemo;

async function fetchDemoImageBlob() 
{
  let lastError = null;

  for (const url of DEMO_IMAGE_URLS) 
  {
    try 
    {
      const response = await fetch(url);
      if (response.ok) 
      {
        return response.blob();
      }
      lastError = new Error(`Demo image could not be loaded from ${url} (${response.status}).`);
    } 
    catch (err) 
    {
      lastError = err;
    }
  }

  throw lastError || new Error('Demo image could not be loaded.');
}

function resetCarUpload() 
{
  currentFile = null;
  imageFileInput.value = '';
  originalImagePreview.src = '';
  processedImagePreview.src = '';
  processedImagePreview.style.display = 'none';
  processedImagePlaceholder.style.display = 'block';
  processedStatusBadge.textContent = 'Awaiting';
  processedStatusBadge.className = 'status-badge';
  downloadButton.removeAttribute('href');
  downloadButton.classList.remove('is-visible');
  imageComparisonGrid.classList.remove('is-visible');
  pipelineOptions.style.display = 'none';
  processingStats.innerHTML = '';
  processingStats.style.display = 'none';
  progressContainer.classList.remove('is-visible');
  progressIndicator.style.width = '0%';
  progressStatusText.textContent = 'Waiting for image…';
  progressPercentage.textContent = '0%';
  errorMessageBar.classList.remove('is-visible');
  processButton.disabled = true;
  updateResetButtons();
}

function resetBackgroundUpload() 
{
  bgFileInput.value = '';
  resetProcessedResult();
  updateResetButtons();
}

function resetPlateUpload() 
{
  plateFileInput.value = '';
  resetProcessedResult();
  updateResetButtons();
}

function resetEverything() 
{
  currentFile = null;
  imageFileInput.value = '';
  bgFileInput.value = '';
  plateFileInput.value = '';
  originalImagePreview.src = '';
  processingModeSelect.value = FULL_PIPELINE_ENDPOINT;
  updateModeUploads(FULL_PIPELINE_ENDPOINT);
  imageComparisonGrid.classList.remove('is-visible');
  pipelineOptions.style.display = 'none';
  processButton.disabled = true;
  resetProcessedResult();
  updateResetButtons();
}

function resetProcessedResult() 
{
  processedImagePreview.src = '';
  processedImagePreview.style.display = 'none';
  processedImagePlaceholder.style.display = 'block';
  processedStatusBadge.textContent = 'Awaiting';
  processedStatusBadge.className = 'status-badge';
  downloadButton.removeAttribute('href');
  downloadButton.classList.remove('is-visible');
  processingStats.innerHTML = '';
  processingStats.style.display = 'none';
  progressContainer.classList.remove('is-visible');
  progressIndicator.style.width = '0%';
  progressStatusText.textContent = 'Waiting for image…';
  progressPercentage.textContent = '0%';
  errorMessageBar.classList.remove('is-visible');
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
  if (endpoint === '/process-vehicle' || endpoint === '/remove-background') 
  {
    if (bgFileInput.files[0]) 
    {
      form.append('background', bgFileInput.files[0], bgFileInput.files[0].name);
    }
  }

  setProgress(30, 'Uploading & Server Processing...');

  const response = await fetch(`${BACKEND_URL}${API_PREFIX}${endpoint}`, 
  {
    method: 'POST',
    body: form
  });

  let json = null;
  try
  {
    json = await response.json();
  }
  catch
  {
    json = null;
  }

  if (!response.ok) 
  {
    const message = json?.error?.message || json?.message || `Server error ${response.status}.`;
    throw new Error(message);
  }

  setProgress(80, 'Rendering results...');

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
  isProcessing = on;
  processButton.disabled = on || !currentFile;
  processButton.textContent = on ? 'Processing…' : 'Process Image';
  processingModeSelect.disabled = on;
  bgFileInput.disabled = on;
  plateFileInput.disabled = on;
  setDemoControlsDisabled(on);
  updateResetButtons(on);
}

function setDemoControlsDisabled(on) 
{
  manualUploadButton.disabled = on;
  demoNavLink.classList.toggle('is-disabled', on);
  demoNavLink.setAttribute('aria-disabled', String(on));
  tryDemoLink.classList.toggle('is-disabled', on);
  tryDemoLink.setAttribute('aria-disabled', String(on));
}

function updateModeUploads(mode) 
{
  if (mode === FULL_PIPELINE_ENDPOINT) 
  {
    bgUploadGroup.style.display = 'block';
    plateUploadGroup.style.display = 'block';
  } 
  else if (mode === '/remove-background') 
  {
    bgUploadGroup.style.display = 'block';
    plateUploadGroup.style.display = 'none';
  } 
  else if (mode === '/detect-and-hide') 
  {
    bgUploadGroup.style.display = 'none';
    plateUploadGroup.style.display = 'block';
  }
}

function updateResetButtons(isLoading = false) 
{
  resetCarButton.disabled = isLoading || !currentFile;
  resetBgButton.disabled = isLoading || !bgFileInput.files.length;
  resetPlateButton.disabled = isLoading || !plateFileInput.files.length;
  resetAllButton.disabled = isLoading || (!currentFile && !bgFileInput.files.length && !plateFileInput.files.length);
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
