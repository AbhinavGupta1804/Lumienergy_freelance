/* ─── Lumi Energy — Bill Upload Page ───────────────────────── */

const MAX_SIZE_BYTES = 20 * 1024 * 1024; // 20 MB

const states = {
  invalid:   document.getElementById('state-invalid'),
  form:      document.getElementById('state-form'),
  uploading: document.getElementById('state-uploading'),
  success:   document.getElementById('state-success'),
  error:     document.getElementById('state-error'),
};

const filePreview    = document.getElementById('file-preview');
const uploadOptions  = document.getElementById('upload-options');
const previewName    = document.getElementById('preview-name');
const previewRemove  = document.getElementById('preview-remove');
const fileInput      = document.getElementById('file-input');
const dropzone       = document.getElementById('dropzone');
const btnFile        = document.getElementById('btn-file');
const btnCamera      = document.getElementById('btn-camera');
const btnSubmit      = document.getElementById('btn-submit');
const btnRetry       = document.getElementById('btn-retry');
const fileError      = document.getElementById('file-error');
const progressBar    = document.getElementById('progress-bar');
const errorMessage   = document.getElementById('error-message');

const cameraInput = document.createElement('input');
cameraInput.type    = 'file';
cameraInput.accept  = 'image/*';
cameraInput.capture = 'environment';
cameraInput.hidden  = true;
document.body.appendChild(cameraInput);

let selectedFile = null;
let uploadToken  = null;

function show(state) {
  Object.values(states).forEach(el => el.hidden = true);
  states[state].hidden = false;
}

function setFile(file) {
  if (!file) return;

  if (file.size > MAX_SIZE_BYTES) {
    showFileError('File is too large. Maximum size is 20 MB.');
    return;
  }

  selectedFile = file;
  previewName.textContent = file.name;
  filePreview.hidden   = false;
  uploadOptions.hidden = true;
  btnSubmit.disabled   = false;
  hideFileError();
}

function clearFile() {
  selectedFile         = null;
  fileInput.value      = '';
  cameraInput.value    = '';
  filePreview.hidden   = true;
  uploadOptions.hidden = false;
  btnSubmit.disabled   = true;
}

function showFileError(msg) {
  fileError.textContent = msg;
  fileError.hidden      = false;
}

function hideFileError() {
  fileError.hidden = true;
}

function getToken() {
  return new URLSearchParams(window.location.search).get('token') || '';
}

async function validateToken(token) {
  if (!token) return false;
  try {
    const res = await fetch(`/api/validate-token?token=${encodeURIComponent(token)}`);
    if (!res.ok) return false;
    const data = await res.json();
    return data.valid === true;
  } catch {
    return false;
  }
}

async function uploadFile(file, token) {
  return new Promise((resolve, reject) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('token', token);

    const xhr = new XMLHttpRequest();

    xhr.upload.addEventListener('progress', (e) => {
      if (e.lengthComputable) {
        progressBar.style.width = `${Math.round((e.loaded / e.total) * 100)}%`;
      }
    });

    xhr.addEventListener('load', () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText));
      } else {
        let msg = 'Upload failed. Please try again.';
        try {
          const body = JSON.parse(xhr.responseText);
          if (body.error) msg = body.error;
        } catch { /* ignore */ }
        reject(new Error(msg));
      }
    });

    xhr.addEventListener('error',   () => reject(new Error('Network error. Please check your connection.')));
    xhr.addEventListener('timeout', () => reject(new Error('Upload timed out. Please try again.')));

    xhr.timeout = 120_000;
    xhr.open('POST', '/api/upload');
    xhr.send(formData);
  });
}

btnFile.addEventListener('click', () => {
  fileInput.value = '';
  fileInput.click();
});
fileInput.addEventListener('change', () => {
  if (fileInput.files[0]) setFile(fileInput.files[0]);
});

btnCamera.addEventListener('click', () => {
  cameraInput.value = '';
  cameraInput.click();
});
cameraInput.addEventListener('change', () => {
  if (cameraInput.files[0]) setFile(cameraInput.files[0]);
});

previewRemove.addEventListener('click', clearFile);

if (dropzone) {
  dropzone.addEventListener('click', () => {
    if (!selectedFile) {
      fileInput.value = '';
      fileInput.click();
    }
  });

  dropzone.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      if (!selectedFile) {
        fileInput.value = '';
        fileInput.click();
      }
    }
  });

  dropzone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropzone.classList.add('drag-over');
  });

  dropzone.addEventListener('dragleave', () => {
    dropzone.classList.remove('drag-over');
  });

  dropzone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropzone.classList.remove('drag-over');
    const file = e.dataTransfer.files[0];
    if (file) setFile(file);
  });
}

document.getElementById('upload-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  if (!selectedFile) return;

  show('uploading');
  progressBar.style.width = '0%';

  try {
    await uploadFile(selectedFile, uploadToken);
    show('success');
  } catch (err) {
    errorMessage.textContent = err.message || 'Something went wrong. Please try again.';
    show('error');
  }
});

btnRetry.addEventListener('click', () => {
  clearFile();
  show('form');
});

(async function init() {
  uploadToken = getToken();
  const valid = await validateToken(uploadToken);
  show(valid ? 'form' : 'invalid');
})();
