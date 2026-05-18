const BACKEND_URL = 'http://127.0.0.1:8000';

let currentFile = null;
const fileInput = document.getElementById('fileIn');
const uploadZone = document.getElementById('uploadZone');
const procBtn = document.getElementById('procBtn');
const progWrap = document.getElementById('progressWrap');
const progText = document.getElementById('progressText');
const progPct = document.getElementById('progressPct');
const progFill = document.getElementById('progressFill');
const errBar = document.getElementById('errBar');
const comp = document.getElementById('comp');
const origImg = document.getElementById('origImg');
const procImg = document.getElementById('procImg');
const procHint = document.getElementById('procHint');
const procBadge = document.getElementById('procBadge');
const dlBtn = document.getElementById('dlBtn');

fileInput.addEventListener('change', event => {
  const file = event.target.files[0];
  if (file) loadFile(file);
});

uploadZone.addEventListener('dragover', event => {
  event.preventDefault();
  uploadZone.classList.add('drag');
});

uploadZone.addEventListener('dragleave', () => {
  uploadZone.classList.remove('drag');
});

uploadZone.addEventListener('drop', event => {
  event.preventDefault();
  uploadZone.classList.remove('drag');
  const file = event.dataTransfer.files[0];
  if (file) loadFile(file);
});

procBtn.addEventListener('click', processImage);

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
    origImg.src = url;
    procImg.style.display = 'none';
    procHint.style.display = 'block';
    procBadge.textContent = 'Awaiting';
    procBadge.className = 'badge';
    dlBtn.classList.remove('show');
    comp.classList.add('show');
    procBtn.disabled = false;
    progWrap.classList.remove('show');
    errBar.classList.remove('show');
  };
  reader.readAsDataURL(file);
}

async function processImage() {
  if (!currentFile) return;
  if (!BACKEND_URL) {
    return showErr('Backend URL is not configured. Set BACKEND_URL in app.js.');
  }

  errBar.classList.remove('show');
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
  procImg.src = dataUrl;
  procImg.style.display = 'block';
  procHint.style.display = 'none';
  procBadge.textContent = '✓ Done';
  procBadge.className = 'badge done';
  dlBtn.href = dataUrl;
  dlBtn.classList.add('show');
}

function setLoading(on) {
  procBtn.disabled = on || !currentFile;
  procBtn.textContent = on ? 'Processing…' : 'Remove Background';
}

function setProgress(percent, label) {
  progWrap.classList.add('show');
  progFill.style.width = percent + '%';
  progText.textContent = label;
  progPct.textContent = percent + '%';
}

function showErr(message) {
  errBar.textContent = '⚠ ' + message;
  errBar.classList.add('show');
}
