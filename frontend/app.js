/**
 * CivicLens AI — Frontend Application
 * app.js
 *
 * Handles form validation, geolocation, photo preview, API communication,
 * loading/error states, and success confirmation display.
 *
 * Backend API base URL is configurable via window.CIVICLENS_API_URL.
 * Defaults to the FastAPI server running on port 8000.
 */

'use strict';

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

const API_BASE = (window.CIVICLENS_API_URL || 'http://localhost:8000').replace(/\/$/, '');
const MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024; // 5 MB
const ALLOWED_MIME_TYPES = new Set(['image/jpeg', 'image/png', 'image/gif', 'image/webp']);
const ALLOWED_EXTENSIONS = new Set(['.jpg', '.jpeg', '.png', '.gif', '.webp']);

// ---------------------------------------------------------------------------
// DOM references
// ---------------------------------------------------------------------------

const form          = document.getElementById('reportForm');
const submitBtn     = document.getElementById('submitBtn');
const categoryError = document.getElementById('categoryError');
const descEl        = document.getElementById('description');
const descCount     = document.getElementById('descCount');
const descError     = document.getElementById('descError');
const latEl         = document.getElementById('latitude');
const lonEl         = document.getElementById('longitude');
const latError      = document.getElementById('latError');
const lonError      = document.getElementById('lonError');
const geoBtn        = document.getElementById('geoBtn');
const geoStatus     = document.getElementById('geoStatus');
const uploadZone    = document.getElementById('uploadZone');
const photoInput    = document.getElementById('photoInput');
const uploadPreview = document.getElementById('uploadPreview');
const previewImg    = document.getElementById('previewImg');
const previewName   = document.getElementById('previewName');
const removePhoto   = document.getElementById('removePhoto');
const photoError    = document.getElementById('photoError');
const formErrorBanner = document.getElementById('formErrorBanner');
const reportFormCard  = document.getElementById('reportFormCard');
const successCard     = document.getElementById('successCard');
const reportIdDisplay    = document.getElementById('reportIdDisplay');
const reportStatusDisplay = document.getElementById('reportStatusDisplay');
const classifierNote  = document.getElementById('classifierNote');
const classifierText  = document.getElementById('classifierText');
const newReportBtn    = document.getElementById('newReportBtn');
const toastContainer  = document.getElementById('toastContainer');

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

/**
 * Clear a field-level error.
 * @param {HTMLElement} el
 */
function clearError(el) {
  el.textContent = '';
}

/**
 * Set a field-level error with an icon.
 * @param {HTMLElement} el
 * @param {string} msg
 */
function setError(el, msg) {
  el.textContent = '⚠ ' + msg;
}

/**
 * Show a toast notification.
 * @param {'success'|'error'|'info'} type
 * @param {string} title
 * @param {string} msg
 */
function showToast(type, title, msg) {
  const icons = { success: '✅', error: '❌', info: 'ℹ️' };
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.setAttribute('role', 'status');
  toast.innerHTML = `
    <span class="toast-icon" aria-hidden="true">${icons[type] || 'ℹ️'}</span>
    <div class="toast-body">
      <div class="toast-title">${escHtml(title)}</div>
      <div class="toast-msg">${escHtml(msg)}</div>
    </div>
  `;
  toastContainer.appendChild(toast);

  // Auto-remove after 5s
  setTimeout(() => {
    toast.classList.add('removing');
    toast.addEventListener('animationend', () => toast.remove(), { once: true });
  }, 5000);
}

/**
 * Basic HTML escape to prevent XSS in toast content.
 * @param {string} str
 * @returns {string}
 */
function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/**
 * Get the extension of a filename (lowercased, including the dot).
 * @param {string} filename
 * @returns {string}
 */
function getExtension(filename) {
  const idx = filename.lastIndexOf('.');
  return idx >= 0 ? filename.slice(idx).toLowerCase() : '';
}

/**
 * Format bytes to a human-readable string.
 * @param {number} bytes
 * @returns {string}
 */
function formatBytes(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
}

// ---------------------------------------------------------------------------
// Description character counter
// ---------------------------------------------------------------------------

descEl.addEventListener('input', () => {
  const len = descEl.value.length;
  descCount.textContent = len;
  if (len >= 5) clearError(descError);
});

// ---------------------------------------------------------------------------
// Geolocation
// ---------------------------------------------------------------------------

function setGeoStatus(cls, msg) {
  geoStatus.className = `geo-status visible ${cls}`;
  geoStatus.textContent = msg;
}

geoBtn.addEventListener('click', () => {
  if (!('geolocation' in navigator)) {
    setGeoStatus('error', 'Geolocation not supported by your browser. Please enter coordinates manually.');
    return;
  }

  geoBtn.disabled = true;
  setGeoStatus('loading', '⏳ Requesting location…');

  navigator.geolocation.getCurrentPosition(
    (pos) => {
      latEl.value = pos.coords.latitude.toFixed(6);
      lonEl.value = pos.coords.longitude.toFixed(6);
      setGeoStatus('success', `✓ Location set: ${pos.coords.latitude.toFixed(4)}, ${pos.coords.longitude.toFixed(4)}`);
      clearError(latError);
      clearError(lonError);
      geoBtn.disabled = false;
    },
    (err) => {
      const messages = {
        1: 'Location access denied. Please enter coordinates manually.',
        2: 'Location unavailable. Check your device settings or enter manually.',
        3: 'Location request timed out. Please try again or enter manually.',
      };
      setGeoStatus('error', messages[err.code] || 'Could not get location. Please enter manually.');
      geoBtn.disabled = false;
    },
    { timeout: 10000, maximumAge: 60000 }
  );
});

// ---------------------------------------------------------------------------
// Photo upload
// ---------------------------------------------------------------------------

/**
 * Validate a file and show the preview, or display an error.
 * @param {File} file
 */
function handleFileSelection(file) {
  clearError(photoError);

  if (!file) return;

  // Check extension
  const ext = getExtension(file.name);
  if (!ALLOWED_EXTENSIONS.has(ext)) {
    setError(photoError, `Unsupported file type "${ext}". Allowed: JPEG, PNG, GIF, WebP.`);
    photoInput.value = '';
    return;
  }

  // Check MIME type
  if (!ALLOWED_MIME_TYPES.has(file.type)) {
    setError(photoError, `Unsupported image format "${file.type}". Please use JPEG, PNG, GIF, or WebP.`);
    photoInput.value = '';
    return;
  }

  // Check size
  if (file.size > MAX_FILE_SIZE_BYTES) {
    setError(photoError, `File is too large (${formatBytes(file.size)}). Maximum is 5 MB.`);
    photoInput.value = '';
    return;
  }

  // Show preview
  const reader = new FileReader();
  reader.onload = (e) => {
    previewImg.src = e.target.result;
    previewName.textContent = `${file.name} · ${formatBytes(file.size)}`;
    uploadPreview.classList.add('visible');
  };
  reader.readAsDataURL(file);
}

photoInput.addEventListener('change', () => {
  const file = photoInput.files[0];
  if (file) handleFileSelection(file);
});

// Drag-and-drop on the upload zone
uploadZone.addEventListener('dragover', (e) => {
  e.preventDefault();
  uploadZone.classList.add('drag-over');
});

uploadZone.addEventListener('dragleave', () => {
  uploadZone.classList.remove('drag-over');
});

uploadZone.addEventListener('drop', (e) => {
  e.preventDefault();
  uploadZone.classList.remove('drag-over');
  const file = e.dataTransfer?.files[0];
  if (file) {
    // Transfer to the input so FormData picks it up
    const dt = new DataTransfer();
    dt.items.add(file);
    photoInput.files = dt.files;
    handleFileSelection(file);
  }
});

// Keyboard activate upload zone
uploadZone.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault();
    photoInput.click();
  }
});

removePhoto.addEventListener('click', () => {
  photoInput.value = '';
  previewImg.src = '';
  previewName.textContent = '';
  uploadPreview.classList.remove('visible');
  clearError(photoError);
});

// ---------------------------------------------------------------------------
// Form validation
// ---------------------------------------------------------------------------

/**
 * Validate the form client-side.
 * @returns {{ valid: boolean }}
 */
function validateForm() {
  let valid = true;

  // Category
  const category = document.querySelector('input[name="category"]:checked');
  if (!category) {
    setError(categoryError, 'Please select an issue category.');
    valid = false;
  } else {
    clearError(categoryError);
  }

  // Description
  const desc = descEl.value.trim();
  if (desc.length < 5) {
    setError(descError, 'Description must be at least 5 characters.');
    valid = false;
  } else {
    clearError(descError);
  }

  // Coordinates — both or neither
  const lat = latEl.value.trim();
  const lon = lonEl.value.trim();

  clearError(latError);
  clearError(lonError);

  if ((lat !== '') !== (lon !== '')) {
    if (lat === '') {
      setError(latError, 'Please enter latitude, or clear longitude to omit both.');
    } else {
      setError(lonError, 'Please enter longitude, or clear latitude to omit both.');
    }
    valid = false;
  } else {
    if (lat !== '') {
      const latNum = parseFloat(lat);
      if (isNaN(latNum) || latNum < -90 || latNum > 90) {
        setError(latError, 'Latitude must be between -90 and 90.');
        valid = false;
      }
    }
    if (lon !== '') {
      const lonNum = parseFloat(lon);
      if (isNaN(lonNum) || lonNum < -180 || lonNum > 180) {
        setError(lonError, 'Longitude must be between -180 and 180.');
        valid = false;
      }
    }
  }

  // Photo (if one was selected, it's already validated in handleFileSelection)
  const file = photoInput.files[0];
  if (file) {
    if (!ALLOWED_MIME_TYPES.has(file.type)) {
      setError(photoError, 'Please remove the invalid file before submitting.');
      valid = false;
    } else if (file.size > MAX_FILE_SIZE_BYTES) {
      setError(photoError, 'Please remove the oversized file before submitting.');
      valid = false;
    }
  }

  return { valid };
}

// ---------------------------------------------------------------------------
// Submit handler
// ---------------------------------------------------------------------------

form.addEventListener('submit', async (e) => {
  e.preventDefault();

  // Clear global error
  formErrorBanner.textContent = '';
  formErrorBanner.classList.remove('visible');

  const { valid } = validateForm();
  if (!valid) {
    showToast('error', 'Validation failed', 'Please fix the highlighted fields and try again.');
    return;
  }

  // Build FormData
  const fd = new FormData();
  fd.append('category', document.querySelector('input[name="category"]:checked').value);
  fd.append('description', descEl.value.trim());

  const lat = latEl.value.trim();
  const lon = lonEl.value.trim();
  if (lat && lon) {
    fd.append('latitude', lat);
    fd.append('longitude', lon);
  }

  const file = photoInput.files[0];
  if (file) fd.append('image', file);

  // Loading state
  submitBtn.disabled = true;
  submitBtn.classList.add('loading');
  submitBtn.textContent = '⏳ Submitting…';

  try {
    const response = await fetch(`${API_BASE}/reports`, {
      method: 'POST',
      body: fd,
      // Do NOT set Content-Type — browser sets multipart boundary automatically
    });

    const data = await response.json();

    if (!response.ok) {
      // Server returned an error
      const detail = Array.isArray(data.detail)
        ? data.detail.map(d => d.msg || JSON.stringify(d)).join(' · ')
        : (data.detail || 'Submission failed. Please try again.');

      throw new Error(detail);
    }

    // Success — show confirmation
    displaySuccess(data);

  } catch (err) {
    const msg = err.message || 'An unexpected error occurred. Please check your connection and try again.';
    formErrorBanner.textContent = '❌ ' + msg;
    formErrorBanner.classList.add('visible');
    showToast('error', 'Submission failed', msg);

  } finally {
    submitBtn.disabled = false;
    submitBtn.classList.remove('loading');
    submitBtn.textContent = 'Submit Report';
  }
});

// ---------------------------------------------------------------------------
// Success display
// ---------------------------------------------------------------------------

/**
 * @param {object} data — API response from POST /reports
 */
function displaySuccess(data) {
  // Populate fields
  reportIdDisplay.textContent = '#' + data.id;
  reportStatusDisplay.textContent = capitalise(data.status || 'submitted');

  const clf = data.classifier || {};
  const priorityLabel = getPriorityLabel(clf.priority_score || data.priority_score || 0);

  if (clf.suggestion || clf.note) {
    classifierText.textContent =
      `Suggested category: ${clf.suggestion || '—'} · Priority: ${clf.priority_score ?? '—'}/100 (${priorityLabel}). ${clf.note || ''}`;
    classifierNote.style.display = 'block';
  } else {
    classifierNote.style.display = 'none';
  }

  // Hide form, show success card
  reportFormCard.style.display = 'none';
  successCard.classList.add('visible');

  // Scroll to top of success card
  successCard.scrollIntoView({ behavior: 'smooth', block: 'center' });

  showToast('success', 'Report submitted!', `Report #${data.id} has been logged successfully.`);
}

function capitalise(str) {
  return str.charAt(0).toUpperCase() + str.slice(1).replace(/_/g, ' ');
}

function getPriorityLabel(score) {
  if (score >= 65) return 'High';
  if (score >= 40) return 'Medium';
  return 'Low';
}

// ---------------------------------------------------------------------------
// Reset / new report
// ---------------------------------------------------------------------------

newReportBtn.addEventListener('click', () => {
  // Reset form
  form.reset();
  descCount.textContent = '0';
  previewImg.src = '';
  previewName.textContent = '';
  uploadPreview.classList.remove('visible');
  geoStatus.className = 'geo-status';
  geoStatus.textContent = '';

  // Clear all errors
  [categoryError, descError, latError, lonError, photoError].forEach(clearError);
  formErrorBanner.classList.remove('visible');

  // Show form again
  successCard.classList.remove('visible');
  reportFormCard.style.display = '';

  // Scroll to top
  reportFormCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
});
