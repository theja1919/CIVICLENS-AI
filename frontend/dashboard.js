/**
 * dashboard.js — CivicLens AI Admin Dashboard
 *
 * Talks to the Flask backend at localhost:8000.
 * Uses Leaflet + OpenStreetMap for the map (requires internet for tiles).
 * All data is fetched live from the API — no hardcoded statistics.
 */

"use strict";

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------
const API_BASE = "http://localhost:8000";
const PAGE_SIZE = 20;

// Category display metadata
const CAT_META = {
  pothole:            { label: "Pothole",           color: "#f59e0b", cls: "cat-pothole",     icon: "🕳️"  },
  garbage:            { label: "Garbage",           color: "#10b981", cls: "cat-garbage",     icon: "🗑️"  },
  broken_streetlight: { label: "Broken Streetlight",color: "#8b5cf6", cls: "cat-streetlight", icon: "💡"  },
  water_leak:         { label: "Water Leak",        color: "#06b6d4", cls: "cat-water_leak",  icon: "💧"  },
  other:              { label: "Other",             color: "#6b7280", cls: "cat-other",       icon: "📌"  },
};

const STATUS_META = {
  submitted:   { label: "Submitted",   cls: "status-submitted",   icon: "📥" },
  assigned:    { label: "Assigned",    cls: "status-assigned",    icon: "👤" },
  in_progress: { label: "In Progress", cls: "status-in_progress", icon: "⚙️" },
  resolved:    { label: "Resolved",    cls: "status-resolved",    icon: "✅" },
};

const STATUS_TRANSITIONS = {
  submitted:   ["assigned"],
  assigned:    ["in_progress"],
  in_progress: ["resolved"],
  resolved:    [],
};

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let currentPage = 0;
let totalReports = 0;
let currentFilters = {};
let leafletMap = null;
let mapInitialized = false;
let activeSection = "stats";

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
  initNav();
  initFilters();
  initModal();
  initPagination();
  document.getElementById("refreshBtn").addEventListener("click", refreshAll);
  checkApiStatus();
  loadStats();
  loadReports();
});

// ---------------------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------------------
function initNav() {
  document.querySelectorAll(".nav-item").forEach(link => {
    link.addEventListener("click", e => {
      e.preventDefault();
      const section = link.dataset.section;
      switchSection(section);
    });
  });
}

function switchSection(section) {
  activeSection = section;
  document.querySelectorAll(".nav-item").forEach(l => l.classList.toggle("active", l.dataset.section === section));
  document.querySelectorAll(".dash-section").forEach(s => s.classList.add("hidden"));
  document.getElementById(`${section}-section`).classList.remove("hidden");

  if (section === "map" && !mapInitialized) {
    initMap();
  }
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------
async function apiFetch(path, options = {}) {
  const resp = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options.headers },
    ...options,
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw Object.assign(new Error(err.detail || "API error"), { status: resp.status, detail: err.detail });
  }
  return resp.json();
}

async function checkApiStatus() {
  const pill = document.getElementById("apiStatus");
  try {
    const data = await apiFetch("/health");
    pill.className = "api-status-pill online";
    pill.innerHTML = `<span class="api-dot"></span> API Online (v${data.version})`;
  } catch {
    pill.className = "api-status-pill offline";
    pill.innerHTML = `<span class="api-dot"></span> API Offline`;
  }
}

function refreshAll() {
  const btn = document.getElementById("refreshBtn");
  btn.classList.add("spin");
  Promise.allSettled([
    checkApiStatus(),
    loadStats(),
    loadReports(),
    mapInitialized ? loadMapData() : Promise.resolve(),
  ]).finally(() => btn.classList.remove("spin"));
}

// ---------------------------------------------------------------------------
// Stats / Overview
// ---------------------------------------------------------------------------
async function loadStats() {
  try {
    const data = await apiFetch("/stats");
    setKpi("kpiTotal",     data.total_reports);
    setKpi("kpiSubmitted", data.by_status.submitted);
    setKpi("kpiProgress",  (data.by_status.in_progress || 0) + (data.by_status.assigned || 0));
    setKpi("kpiResolved",  data.by_status.resolved);
    setKpi("kpiHigh",      data.high_priority_count);
    renderCategoryBars(data.by_category, data.total_reports);
    renderHighPriorityList(data.recent_high_priority);
  } catch (e) {
    showToast("error", "Stats unavailable", e.message);
  }
}

function setKpi(id, value) {
  const el = document.getElementById(id);
  if (!el) return;
  const current = parseInt(el.textContent, 10);
  const target = parseInt(value, 10);
  if (isNaN(current) || isNaN(target)) { el.textContent = value; return; }
  animateCounter(el, current || 0, target, 600);
}

function animateCounter(el, from, to, durationMs) {
  const start = performance.now();
  const update = (now) => {
    const t = Math.min((now - start) / durationMs, 1);
    el.textContent = Math.round(from + (to - from) * easeOut(t));
    if (t < 1) requestAnimationFrame(update);
  };
  requestAnimationFrame(update);
}
function easeOut(t) { return 1 - Math.pow(1 - t, 3); }

function renderCategoryBars(byCategory, total) {
  const container = document.getElementById("catBars");
  if (!byCategory || Object.keys(byCategory).length === 0) {
    container.innerHTML = `<p class="empty-state">No reports yet.</p>`;
    return;
  }
  const maxCount = Math.max(...Object.values(byCategory), 1);
  const order = ["pothole", "garbage", "broken_streetlight", "water_leak", "other"];
  const html = order
    .filter(cat => byCategory[cat] > 0)
    .map(cat => {
      const count = byCategory[cat] || 0;
      const pct = Math.round((count / maxCount) * 100);
      const meta = CAT_META[cat] || { label: cat, color: "#6b7280" };
      return `
        <div class="cat-bar-row" role="listitem">
          <span class="cat-bar-label">${meta.icon || ""} ${meta.label}</span>
          <div class="cat-bar-track">
            <div class="cat-bar-fill" style="width:${pct}%;background:${meta.color}"></div>
          </div>
          <span class="cat-bar-count">${count}</span>
        </div>`;
    }).join("");
  container.innerHTML = html || `<p class="empty-state">No reports yet.</p>`;
}

function renderHighPriorityList(reports) {
  const el = document.getElementById("highPriorityList");
  if (!reports || reports.length === 0) {
    el.innerHTML = `<p class="empty-state">No high-priority reports yet.</p>`;
    return;
  }
  el.innerHTML = reports.map(r => {
    const cat = CAT_META[r.category] || { label: r.category, icon: "📌" };
    const scoreClass = r.priority_score >= 80 ? "score-high" : r.priority_score >= 65 ? "score-medium" : "score-low";
    const desc = r.description.length > 80 ? r.description.slice(0, 80) + "…" : r.description;
    return `
      <div class="hp-item" onclick="openReportModal(${r.id})" role="button"
           tabindex="0" aria-label="View report ${r.id}">
        <div class="hp-score ${scoreClass}">${r.priority_score}</div>
        <div class="hp-meta">
          <div class="hp-desc">${esc(desc)}</div>
          <div class="hp-sub">${cat.icon} ${cat.label} · #${r.id} · ${formatDate(r.created_at)}</div>
        </div>
      </div>`;
  }).join("");
}

// ---------------------------------------------------------------------------
// Map
// ---------------------------------------------------------------------------
function initMap() {
  if (mapInitialized) return;
  mapInitialized = true;

  leafletMap = L.map("leafletMap").setView([20, 0], 2);

  const tileLayer = L.tileLayer(
    "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    {
      attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      maxZoom: 19,
    }
  );

  tileLayer.on("tileerror", () => {
    document.getElementById("mapTileError").classList.remove("hidden");
  });

  tileLayer.addTo(leafletMap);
  loadMapData();
}

async function loadMapData() {
  try {
    const data = await apiFetch("/map-data");
    renderMapFeatures(data);
    const statsEl = document.getElementById("mapStats");
    if (statsEl) {
      statsEl.textContent = `Showing ${data.total_with_coordinates} mapped report(s). ` +
        (data.total_without_coordinates > 0
          ? `${data.total_without_coordinates} report(s) have no coordinates and are not shown.`
          : "All reports have coordinates.");
    }
  } catch (e) {
    showToast("error", "Map data unavailable", e.message);
  }
}

const mapMarkers = [];
function renderMapFeatures(data) {
  if (!leafletMap) return;
  mapMarkers.forEach(m => m.remove());
  mapMarkers.length = 0;

  if (!data.features || data.features.length === 0) return;

  const bounds = [];
  data.features.forEach(f => {
    const cat = CAT_META[f.category] || { color: "#6b7280" };
    const scoreClass = f.priority_score >= 80 ? "#ef4444" : f.priority_score >= 65 ? "#f59e0b" : "#10b981";

    const icon = L.divIcon({
      className: "",
      html: `<div style="
        width:28px; height:28px; border-radius:50%;
        background:${cat.color};
        border:3px solid ${scoreClass};
        box-shadow:0 2px 8px rgba(0,0,0,.4);
        display:flex; align-items:center; justify-content:center;
        font-size:12px;
      "></div>`,
      iconSize: [28, 28],
      iconAnchor: [14, 14],
    });

    const marker = L.marker([f.latitude, f.longitude], { icon })
      .addTo(leafletMap)
      .bindPopup(`
        <div style="font-family:system-ui;font-size:13px;min-width:180px">
          <strong>#${f.id} — ${esc(cat.label || f.category)}</strong><br/>
          <span style="color:#64748b;font-size:11px">${esc(STATUS_META[f.status]?.label || f.status)} · Priority ${f.priority_score}</span><br/>
          <span style="margin-top:4px;display:block;font-size:12px;line-height:1.4">${esc(f.description_preview)}</span>
          <a onclick="openReportModal(${f.id})" style="cursor:pointer;color:#06b6d4;font-size:11px;margin-top:4px;display:inline-block">View details →</a>
        </div>
      `);

    mapMarkers.push(marker);
    bounds.push([f.latitude, f.longitude]);
  });

  if (bounds.length > 0) {
    leafletMap.fitBounds(bounds, { padding: [32, 32], maxZoom: 14 });
  }
}

// ---------------------------------------------------------------------------
// Reports table
// ---------------------------------------------------------------------------
async function loadReports(page = 0) {
  currentPage = page;
  const params = new URLSearchParams({
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
    ...currentFilters,
  });
  Object.keys(params).forEach(k => !params.get(k) && params.delete(k));

  try {
    const data = await apiFetch(`/reports?${params.toString()}`);
    totalReports = data.total;
    renderReportTable(data.reports, data.total);
    updatePagination(page, data.total);
  } catch (e) {
    document.getElementById("reportTableBody").innerHTML =
      `<tr><td colspan="8" class="empty-cell">Failed to load: ${esc(e.message)}</td></tr>`;
    showToast("error", "Reports unavailable", e.message);
  }
}

function renderReportTable(reports, total) {
  const meta = document.getElementById("reportCount");
  meta.textContent = `Showing ${reports.length} of ${total} report(s)`;

  const tbody = document.getElementById("reportTableBody");
  if (reports.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" class="empty-cell">No reports match your filters.</td></tr>`;
    return;
  }

  tbody.innerHTML = reports.map(r => {
    const cat = CAT_META[r.category] || { label: r.category, cls: "cat-other", icon: "📌" };
    const status = STATUS_META[r.status] || { label: r.status, cls: "status-submitted" };
    const priBadge = priorityBadge(r.priority_score);
    const desc = r.description.length > 60 ? r.description.slice(0, 60) + "…" : r.description;
    const loc = r.latitude != null ? `${r.latitude.toFixed(4)}, ${r.longitude.toFixed(4)}` : "—";
    return `
      <tr onclick="openReportModal(${r.id})" aria-label="Open report ${r.id}">
        <td><code style="font-family:var(--font-mono);font-size:.75rem">#${r.id}</code></td>
        <td><span class="cat-pill ${cat.cls}">${cat.icon} ${cat.label}</span></td>
        <td title="${esc(r.description)}">${esc(desc)}</td>
        <td><span class="status-badge ${status.cls}">${status.icon || ""} ${status.label}</span></td>
        <td>${priBadge}</td>
        <td style="font-size:.75rem;color:var(--clr-text-muted)">${loc}</td>
        <td style="font-size:.75rem;color:var(--clr-text-muted)">${formatDate(r.created_at)}</td>
        <td><button class="action-btn" onclick="event.stopPropagation();openReportModal(${r.id})">View</button></td>
      </tr>`;
  }).join("");
}

function priorityBadge(score) {
  const cls = score >= 65 ? "pri-high" : score >= 40 ? "pri-medium" : "pri-low";
  return `<span class="priority-badge ${cls}">${score}</span>`;
}

// ---------------------------------------------------------------------------
// Pagination
// ---------------------------------------------------------------------------
function updatePagination(page, total) {
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  document.getElementById("pageInfo").textContent = `Page ${page + 1} of ${pages}`;
  document.getElementById("prevPage").disabled = page === 0;
  document.getElementById("nextPage").disabled = (page + 1) * PAGE_SIZE >= total;
}

function initPagination() {
  document.getElementById("prevPage").addEventListener("click", () => loadReports(currentPage - 1));
  document.getElementById("nextPage").addEventListener("click", () => loadReports(currentPage + 1));
}

// ---------------------------------------------------------------------------
// Filters
// ---------------------------------------------------------------------------
function initFilters() {
  document.getElementById("applyFilters").addEventListener("click", applyFilters);
  document.getElementById("clearFilters").addEventListener("click", clearFilters);
  document.getElementById("filterSearch").addEventListener("keydown", e => {
    if (e.key === "Enter") applyFilters();
  });
}

function applyFilters() {
  currentFilters = {};
  const search   = document.getElementById("filterSearch").value.trim();
  const category = document.getElementById("filterCategory").value;
  const status   = document.getElementById("filterStatus").value;
  if (search)   currentFilters.search   = search;
  if (category) currentFilters.category = category;
  if (status)   currentFilters.status   = status;
  loadReports(0);
  switchSection("reports");
}

function clearFilters() {
  currentFilters = {};
  document.getElementById("filterSearch").value = "";
  document.getElementById("filterCategory").value = "";
  document.getElementById("filterStatus").value = "";
  loadReports(0);
}

// ---------------------------------------------------------------------------
// Report Detail Modal
// ---------------------------------------------------------------------------
function initModal() {
  document.getElementById("modalClose").addEventListener("click", closeModal);
  document.getElementById("modalOverlay").addEventListener("click", e => {
    if (e.target === document.getElementById("modalOverlay")) closeModal();
  });
  document.addEventListener("keydown", e => { if (e.key === "Escape") closeModal(); });
}

function closeModal() {
  document.getElementById("modalOverlay").classList.add("hidden");
  document.getElementById("modalBody").innerHTML = "";
}

async function openReportModal(reportId) {
  const overlay = document.getElementById("modalOverlay");
  const body = document.getElementById("modalBody");
  document.getElementById("modalTitle").textContent = `Report #${reportId}`;
  body.innerHTML = `<p class="empty-state">Loading…</p>`;
  overlay.classList.remove("hidden");

  try {
    const [report, priorityData, dupsData, histData] = await Promise.allSettled([
      apiFetch(`/reports/${reportId}`),
      apiFetch(`/reports/${reportId}/priority`),
      apiFetch(`/reports/${reportId}/duplicates`),
      apiFetch(`/reports/${reportId}/history`),
    ]);

    const r  = report.value;
    const pd = priorityData.value;
    const dd = dupsData.value;
    const hd = histData.value;

    if (!r) {
      body.innerHTML = `<p class="empty-state">Failed to load report.</p>`;
      return;
    }

    body.innerHTML = buildModalBody(r, pd, dd, hd);
    initStatusControls(r);

  } catch (e) {
    body.innerHTML = `<p class="empty-state" style="color:var(--clr-error)">${esc(e.message)}</p>`;
  }
}

function buildModalBody(r, pd, dd, hd) {
  const cat = CAT_META[r.category] || { label: r.category, icon: "📌" };
  const status = STATUS_META[r.status] || { label: r.status };

  let html = `
    <!-- Basic info -->
    <div class="modal-field"><span class="modal-field-label">Category</span>
      <span class="cat-pill ${cat.cls}">${cat.icon} ${cat.label}</span></div>
    <div class="modal-field"><span class="modal-field-label">Status</span>
      <span class="status-badge ${status.cls}">${status.label}</span></div>
    <div class="modal-field"><span class="modal-field-label">Priority</span>
      ${priorityBadge(r.priority_score)}</div>
    <div class="modal-field"><span class="modal-field-label">Description</span>
      <span class="modal-field-value">${esc(r.description)}</span></div>`;

  if (r.latitude != null) {
    html += `<div class="modal-field"><span class="modal-field-label">Coordinates</span>
      <span class="modal-field-value">${r.latitude.toFixed(6)}, ${r.longitude.toFixed(6)}
        <a href="https://www.openstreetmap.org/?mlat=${r.latitude}&mlon=${r.longitude}&zoom=16"
           target="_blank" style="margin-left:8px;font-size:.75rem">View on map ↗</a>
      </span></div>`;
  }

  html += `
    <div class="modal-field"><span class="modal-field-label">Submitted</span>
      <span class="modal-field-value">${formatDateFull(r.created_at)}</span></div>
    <div class="modal-field"><span class="modal-field-label">Updated</span>
      <span class="modal-field-value">${formatDateFull(r.updated_at)}</span></div>`;

  if (r.assigned_at) {
    html += `<div class="modal-field"><span class="modal-field-label">Assigned</span>
      <span class="modal-field-value">${formatDateFull(r.assigned_at)}</span></div>`;
  }
  if (r.resolved_at) {
    html += `<div class="modal-field"><span class="modal-field-label">Resolved</span>
      <span class="modal-field-value">${formatDateFull(r.resolved_at)}</span></div>`;
  }

  // Image
  if (r.image_path) {
    html += `
      <div class="modal-section-title">Photo</div>
      <img class="modal-img" src="${API_BASE}/${r.image_path}"
           alt="Photo for report #${r.id}" loading="lazy" />`;
  }

  // Priority breakdown
  if (pd && pd.breakdown) {
    const bd = pd.breakdown;
    html += `<div class="modal-section-title">Priority Breakdown</div>
      <div class="priority-factors">
        ${(bd.factors || []).map(f => `
          <div class="pf-row">
            <span class="pf-value ${f.value < 0 ? 'neg' : ''}">${f.value > 0 ? '+' : ''}${f.value}</span>
            <div>
              <div style="font-weight:600;font-size:.8125rem">${esc(f.name)}</div>
              <div class="pf-desc">${esc(f.description)}</div>
            </div>
          </div>`).join("")}
      </div>
      <div class="disclaimer-box" style="margin-top:12px">${esc(bd.disclaimer || "")}</div>`;
  }

  // Duplicate warnings
  if (dd) {
    if (dd.has_coordinates === false) {
      html += `<div class="modal-section-title">Duplicate Check</div>
        <p class="empty-state">No coordinates — duplicate detection not available for this report.</p>`;
    } else if (dd.duplicates && dd.duplicates.length > 0) {
      html += `<div class="modal-section-title">⚠️ Possible Duplicates (${dd.duplicates.length} within ${dd.radius_m}m)</div>
        <div class="dup-list">
          ${dd.duplicates.map(d => `
            <div class="dup-item">
              <span>#${d.id} — ${esc(d.category)} (${STATUS_META[d.status]?.label || d.status})</span>
              <span class="dup-dist">${d.distance_m}m away</span>
            </div>`).join("")}
        </div>
        <p style="font-size:.75rem;color:var(--clr-text-faint);margin-top:6px">${esc(dd.note || "")}</p>`;
    } else {
      html += `<div class="modal-section-title">Duplicate Check</div>
        <p class="empty-state">No nearby duplicate reports found within ${dd.radius_m}m.</p>`;
    }
  }

  // Resolution note (if resolved)
  if (r.resolution_note) {
    html += `<div class="modal-section-title">✅ Resolution Note</div>
      <div class="disclaimer-box" style="background:rgba(16,185,129,.06);border-color:rgba(16,185,129,.2);color:var(--clr-text)">${esc(r.resolution_note)}</div>`;
  }
  if (r.resolution_image_path) {
    html += `<div class="modal-section-title">After-Photo</div>
      <img class="modal-img" src="${API_BASE}/${r.resolution_image_path}"
           alt="After-photo for report #${r.id}" loading="lazy" />`;
  }

  // Reopen info (if citizen requested)
  if (r.reopen_reason) {
    html += `<div class="modal-section-title">🔁 Reopen Request</div>
      <div class="disclaimer-box" style="background:rgba(245,158,11,.06);border-color:rgba(245,158,11,.2);color:var(--clr-text)">
        <strong>Reason:</strong> ${esc(r.reopen_reason)}<br/>
        <span style="font-size:.75rem;color:var(--clr-text-muted)">Requested: ${formatDateFull(r.reopen_at)}</span>
      </div>`;
  }

  // Status management
  const allowed = STATUS_TRANSITIONS[r.status] || [];
  html += `<div class="modal-section-title">Update Status</div>
    <div class="status-controls" id="statusControls">`;
  if (r.status === "resolved") {
    html += `<p class="empty-state" style="margin-bottom:8px">This report is resolved. Use the Reopen form below if the issue has recurred.</p>`;
  } else {
    allowed.forEach(next => {
      const sm = STATUS_META[next] || { label: next };
      html += `<button class="status-change-btn"
        onclick="changeStatus(${r.id},'${next}')"
        id="statusBtn-${next}">
        ${sm.icon || ""} Mark as "${sm.label}"
      </button>`;
    });
  }
  html += `</div>`;

  // Inline Resolve form (admin) — shown for assigned or in_progress
  if (r.status === "assigned" || r.status === "in_progress") {
    html += `
      <div class="modal-section-title">Resolve This Report (Admin)</div>
      <div style="display:flex;flex-direction:column;gap:8px">
        <textarea id="resolveNote" placeholder="Describe what was done to fix this issue…"
          rows="3" style="background:var(--clr-surface-alt);border:1px solid var(--clr-border);
          border-radius:var(--radius-sm);color:var(--clr-text);font-family:var(--font-sans);
          font-size:.875rem;padding:8px 10px;resize:vertical;width:100%"></textarea>
        <button class="apply-btn" onclick="resolveReport(${r.id})" id="resolveBtn">
          ✅ Mark as Resolved
        </button>
      </div>`;
  }

  // Citizen reopen request — shown only for resolved reports
  if (r.status === "resolved") {
    html += `
      <div class="modal-section-title">Request Reopen (Citizen)</div>
      <div style="display:flex;flex-direction:column;gap:8px">
        <textarea id="reopenReason" placeholder="Explain why the issue needs to be reopened (min 10 chars)…"
          rows="2" style="background:var(--clr-surface-alt);border:1px solid var(--clr-border);
          border-radius:var(--radius-sm);color:var(--clr-text);font-family:var(--font-sans);
          font-size:.875rem;padding:8px 10px;resize:vertical;width:100%"></textarea>
        <button class="clear-btn" onclick="requestReopen(${r.id})" id="reopenBtn"
          style="align-self:flex-start">
          🔁 Submit Reopen Request
        </button>
      </div>`;
  }

  // Status history
  if (hd && hd.history && hd.history.length > 0) {
    html += `<div class="modal-section-title">Status History</div>
      <div>
        ${hd.history.map(h => `
          <div class="history-entry">
            <span>${STATUS_META[h.from_status]?.label || h.from_status}</span>
            <span class="history-arrow">→</span>
            <span>${STATUS_META[h.to_status]?.label || h.to_status}</span>
            <span style="margin-left:auto;color:var(--clr-text-faint);font-size:.75rem">${formatDateFull(h.changed_at)}</span>
            ${h.note ? `<span style="display:block;width:100%;font-size:.7rem;color:var(--clr-text-faint);margin-top:2px;padding-left:4px">${esc(h.note)}</span>` : ""}
          </div>`).join("")}
      </div>`;
  }

  return html;
}

function initStatusControls(report) {
  // Nothing extra needed — buttons are inline onclick
}

async function changeStatus(reportId, newStatus) {
  const btn = document.getElementById(`statusBtn-${newStatus}`);
  if (btn) { btn.disabled = true; btn.textContent = "Updating…"; }

  try {
    await apiFetch(`/reports/${reportId}/status`, {
      method: "PATCH",
      body: JSON.stringify({ status: newStatus }),
    });
    showToast("success", "Status updated",
      `Report #${reportId} is now "${STATUS_META[newStatus]?.label || newStatus}".`);
    closeModal();
    await Promise.allSettled([loadStats(), loadReports(currentPage)]);
    if (mapInitialized) await loadMapData();
  } catch (e) {
    showToast("error", "Status update failed", e.message || "Unknown error");
    if (btn) { btn.disabled = false; btn.textContent = STATUS_META[newStatus]?.label || newStatus; }
  }
}

async function resolveReport(reportId) {
  const noteEl = document.getElementById("resolveNote");
  const btn = document.getElementById("resolveBtn");
  const note = (noteEl?.value || "").trim();
  if (!note || note.length < 5) {
    showToast("error", "Note required", "Please enter a resolution note (at least 5 characters).");
    noteEl?.focus();
    return;
  }
  if (btn) { btn.disabled = true; btn.textContent = "Resolving…"; }
  try {
    const fd = new FormData();
    fd.append("resolution_note", note);
    const resp = await fetch(`${API_BASE}/reports/${reportId}/resolve`, {
      method: "POST", body: fd,
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "Resolve failed");
    showToast("success", "Report resolved", `Report #${reportId} marked as resolved.`);
    closeModal();
    await Promise.allSettled([loadStats(), loadReports(currentPage)]);
    if (mapInitialized) await loadMapData();
  } catch (e) {
    showToast("error", "Resolve failed", e.message);
    if (btn) { btn.disabled = false; btn.textContent = "✅ Mark as Resolved"; }
  }
}

async function requestReopen(reportId) {
  const reasonEl = document.getElementById("reopenReason");
  const btn = document.getElementById("reopenBtn");
  const reason = (reasonEl?.value || "").trim();
  if (!reason || reason.length < 10) {
    showToast("error", "Reason required", "Please enter a reopen reason (at least 10 characters).");
    reasonEl?.focus();
    return;
  }
  if (btn) { btn.disabled = true; btn.textContent = "Submitting…"; }
  try {
    const data = await apiFetch(`/reports/${reportId}/reopen`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    });
    showToast("success", "Reopen request sent",
      `Reopen request for Report #${reportId} has been recorded.`);
    closeModal();
    await loadReports(currentPage);
  } catch (e) {
    showToast("error", "Reopen failed", e.message);
    if (btn) { btn.disabled = false; btn.textContent = "🔁 Submit Reopen Request"; }
  }
}

// ---------------------------------------------------------------------------
// Toast notifications
// ---------------------------------------------------------------------------
function showToast(type, title, message) {
  const container = document.getElementById("toastContainer");
  const toast = document.createElement("div");
  const icon = type === "success" ? "✅" : type === "error" ? "❌" : "ℹ️";
  toast.className = `toast ${type}`;
  toast.innerHTML = `
    <span class="toast-icon">${icon}</span>
    <div>
      <div class="toast-title">${esc(title)}</div>
      <div class="toast-msg">${esc(message)}</div>
    </div>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.classList.add("removing");
    toast.addEventListener("animationend", () => toast.remove());
  }, 4000);
}

// ---------------------------------------------------------------------------
// Utility
// ---------------------------------------------------------------------------
function esc(str) {
  if (str == null) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function formatDate(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
  } catch { return iso; }
}

function formatDateFull(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("en-GB", {
      day: "2-digit", month: "short", year: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  } catch { return iso; }
}

// Make functions globally accessible (called from inline onclick in dynamic HTML)
window.openReportModal = openReportModal;
window.changeStatus    = changeStatus;
window.resolveReport   = resolveReport;
window.requestReopen   = requestReopen;
