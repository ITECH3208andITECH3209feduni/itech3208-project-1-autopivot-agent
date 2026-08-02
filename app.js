// Main JavaScript Logic for AutoPivot Full Pipeline Interface — multi-image version
// Developed by Vadim Rudoi, Akhanda Bhandari and Suraj Purella

const BACKEND_URL = window.location.origin;
const DEMO_IMAGE_URLS = ['/static/assets/demo-car.jpg', 'assets/demo-car.jpg'];
const FULL_PIPELINE_ENDPOINT = '/process-vehicle';
const IMPORT_URL_ENDPOINT = '/extract-images-from-url';
const MAX_FILES = 20;
const MAX_FILE_SIZE = 10 * 1024 * 1024;

// items: array of { id, file, originalUrl, status: 'idle'|'processing'|'done'|'error', processedDataUrl, statsHTML, errorMessage, cardEl, els }
let items = [];
let nextItemId = 1;
let isProcessing = false;
let isDemoStarting = false;
let isImportingUrl = false;

const imageFileInput = document.getElementById('image-file-input');
const imageUploadZone = document.getElementById('image-upload-zone');
const manualUploadButton = document.getElementById('manual-upload-button');
const demoNavLink = document.getElementById('demo-nav-link');
const tryDemoLink = document.getElementById('try-demo-link');
const processButton = document.getElementById('process-button');
const errorMessageBar = document.getElementById('error-message-bar');
const imageGallery = document.getElementById('image-gallery');
const galleryItemTemplate = document.getElementById('gallery-item-template');

const pipelineOptions = document.getElementById('pipeline-options');
const processingModeSelect = document.getElementById('processing-mode');
const bgUploadGroup = document.getElementById('bg-upload-group');
const plateUploadGroup = document.getElementById('plate-upload-group');
const bgFileInput = document.getElementById('bg-file-input');
const plateFileInput = document.getElementById('plate-file-input');
const resetBgButton = document.getElementById('reset-bg-button');
const resetPlateButton = document.getElementById('reset-plate-button');
const resetAllButton = document.getElementById('reset-all-button');
const addMoreButton = document.getElementById('add-more-button');

const batchSummaryRow = document.getElementById('batch-summary-row');
const batchSummaryText = document.getElementById('batch-summary-text');
const batchProgressText = document.getElementById('batch-progress-text');
const downloadAllButton = document.getElementById('download-all-button');

const pageUrlInput = document.getElementById('page-url-input');
const fetchUrlImagesButton = document.getElementById('fetch-url-images-button');
const urlImportStatus = document.getElementById('url-import-status');

processingModeSelect.addEventListener('change', e => {
  updateModeUploads(e.target.value);
  markAllPending();
});

manualUploadButton.addEventListener('click', () => {
  if (isProcessing) return;
  imageFileInput.click();
});

addMoreButton.addEventListener('click', () => {
  if (isProcessing) return;
  imageFileInput.click();
});

demoNavLink.addEventListener('click', event => {
  event.preventDefault();
  runDemo();
});

tryDemoLink.addEventListener('click', event => {
  event.preventDefault();
  runDemo();
});

imageFileInput.addEventListener('change', event => {
  const files = Array.from(event.target.files || []);
  if (files.length) {
    addFiles(files).catch(err => showErr(err.message || 'Could not load the selected images.'));
  }
  imageFileInput.value = '';
});

bgFileInput.addEventListener('change', () => {
  markAllPending();
  updateResetButtons();
});

plateFileInput.addEventListener('change', () => {
  markAllPending();
  updateResetButtons();
});

resetBgButton.addEventListener('click', () => {
  bgFileInput.value = '';
  markAllPending();
  updateResetButtons();
});

resetPlateButton.addEventListener('click', () => {
  plateFileInput.value = '';
  markAllPending();
  updateResetButtons();
});

resetAllButton.addEventListener('click', resetEverything);

fetchUrlImagesButton.addEventListener('click', importImagesFromUrl);
pageUrlInput.addEventListener('keydown', event => {
  if (event.key === 'Enter') {
    event.preventDefault();
    importImagesFromUrl();
  }
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
  const files = Array.from(event.dataTransfer.files || []);
  if (files.length) {
    addFiles(files).catch(err => showErr(err.message || 'Could not load the dropped images.'));
  }
});

processButton.addEventListener('click', processAllImages);

window.scrollToSection = function (id) {
  const el = document.getElementById(id);
  if (!el) return;
  window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - 80, behavior: 'smooth' });
};

// ---------- File loading ----------

async function addFiles(fileList) {
  errorMessageBar.classList.remove('is-visible');

  const room = MAX_FILES - items.length;
  if (room <= 0) {
    return showErr(`You can process up to ${MAX_FILES} images at a time.`);
  }
  const filesToAdd = fileList.slice(0, room);
  if (fileList.length > filesToAdd.length) {
    showErr(`Only the first ${filesToAdd.length} images were added (limit ${MAX_FILES}).`);
  }

  for (const file of filesToAdd) {
    if (!file.type.startsWith('image/')) {
      showErr(`Skipped "${file.name}" — not a supported image type.`);
      continue;
    }
    if (file.size > MAX_FILE_SIZE) {
      showErr(`Skipped "${file.name}" — file too large (max 10MB).`);
      continue;
    }

    const dataUrl = await readFileAsDataUrl(file);
    const item = {
      id: nextItemId++,
      file,
      originalUrl: dataUrl,
      status: 'idle',
      processedDataUrl: null,
      statsHTML: '',
      errorMessage: '',
    };
    items.push(item);
    renderGalleryItem(item);
  }

  pipelineOptions.style.display = items.length ? 'block' : 'none';
  imageGallery.classList.toggle('is-visible', items.length > 0);
  processButton.disabled = items.length === 0 || isProcessing;
  updateResetButtons();
  updateBatchSummary();
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = e => resolve(e.target.result);
    reader.onerror = () => reject(new Error(`Could not read "${file.name}".`));
    reader.readAsDataURL(file);
  });
}

// ---------- Import images from a page URL ----------

async function importImagesFromUrl() {
  if (isProcessing || isImportingUrl) return;

  const rawUrl = pageUrlInput.value.trim();
  if (!rawUrl) {
    setUrlImportStatus('Paste a page URL first.', true);
    return;
  }

  let parsedUrl;
  try {
    parsedUrl = new URL(rawUrl);
    if (!/^https?:$/.test(parsedUrl.protocol)) throw new Error('bad protocol');
  } catch {
    setUrlImportStatus('Enter a valid http:// or https:// URL.', true);
    return;
  }

  if (items.length >= MAX_FILES) {
    setUrlImportStatus(`You already have ${MAX_FILES} images loaded — remove some first.`, true);
    return;
  }

  isImportingUrl = true;
  fetchUrlImagesButton.disabled = true;
  fetchUrlImagesButton.textContent = 'Fetching…';
  setUrlImportStatus('Scanning page for images…', false);

  try {
    const response = await fetch(`${BACKEND_URL.replace(/\/$/, '')}${IMPORT_URL_ENDPOINT}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: parsedUrl.href }),
    });

    if (!response.ok) {
      const body = await response.text();
      throw new Error(`Server error ${response.status}: ${body}`);
    }

    const json = await response.json();
    if (!json.success) {
      throw new Error(json.message || 'Could not extract images from that page.');
    }

    const found = Array.isArray(json.images) ? json.images : [];
    if (!found.length) {
      setUrlImportStatus('No usable images were found on that page.', true);
      return;
    }

    const files = found
      .map((entry, index) => {
        try {
          return base64EntryToFile(entry, index);
        } catch {
          return null;
        }
      })
      .filter(Boolean);

    if (!files.length) {
      setUrlImportStatus('Found images, but none could be loaded.', true);
      return;
    }

    await addFiles(files);
    setUrlImportStatus(
      `Imported ${files.length} image${files.length === 1 ? '' : 's'} from the page.`,
      false
    );
    pageUrlInput.value = '';
  } catch (err) {
    setUrlImportStatus(err.message || 'Could not fetch images from that URL.', true);
  } finally {
    isImportingUrl = false;
    fetchUrlImagesButton.disabled = false;
    fetchUrlImagesButton.textContent = 'Fetch Images';
  }
}

function base64EntryToFile(entry, index) {
  const contentType = entry.content_type || entry.contentType || 'image/jpeg';
  const filename = entry.filename || entry.name || `url-image-${index + 1}.jpg`;
  const base64Data = entry.data || entry.base64 || '';
  if (!base64Data) throw new Error('missing image data');

  const byteChars = atob(base64Data);
  const byteNumbers = new Array(byteChars.length);
  for (let i = 0; i < byteChars.length; i++) {
    byteNumbers[i] = byteChars.charCodeAt(i);
  }
  const byteArray = new Uint8Array(byteNumbers);
  return new File([byteArray], filename, { type: contentType });
}

function setUrlImportStatus(message, isError) {
  urlImportStatus.textContent = message;
  urlImportStatus.classList.toggle('is-error', !!isError);
}

// ---------- Gallery rendering ----------

function renderGalleryItem(item) {
  const fragment = galleryItemTemplate.content.cloneNode(true);
  const card = fragment.querySelector('.gallery-item-card');
  card.dataset.itemId = String(item.id);

  card.querySelector('.gallery-item-name').textContent = item.file.name;
  card.querySelector('.original-image-preview').src = item.originalUrl;

  const removeBtn = card.querySelector('.gallery-item-remove');
  removeBtn.addEventListener('click', () => removeItem(item.id));

  imageGallery.appendChild(card);
  item.cardEl = card;

  // Grab every element we'll touch ONCE here and keep direct references.
  // (Re-querying by class later is fragile: status updates change class
  // names like "status-badge is-complete", which breaks any selector
  // built on those same classes.)
  item.els = {
    badge: card.querySelector('.processed-status-badge'),
    img: card.querySelector('.processed-image-preview'),
    placeholder: card.querySelector('.processed-image-placeholder'),
    statsEl: card.querySelector('.processing-stats'),
    progressWrap: card.querySelector('.gallery-item-progress'),
    progressBar: card.querySelector('.gallery-item-progress-bar'),
    errorEl: card.querySelector('.gallery-item-error'),
    downloadLink: card.querySelector('.gallery-item-download'),
    removeBtn,
  };
}

function removeItem(id) {
  if (isProcessing) return;
  const idx = items.findIndex(it => it.id === id);
  if (idx === -1) return;
  const item = items[idx];
  if (item.cardEl) item.cardEl.remove();
  items.splice(idx, 1);

  if (items.length === 0) {
    resetEverything();
    return;
  }

  pipelineOptions.style.display = 'block';
  imageGallery.classList.toggle('is-visible', items.length > 0);
  processButton.disabled = items.length === 0;
  updateResetButtons();
  updateBatchSummary();
  updateDownloadAllVisibility();
}

function markAllPending() {
  for (const item of items) {
    if (item.status === 'processing') continue;
    setItemStatus(item, 'idle');
  }
  updateDownloadAllVisibility();
}

function setItemStatus(item, status, extra = {}) {
  item.status = status;
  if (!item.cardEl || !item.els) return;

  const { badge, img, placeholder, statsEl, progressWrap, progressBar, errorEl, downloadLink } = item.els;

  if (status === 'idle') {
    badge.textContent = 'Awaiting';
    badge.className = 'status-badge processed-status-badge';
    img.style.display = 'none';
    img.src = '';
    placeholder.style.display = 'block';
    placeholder.textContent = 'Waiting to be processed.';
    statsEl.innerHTML = '';
    statsEl.style.display = 'none';
    progressWrap.classList.remove('is-visible');
    progressBar.style.width = '0%';
    errorEl.classList.remove('is-visible');
    errorEl.textContent = '';
    downloadLink.classList.remove('is-visible');
    downloadLink.removeAttribute('href');
  } else if (status === 'processing') {
    badge.textContent = 'Processing…';
    badge.className = 'status-badge';
    placeholder.style.display = 'block';
    placeholder.textContent = 'Processing…';
    img.style.display = 'none';
    errorEl.classList.remove('is-visible');
    progressWrap.classList.add('is-visible');
    progressBar.style.width = (extra.percent || 10) + '%';
  } else if (status === 'progress') {
    progressBar.style.width = (extra.percent || 0) + '%';
  } else if (status === 'done') {
    badge.textContent = '✓ Done';
    badge.className = 'status-badge is-complete';
    img.src = item.processedDataUrl;
    img.style.display = 'block';
    placeholder.style.display = 'none';
    statsEl.innerHTML = item.statsHTML;
    statsEl.style.display = item.statsHTML ? 'block' : 'none';
    progressWrap.classList.remove('is-visible');
    progressBar.style.width = '100%';
    downloadLink.href = item.processedDataUrl;
    downloadLink.setAttribute('download', buildDownloadName(item.file.name));
    downloadLink.classList.add('is-visible');
  } else if (status === 'error') {
    badge.textContent = 'Failed';
    badge.className = 'status-badge';
    placeholder.style.display = 'block';
    placeholder.textContent = 'Processing failed.';
    img.style.display = 'none';
    progressWrap.classList.remove('is-visible');
    errorEl.textContent = '⚠ ' + (item.errorMessage || 'Something went wrong.');
    errorEl.classList.add('is-visible');
    downloadLink.classList.remove('is-visible');
  }
}

function buildDownloadName(originalName) {
  const dot = originalName.lastIndexOf('.');
  const base = dot > -1 ? originalName.slice(0, dot) : originalName;
  return `${base}-autopivot.png`;
}

// ---------- Demo ----------

async function runDemo() {
  if (isProcessing || isDemoStarting) return;

  isDemoStarting = true;
  window.scrollToSection('demo-section');
  resetEverything();
  setDemoControlsDisabled(true);

  try {
    const blob = await fetchDemoImageBlob();
    const demoFile = new File([blob], 'demo-car.jpg', { type: blob.type || 'image/jpeg' });

    processingModeSelect.value = FULL_PIPELINE_ENDPOINT;
    updateModeUploads(FULL_PIPELINE_ENDPOINT);
    await addFiles([demoFile]);
    await processAllImages();
  } catch (err) {
    showErr(err.message || 'Could not start the demo. Please try uploading photos manually.');
  } finally {
    isDemoStarting = false;
    setDemoControlsDisabled(false);
  }
}

window.runDemo = runDemo;

async function fetchDemoImageBlob() {
  let lastError = null;
  for (const url of DEMO_IMAGE_URLS) {
    try {
      const response = await fetch(url);
      if (response.ok) return response.blob();
      lastError = new Error(`Demo image could not be loaded from ${url} (${response.status}).`);
    } catch (err) {
      lastError = err;
    }
  }
  throw lastError || new Error('Demo image could not be loaded.');
}

// ---------- Reset ----------

function resetEverything() {
  items = [];
  imageGallery.innerHTML = '';
  imageGallery.classList.remove('is-visible');
  bgFileInput.value = '';
  plateFileInput.value = '';
  pageUrlInput.value = '';
  setUrlImportStatus('', false);
  processingModeSelect.value = FULL_PIPELINE_ENDPOINT;
  updateModeUploads(FULL_PIPELINE_ENDPOINT);
  pipelineOptions.style.display = 'none';
  processButton.disabled = true;
  errorMessageBar.classList.remove('is-visible');
  batchSummaryRow.style.display = 'none';
  downloadAllButton.style.display = 'none';
  updateResetButtons();
}

// ---------- Processing ----------

async function processAllImages() {
  const pending = items.filter(it => it.status !== 'done');
  if (!pending.length) return;
  if (!BACKEND_URL) {
    return showErr('Backend URL is not configured. Set BACKEND_URL in app.js.');
  }

  errorMessageBar.classList.remove('is-visible');
  setLoading(true);

  let completed = 0;
  updateBatchSummary(completed, pending.length);

  for (const item of pending) {
    setItemStatus(item, 'processing', { percent: 15 });
    try {
      await processSingleImage(item);
      setItemStatus(item, 'done');
    } catch (err) {
      item.errorMessage = err.message || 'Something went wrong.';
      setItemStatus(item, 'error');
    }
    completed += 1;
    updateBatchSummary(completed, pending.length);
  }

  setLoading(false);
  updateDownloadAllVisibility();
}

async function processSingleImage(item) {
  const endpoint = processingModeSelect.value;
  const form = new FormData();
  form.append('file', item.file, item.file.name);

  if (endpoint === '/process-vehicle' || endpoint === '/detect-and-hide') {
    if (plateFileInput.files[0]) {
      form.append('plate_overlay', plateFileInput.files[0], plateFileInput.files[0].name);
    }
  }
  if (endpoint === '/process-vehicle') {
    if (bgFileInput.files[0]) {
      form.append('background', bgFileInput.files[0], bgFileInput.files[0].name);
    }
  }

  setItemStatus(item, 'progress', { percent: 40 });

  const response = await fetch(`${BACKEND_URL.replace(/\/$/, '')}${endpoint}`, {
    method: 'POST',
    body: form,
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`Server error ${response.status}: ${body}`);
  }

  setItemStatus(item, 'progress', { percent: 80 });
  const json = await response.json();

  if (!json.success) {
    throw new Error(json.message || 'Backend failed to process this image.');
  }

  item.processedDataUrl = `data:image/png;base64,${json.processed_image}`;
  item.statsHTML = buildStatsHTML(json, endpoint);
}

function buildStatsHTML(json, endpoint) {
  let statsHTML = '';
  if (endpoint === '/process-vehicle') {
    statsHTML += `<div class="stats-row"><span>Vehicle:</span> <strong>${json.vehicle.class} (${(json.vehicle.score * 100).toFixed(1)}%)</strong></div>`;
    statsHTML += `<div class="stats-row"><span>Plates Detected:</span> <strong>${json.plates_detected} (${json.plate_treatment})</strong></div>`;
    statsHTML += `<div class="stats-row"><span>AI BG Model:</span> <strong>${json.bg_model_used.split('/')[1]}</strong></div>`;
  } else if (endpoint === '/remove-background') {
    statsHTML += `<div class="stats-row"><span>AI BG Model:</span> <strong>${json.bg_model_used.split('/')[1]}</strong></div>`;
  } else if (endpoint === '/detect-and-hide') {
    statsHTML += `<div class="stats-row"><span>Plates Detected:</span> <strong>${json.plates_detected} (${json.plate_treatment})</strong></div>`;
  }
  return statsHTML;
}

// ---------- UI state helpers ----------

function setLoading(on) {
  isProcessing = on;
  processButton.disabled = on || items.every(it => it.status === 'done');
  processButton.textContent = on ? 'Processing…' : 'Process All Images';
  processingModeSelect.disabled = on;
  bgFileInput.disabled = on;
  plateFileInput.disabled = on;
  addMoreButton.disabled = on;
  fetchUrlImagesButton.disabled = on || isImportingUrl;
  pageUrlInput.disabled = on;
  setDemoControlsDisabled(on);
  updateResetButtons(on);
}

function setDemoControlsDisabled(on) {
  manualUploadButton.disabled = on;
  demoNavLink.classList.toggle('is-disabled', on);
  demoNavLink.setAttribute('aria-disabled', String(on));
  tryDemoLink.classList.toggle('is-disabled', on);
  tryDemoLink.setAttribute('aria-disabled', String(on));
}

function updateModeUploads(mode) {
  if (mode === FULL_PIPELINE_ENDPOINT) {
    bgUploadGroup.style.display = 'block';
    plateUploadGroup.style.display = 'block';
  } else if (mode === '/remove-background') {
    bgUploadGroup.style.display = 'none';
    plateUploadGroup.style.display = 'none';
  } else if (mode === '/detect-and-hide') {
    bgUploadGroup.style.display = 'none';
    plateUploadGroup.style.display = 'block';
  }
}

function updateResetButtons(isLoading = false) {
  resetBgButton.disabled = isLoading || !bgFileInput.files.length;
  resetPlateButton.disabled = isLoading || !plateFileInput.files.length;
  resetAllButton.disabled = isLoading || items.length === 0;
  document.querySelectorAll('.gallery-item-remove').forEach(btn => {
    btn.disabled = isLoading;
  });
}

function updateBatchSummary(completed, total) {
  if (!items.length) {
    batchSummaryRow.style.display = 'none';
    return;
  }
  batchSummaryRow.style.display = 'flex';
  batchSummaryText.textContent = `${items.length} image${items.length === 1 ? '' : 's'} loaded`;
  if (typeof completed === 'number' && typeof total === 'number' && total > 0) {
    batchProgressText.textContent = `Processing ${completed}/${total}…`;
  } else {
    const done = items.filter(it => it.status === 'done').length;
    batchProgressText.textContent = done ? `${done}/${items.length} processed` : '';
  }
}

function updateDownloadAllVisibility() {
  const doneItems = items.filter(it => it.status === 'done' && it.processedDataUrl);
  if (doneItems.length > 1) {
    downloadAllButton.style.display = 'inline-block';
    downloadAllButton.onclick = e => {
      e.preventDefault();
      downloadAllProcessed(doneItems);
    };
  } else {
    downloadAllButton.style.display = 'none';
    downloadAllButton.onclick = null;
  }
}

function downloadAllProcessed(doneItems) {
  // Triggers sequential downloads (no zip dependency available client-side).
  doneItems.forEach((item, i) => {
    setTimeout(() => {
      const link = document.createElement('a');
      link.href = item.processedDataUrl;
      link.download = buildDownloadName(item.file.name);
      document.body.appendChild(link);
      link.click();
      link.remove();
    }, i * 300);
  });
}

function showErr(message) {
  errorMessageBar.textContent = '⚠ ' + message;
  errorMessageBar.classList.add('is-visible');
}