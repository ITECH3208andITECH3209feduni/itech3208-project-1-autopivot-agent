const BACKEND_URL = 'http://127.0.0.1:8000';

let currentFile = null;
let origURL = null;
let finalURL = null;
let baseFinalURL = null;
let plateDetections = [];
let plateOverlayURL = null;

window.goHome = function() {
  document.getElementById('home-page').classList.add('active');
  window.scrollTo({ top: 0, behavior: 'smooth' });
};

window.navTo = function(id) {
  const el = document.getElementById(id);
  if (!el) return;
  window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - 75, behavior: 'smooth' });
};

const zone = document.getElementById('uploadZone');
zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('drag'); });
zone.addEventListener('dragleave', () => zone.classList.remove('drag'));
zone.addEventListener('drop', e => {
  e.preventDefault();
  zone.classList.remove('drag');
  const f = e.dataTransfer.files[0];
  if (f) loadFile(f);
});

window.handleFile = function(e) {
  const f = e.target.files[0];
  if (f) loadFile(f);
};

function loadFile(f) {
  if (!f.type.startsWith('image/')) {
    showErr('Please upload a JPG, PNG, or WEBP image.', 'errBar');
    return;
  }
  if (f.size > 10 * 1024 * 1024) {
    showErr('File too large — max 10MB.', 'errBar');
    return;
  }

  currentFile = f;
  finalURL = null;
  baseFinalURL = null;
  plateOverlayURL = null;
  plateDetections = [];

  document.getElementById('errBar').classList.remove('show');
  document.getElementById('plateCanvasStatus').textContent = 'Process the vehicle first, then drop an image here to place it on the white plate area.';
  document.getElementById('plateDropBadge').textContent = 'Upload';
  document.getElementById('plateDropBadge').className = 'badge';
  document.getElementById('resetPlateBtn').style.display = 'none';

  const r = new FileReader();
  r.onload = e => {
    origURL = e.target.result;

    document.getElementById('heroOriginalPreview').innerHTML = `<img src="${origURL}" alt="Original" style="max-width:100%;max-height:180px;object-fit:contain;">`;
    document.getElementById('heroProcessedPreview').innerHTML = '<span class="result-placeholder">⏳</span>';
    document.getElementById('heroStatusTxt').textContent = 'Photo loaded — ready to process';

    document.getElementById('origImg').src = origURL;
    document.getElementById('comp').classList.add('show');

    const resultImg = document.getElementById('procImg');
    resultImg.src = '';
    resultImg.style.display = 'none';

    document.getElementById('procHint').style.display = 'inline';
    document.getElementById('procHint').textContent = 'Press process to remove background and hide plate';
    document.getElementById('procBadge').textContent = 'Awaiting';
    document.getElementById('procBadge').className = 'badge';
    document.getElementById('dlBtn1').style.display = 'none';

    resetProcBtn();
  };
  r.readAsDataURL(f);
}

function resetProcBtn() {
  document.getElementById('procBtn').disabled = !currentFile;
  document.getElementById('procLabel').textContent = currentFile ? 'Process Photo' : 'Upload an image first';
}

function setLoading(on) {
  document.getElementById('procBtn').disabled = on;
  document.getElementById('spin').style.display = on ? 'block' : 'none';
  document.getElementById('procLabel').textContent = on ? 'Processing…' : 'Process Photo';
}

function showErr(m, id) {
  const b = document.getElementById(id);
  b.textContent = '⚠ ' + m;
  b.classList.add('show');
}

window.processVehiclePhoto = async function() {
  if (!currentFile) return;

  document.getElementById('errBar').classList.remove('show');
  setLoading(true);

  try {
    document.getElementById('procBadge').textContent = 'Processing';
    document.getElementById('procBadge').className = 'badge working';
    document.getElementById('procHint').style.display = 'inline';
    document.getElementById('procHint').textContent = 'AI is processing…';

    setProgress(10, 'Uploading image…');

    const formData = new FormData();
    formData.append('file', currentFile);

    setProgress(35, 'Removing background…');

    const res = await fetch(`${BACKEND_URL}/process-vehicle`, {
      method: 'POST',
      body: formData
    });

    if (!res.ok) {
      const errorData = await res.json().catch(() => ({}));
      throw new Error(errorData.detail || `Backend error: ${res.status}`);
    }

    setProgress(70, 'Hiding number plate…');

    const data = await res.json();
    if (!data.success) {
      throw new Error(data.message || 'Processing failed');
    }

    setProgress(100, 'Done!');
    setTimeout(() => hideProgress(), 800);

    baseFinalURL = 'data:image/png;base64,' + data.processed_image;
    finalURL = baseFinalURL;
    plateDetections = data.detections || [];

    updateResultImages(finalURL);

    document.getElementById('procHint').style.display = 'none';
    document.getElementById('procBadge').textContent = '✓ Complete';
    document.getElementById('procBadge').className = 'badge done';

    const dl = document.getElementById('dlBtn1');
    dl.href = finalURL;
    dl.style.display = 'flex';

    if (plateDetections.length > 0) {
      document.getElementById('plateCanvasStatus').textContent =
        `Ready — ${plateDetections.length} plate area(s) detected. Drag and drop a plate image beside the final result.`;
      document.getElementById('plateDropBadge').textContent = 'Ready';
      document.getElementById('plateDropBadge').className = 'badge done';
    } else {
      document.getElementById('plateCanvasStatus').textContent =
        'No plate area was detected, so the drag-and-drop plate image option is not available for this image.';
      document.getElementById('plateDropBadge').textContent = 'No plate';
      document.getElementById('plateDropBadge').className = 'badge';
    }

    document.getElementById('heroStatusTxt').textContent =
      `Complete — background removed and ${data.plates_detected} plate(s) hidden`;
  } catch (e) {
    console.error('Vehicle processing error:', e);
    document.getElementById('procBadge').textContent = 'Error';
    document.getElementById('procBadge').className = 'badge';

    if (e.message.includes('fetch') || e.message.includes('Failed to fetch')) {
      showErr('❌ Cannot connect to backend. Make sure the Python server is running at: ' + BACKEND_URL, 'errBar');
    } else {
      showErr(e.message || 'Processing failed. Please try again.', 'errBar');
    }
  }

  setLoading(false);
};

window.handlePlateOverlay = function(e) {
  const f = e.target.files[0];
  if (!f) return;

  if (!f.type.startsWith('image/')) {
    showErr('Please upload an image for the plate area.', 'errBar');
    return;
  }

  if (!baseFinalURL || plateDetections.length === 0) {
    showErr('Please process a vehicle photo with a detected plate first.', 'errBar');
    return;
  }

  const r = new FileReader();
  r.onload = async event => {
    plateOverlayURL = event.target.result;
    await drawOverlayOnPlate();
  };
  r.readAsDataURL(f);
};

async function drawOverlayOnPlate() {
  try {
    const baseImg = await loadImage(baseFinalURL);
    const overlayImg = await loadImage(plateOverlayURL);

    const canvas = document.getElementById('canvas');
    const ctx = canvas.getContext('2d');

    canvas.width = baseImg.naturalWidth;
    canvas.height = baseImg.naturalHeight;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(baseImg, 0, 0);

    plateDetections.forEach(d => {
      const box = d.box;

      // Match the backend white rectangle padding.
      const pad = 5;
      const x = Math.max(0, Math.round(box.xmin) - pad);
      const y = Math.max(0, Math.round(box.ymin) - pad);
      const w = Math.min(canvas.width - x, Math.round(box.xmax - box.xmin) + pad * 2);
      const h = Math.min(canvas.height - y, Math.round(box.ymax - box.ymin) + pad * 2);

      // Keep a clean white plate canvas underneath.
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(x, y, w, h);

      // Draw the uploaded image inside the plate rectangle without stretching badly.
      const scale = Math.min(w / overlayImg.naturalWidth, h / overlayImg.naturalHeight);
      const drawW = overlayImg.naturalWidth * scale;
      const drawH = overlayImg.naturalHeight * scale;
      const drawX = x + (w - drawW) / 2;
      const drawY = y + (h - drawH) / 2;

      ctx.drawImage(overlayImg, drawX, drawY, drawW, drawH);
    });

    finalURL = canvas.toDataURL('image/png');
    updateResultImages(finalURL);

    const dl = document.getElementById('dlBtn1');
    dl.href = finalURL;
    dl.download = 'autopivot-final-custom-plate.png';

    document.getElementById('plateCanvasStatus').textContent =
      'Done — your uploaded image has been placed on the covered number plate area.';
    document.getElementById('plateDropBadge').textContent = 'Applied';
    document.getElementById('plateDropBadge').className = 'badge done';
    document.getElementById('resetPlateBtn').style.display = 'inline-flex';
    document.getElementById('heroStatusTxt').textContent =
      'Complete — custom image added to the hidden plate area';
  } catch (e) {
    console.error('Plate overlay error:', e);
    showErr('Could not place the uploaded image on the plate area. Please try another image.', 'errBar');
  }
}

window.resetPlateCanvas = function() {
  if (!baseFinalURL) return;

  finalURL = baseFinalURL;
  plateOverlayURL = null;

  updateResultImages(finalURL);

  const dl = document.getElementById('dlBtn1');
  dl.href = finalURL;
  dl.download = 'autopivot-final.png';

  const input = document.getElementById('plateOverlayIn');
  if (input) input.value = '';
  document.getElementById('plateDropBadge').textContent = 'Ready';
  document.getElementById('plateDropBadge').className = 'badge done';

  document.getElementById('plateCanvasStatus').textContent =
    'Reset complete — the result is back to the original white covered plate.';
  document.getElementById('heroStatusTxt').textContent =
    'Complete — background removed and plate hidden';
};

function updateResultImages(url) {
  const pi = document.getElementById('procImg');
  pi.src = url;
  pi.style.display = 'block';

  document.getElementById('heroProcessedPreview').innerHTML =
    `<img src="${url}" alt="Final result" style="max-width:100%;max-height:180px;object-fit:contain;">`;
}

function setProgress(pct, label) {
  document.getElementById('progressWrap').classList.add('show');
  document.getElementById('progressFill').style.width = pct + '%';
  document.getElementById('progressText').textContent = label;
  document.getElementById('progressPct').textContent = pct + '%';
}

function hideProgress() {
  document.getElementById('progressWrap').classList.remove('show');
}

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = reject;
    img.src = src;
  });
}


// Drag and drop support for the plate image box beside the final result
const plateDropZone = document.getElementById('plateDropZone');
if (plateDropZone) {
  ['dragenter', 'dragover'].forEach(eventName => {
    plateDropZone.addEventListener(eventName, e => {
      e.preventDefault();
      plateDropZone.classList.add('drag');
    });
  });

  ['dragleave', 'drop'].forEach(eventName => {
    plateDropZone.addEventListener(eventName, e => {
      e.preventDefault();
      plateDropZone.classList.remove('drag');
    });
  });

  plateDropZone.addEventListener('drop', e => {
    const f = e.dataTransfer.files[0];
    if (!f) return;
    handlePlateOverlay({ target: { files: [f] } });
  });
}
