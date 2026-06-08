/* ─── Lumi Admin Dashboard ──────────────────────────────────── */

const API = '/api/admin';

const $ = (id) => document.getElementById(id);

let calls = [];
let selectedKey = null;
let searchTimer = null;

function fmtDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  });
}

function fmtDuration(secs) {
  if (secs == null || secs === '') return '—';
  const n = Number(secs);
  if (Number.isNaN(n)) return '—';
  const m = Math.floor(n / 60);
  const s = n % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function fmtBytes(bytes) {
  if (!bytes) return '';
  const n = Number(bytes);
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function yesNo(val) {
  return val ? 'Yes' : 'No';
}

function callStatus(row) {
  const val = String(row.call_successful || '').toLowerCase();
  if (['true', 'success', 'yes', '1'].includes(val)) return { label: 'Success', cls: 'pill-yes' };
  if (['false', 'failure', 'failed', 'no', '0'].includes(val)) return { label: 'Failed', cls: 'pill-err' };
  if (val) return { label: row.call_successful, cls: 'pill-warn' };
  return { label: row.status || '—', cls: 'pill-no' };
}

function billPill(count) {
  if (count > 0) return `<span class="pill pill-blue">${count} file${count > 1 ? 's' : ''}</span>`;
  return `<span class="pill pill-no">None</span>`;
}

function smsPill(sent) {
  return sent
    ? '<span class="pill pill-yes">Sent</span>'
    : '<span class="pill pill-no">No</span>';
}

async function loadCalls() {
  const q = $('search').value.trim();
  const filter = $('filter').value;
  const params = new URLSearchParams({ q, filter });

  $('calls-body').innerHTML = '<tr><td colspan="7" class="empty-row">Loading…</td></tr>';

  try {
    const res = await fetch(`${API}/calls?${params}`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    const data = await res.json();
    calls = data.calls || [];
    $('call-count').textContent = data.count;
    renderTable();
  } catch (err) {
    $('calls-body').innerHTML =
      `<tr><td colspan="7" class="empty-row">${esc(err.message)}</td></tr>`;
  }
}

function renderTable() {
  if (!calls.length) {
    $('calls-body').innerHTML = '<tr><td colspan="7" class="empty-row">No calls found</td></tr>';
    return;
  }

  $('calls-body').innerHTML = calls.map((row) => {
    const st = callStatus(row);
    const selected = row.row_key === selectedKey ? 'selected' : '';
    return `<tr data-key="${esc(row.row_key)}" class="${selected}">
      <td><strong>${esc(row.name || '—')}</strong></td>
      <td>${esc(row.dial_to || row.phone_no || '—')}</td>
      <td>${fmtDate(row.processed_at)}</td>
      <td>${fmtDuration(row.call_duration_secs)}</td>
      <td>${smsPill(row.sms_sent)}</td>
      <td>${billPill(row.bill_count || 0)}</td>
      <td><span class="pill ${st.cls}">${esc(st.label)}</span></td>
    </tr>`;
  }).join('');

  $('calls-body').querySelectorAll('tr[data-key]').forEach((tr) => {
    tr.addEventListener('click', () => selectCall(tr.dataset.key));
  });

  if (selectedKey && calls.some((c) => c.row_key === selectedKey)) {
    showDetail(calls.find((c) => c.row_key === selectedKey));
  }
}

async function selectCall(rowKey) {
  selectedKey = rowKey;
  renderTable();

  try {
    const res = await fetch(`${API}/calls/${encodeURIComponent(rowKey)}`);
    if (!res.ok) throw new Error('Could not load call details');
    showDetail(await res.json());
  } catch (err) {
    showDetail(calls.find((c) => c.row_key === rowKey));
  }
}

function showDetail(row) {
  if (!row) return;

  $('detail-empty').hidden = true;
  $('detail-content').hidden = false;

  const st = callStatus(row);
  $('detail-name').textContent = row.name || 'Unknown';
  const statusEl = $('detail-status');
  statusEl.textContent = st.label;
  statusEl.className = `status-pill pill ${st.cls}`;

  $('d-phone').textContent = row.phone_no || '—';
  $('d-dial').textContent = row.dial_to || '—';
  $('d-address').textContent = row.address || '—';
  $('d-date').textContent = fmtDate(row.processed_at);
  $('d-duration').textContent = fmtDuration(row.call_duration_secs);
  $('d-ended').textContent = fmtDate(row.call_ended_at);
  $('d-sms-eligible').textContent = yesNo(row.sms_eligible);
  $('d-sms-sent').textContent = yesNo(row.sms_sent);
  $('d-token-used').textContent = yesNo(row.upload_token_used);
  $('d-call-sid').textContent = row.call_sid || '—';
  $('d-conv-id').textContent = row.conversation_id || '—';
  $('d-termination').textContent = row.termination_reason || '—';
  $('d-transcript').textContent = row.transcript_summary || 'No summary available.';

  renderBills(row.bills || []);
  closePreview();
}

function renderBills(bills) {
  const el = $('bills-list');
  if (!bills.length) {
    el.innerHTML = '<p class="no-bills">No bill uploaded yet.</p>';
    return;
  }

  el.innerHTML = bills.map((b) => {
    const type = b.content_type || 'file';
    const meta = [fmtDate(b.uploaded_at), fmtBytes(b.size_bytes), b.status].filter(Boolean).join(' · ');
    return `<div class="bill-card">
      <div class="bill-info">
        <strong>${esc(b.original_name || 'Uploaded file')}</strong>
        <small>${esc(meta)} · ${esc(type)}</small>
      </div>
      <div class="bill-actions">
        <button type="button" class="btn-sm btn-sm-primary" data-view="${b.id}">View</button>
        <button type="button" class="btn-sm" data-dl="${b.id}">Download</button>
      </div>
    </div>`;
  }).join('');

  el.querySelectorAll('[data-view]').forEach((btn) => {
    btn.addEventListener('click', () => viewBill(Number(btn.dataset.view)));
  });
  el.querySelectorAll('[data-dl]').forEach((btn) => {
    btn.addEventListener('click', () => downloadBill(Number(btn.dataset.dl)));
  });
}

async function getSignedUrl(billId, download = false) {
  const params = download ? '?download=true' : '';
  const res = await fetch(`${API}/bills/${billId}/signed-url${params}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Could not get file URL');
  }
  return res.json();
}

async function viewBill(billId) {
  const container = $('preview-container');
  container.innerHTML = '<p class="no-bills" style="padding:20px">Loading preview…</p>';
  $('preview-block').hidden = false;

  try {
    const { url, content_type: type } = await getSignedUrl(billId, false);
    if (type.startsWith('image/')) {
      container.innerHTML = `<img src="${url}" alt="Bill preview" />`;
    } else if (type === 'application/pdf') {
      container.innerHTML = `<iframe src="${url}" title="Bill PDF"></iframe>`;
    } else {
      container.innerHTML = `<p class="no-bills" style="padding:20px">Preview not available for this file type. Use Download.</p>`;
    }
  } catch (err) {
    container.innerHTML = `<p class="no-bills" style="padding:20px;color:#DC2626">${esc(err.message)}</p>`;
  }
}

async function downloadBill(billId) {
  try {
    const { url } = await getSignedUrl(billId, true);
    window.open(url, '_blank');
  } catch (err) {
    alert(err.message);
  }
}

function closePreview() {
  $('preview-block').hidden = true;
  $('preview-container').innerHTML = '';
}

function esc(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

$('search').addEventListener('input', () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(loadCalls, 300);
});

$('filter').addEventListener('change', loadCalls);
$('btn-refresh').addEventListener('click', loadCalls);
$('btn-close-preview').addEventListener('click', closePreview);

loadCalls();
