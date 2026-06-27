/* ─── Lumi Admin Dashboard ──────────────────────────────────── */

const API = '/api/admin';

const $ = (id) => document.getElementById(id);

const CALL_FILTERS = [
  { value: 'all', label: 'All calls' },
  { value: 'bill_uploaded', label: 'Bill uploaded' },
  { value: 'no_bill', label: 'No bill' },
  { value: 'sms_sent', label: 'SMS sent' },
  { value: 'call_failed', label: 'Call failed' },
  { value: 'callback_active', label: 'Callback scheduled' },
];

const MESSAGE_FILTERS = [
  { value: 'all', label: 'All messages' },
  { value: 'inbound', label: 'Inbound only' },
  { value: 'outbound', label: 'Outbound only' },
  { value: 'sms', label: 'SMS only' },
  { value: 'email', label: 'Email only' },
];

let activeTab = 'calls';
let calls = [];
let messages = [];
let selectedKey = null;
let selectedMessageId = null;
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

function esc(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function truncate(str, max = 80) {
  const s = String(str || '');
  if (s.length <= max) return s;
  return `${s.slice(0, max)}…`;
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

function callbackPill(row) {
  const st = (row.callback_status || 'none').toLowerCase();
  if (st === 'answered') return '<span class="pill pill-yes">Answered</span>';
  if (st === 'active') {
    const next = row.next_retry_at ? fmtDate(row.next_retry_at) : 'pending';
    return `<span class="pill pill-warn">Active · ${esc(next)}</span>`;
  }
  if (st === 'exhausted') return '<span class="pill pill-err">Exhausted</span>';
  return '<span class="pill pill-no">—</span>';
}

function smsPill(sent) {
  return sent
    ? '<span class="pill pill-yes">Sent</span>'
    : '<span class="pill pill-no">No</span>';
}

function directionPill(direction) {
  const d = (direction || '').toLowerCase();
  if (d === 'inbound') {
    return '<span class="pill pill-inbound">Inbound</span>';
  }
  return '<span class="pill pill-outbound">Outbound</span>';
}

function messageTypeLabel(type) {
  const map = {
    bill_upload: 'Bill upload link',
    confirmation: 'Confirmation',
    inbound_reply: 'Customer reply',
    general: 'General',
  };
  return map[type] || type || '—';
}

function populateFilterOptions() {
  const options = activeTab === 'calls' ? CALL_FILTERS : MESSAGE_FILTERS;
  $('filter').innerHTML = options
    .map((o, i) => `<option value="${esc(o.value)}"${i === 0 ? ' selected' : ''}>${esc(o.label)}</option>`)
    .join('');
  if (!$('filter').value && options.length) {
    $('filter').value = options[0].value;
  }
}

function switchTab(tab) {
  activeTab = tab;
  document.querySelectorAll('.tab').forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.tab === tab);
  });

  $('calls-view').hidden = tab !== 'calls';
  $('messages-view').hidden = tab !== 'messages';
  $('page-subtitle').textContent = tab === 'calls' ? 'Call Dashboard' : 'Message Log';
  $('search').placeholder = tab === 'calls'
    ? 'Search name, phone, address…'
    : 'Search message, phone, email, lead…';

  populateFilterOptions();
  $('search').value = '';
  refreshActiveTab();
}

function refreshActiveTab() {
  if (activeTab === 'calls') {
    loadCalls();
  } else {
    loadMessages();
  }
}

async function loadCalls() {
  const q = $('search').value.trim();
  const filter = $('filter').value || 'all';
  const params = new URLSearchParams({ q, filter });

  $('calls-body').innerHTML = '<tr><td colspan="8" class="empty-row">Loading…</td></tr>';

  try {
    const res = await fetch(`${API}/calls?${params}`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    const data = await res.json();
    calls = data.calls || [];
    $('call-count').textContent = data.count;
    renderCallsTable();
  } catch (err) {
    $('calls-body').innerHTML =
      `<tr><td colspan="8" class="empty-row">${esc(err.message)}</td></tr>`;
  }
}

function renderCallsTable() {
  if (!calls.length) {
    $('calls-body').innerHTML = '<tr><td colspan="8" class="empty-row">No calls found</td></tr>';
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
      <td>${callbackPill(row)}</td>
      <td>${billPill(row.bill_count || 0)}</td>
      <td><span class="pill ${st.cls}">${esc(st.label)}</span></td>
    </tr>`;
  }).join('');

  $('calls-body').querySelectorAll('tr[data-key]').forEach((tr) => {
    tr.addEventListener('click', () => selectCall(tr.dataset.key));
  });

  if (selectedKey && calls.some((c) => c.row_key === selectedKey)) {
    showCallDetail(calls.find((c) => c.row_key === selectedKey));
  }
}

async function selectCall(rowKey) {
  selectedKey = rowKey;
  renderCallsTable();

  try {
    const res = await fetch(`${API}/calls/${encodeURIComponent(rowKey)}`);
    if (!res.ok) throw new Error('Could not load call details');
    showCallDetail(await res.json());
  } catch (err) {
    showCallDetail(calls.find((c) => c.row_key === rowKey));
  }
}

function showCallDetail(row) {
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
  $('d-callback-status').textContent = row.callback_status || '—';
  $('d-callback-attempt').textContent = row.callback_attempt != null ? String(row.callback_attempt) : '—';
  $('d-next-retry').textContent = fmtDate(row.next_retry_at);
  $('d-twilio-status').textContent = row.last_twilio_status || '—';
  $('d-in-progress').textContent = yesNo(row.call_in_progress);
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

async function loadMessages() {
  const q = $('search').value.trim();
  const filter = $('filter').value;
  const params = new URLSearchParams({ q });

  if (filter === 'inbound' || filter === 'outbound') {
    params.set('direction', filter);
  } else if (filter === 'sms' || filter === 'email') {
    params.set('channel', filter);
  }

  $('messages-body').innerHTML = '<tr><td colspan="8" class="empty-row">Loading…</td></tr>';

  try {
    const res = await fetch(`${API}/messages?${params}`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    const data = await res.json();
    messages = data.messages || [];
    $('message-count').textContent = data.count;
    renderMessagesTable();
  } catch (err) {
    $('messages-body').innerHTML =
      `<tr><td colspan="8" class="empty-row">${esc(err.message)}</td></tr>`;
  }
}

function renderMessagesTable() {
  if (!messages.length) {
    $('messages-body').innerHTML = '<tr><td colspan="8" class="empty-row">No messages found</td></tr>';
    return;
  }

  $('messages-body').innerHTML = messages.map((row) => {
    const selected = row.id === selectedMessageId ? 'selected' : '';
    return `<tr data-id="${row.id}" class="${selected}">
      <td>${directionPill(row.direction)}</td>
      <td>${esc((row.channel || '—').toUpperCase())}</td>
      <td>${esc(messageTypeLabel(row.message_type))}</td>
      <td><strong>${esc(row.lead_name || '—')}</strong></td>
      <td>${esc(row.from_address || '—')}</td>
      <td>${esc(row.to_address || '—')}</td>
      <td class="message-preview">${esc(truncate(row.body, 90))}</td>
      <td>${fmtDate(row.created_at)}</td>
    </tr>`;
  }).join('');

  $('messages-body').querySelectorAll('tr[data-id]').forEach((tr) => {
    tr.addEventListener('click', () => selectMessage(Number(tr.dataset.id)));
  });

  if (selectedMessageId) {
    const row = messages.find((m) => m.id === selectedMessageId);
    if (row) showMessageDetail(row);
  }
}

function selectMessage(id) {
  selectedMessageId = id;
  renderMessagesTable();
  const row = messages.find((m) => m.id === id);
  showMessageDetail(row);
}

function showMessageDetail(row) {
  if (!row) return;

  $('message-detail-empty').hidden = true;
  $('message-detail-content').hidden = false;

  const dir = (row.direction || '').toLowerCase();
  $('msg-detail-title').textContent = row.lead_name || 'Message';
  const dirEl = $('msg-detail-direction');
  dirEl.innerHTML = directionPill(dir);
  dirEl.className = 'status-pill';

  $('m-channel').textContent = (row.channel || '—').toUpperCase();
  $('m-type').textContent = messageTypeLabel(row.message_type);
  $('m-lead').textContent = row.lead_name || row.lead_row_key || '—';
  $('m-from').textContent = row.from_address || '—';
  $('m-to').textContent = row.to_address || '—';
  $('m-status').textContent = row.status || '—';
  $('m-date').textContent = fmtDate(row.created_at);
  $('m-provider').textContent = row.provider_id || '—';
  $('m-call-sid').textContent = row.call_sid || '—';
  $('m-body').textContent = row.body || '—';
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
      container.innerHTML = '<p class="no-bills" style="padding:20px">Preview not available for this file type. Use Download.</p>';
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

document.querySelectorAll('.tab').forEach((btn) => {
  btn.addEventListener('click', () => switchTab(btn.dataset.tab));
});

$('search').addEventListener('input', () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(refreshActiveTab, 300);
});

$('filter').addEventListener('change', refreshActiveTab);
$('btn-refresh').addEventListener('click', refreshActiveTab);
$('btn-close-preview').addEventListener('click', closePreview);

populateFilterOptions();
loadCalls();
