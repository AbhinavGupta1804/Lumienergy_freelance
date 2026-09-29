/**
 * Google Apps Script — push new sheet rows to Lumi FastAPI + Zoho CRM.
 *
 * Setup (run once after pasting this file):
 *   1. Set WEBHOOK_URL and WEBHOOK_SECRET below
 *   2. Fill ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN
 *      (Zoho API Console → Self Client → generate refresh token with
 *       scope ZohoCRM.modules.leads.ALL,ZohoCRM.settings.ALL)
 *   3. Run setupSheetsWebhookTriggers() — authorize when prompted
 *   4. (Optional) Run testZohoConnection() then initializeLastProcessedRow()
 *   5. Submit a NEW form row or add a row at the bottom of the sheet
 *
 * Row 1 headers must include:
 *   First Name, Last Name, Address, Phone
 *   Transactional SMS Consent (Yes / No — only Yes allows bill-upload SMS)
 *   Bill Upload URL (written by the website on form submit)
 * Add an Email column when NOTIFICATION_CHANNEL=email on the server.
 *
 * Troubleshooting:
 *   - Run debugWebhookStatus() — shows lastProcessedRow vs sheet lastRow
 *   - Run processNewRows() manually to force-send pending rows
 *   - Re-run setupSheetsWebhookTriggers() if auto-trigger stopped after edits
 *   - Check Apps Script → Executions for errors
 *   - WEBHOOK_URL must match Cloud Run PUBLIC_BASE_URL + /webhooks/sheets/new-lead
 */

const WEBHOOK_URL = 'https://maya-unanemic-honey.ngrok-free.dev/webhooks/sheets/new-lead';
const WEBHOOK_SECRET = 'lumi-sheets-wh-8f3c2a9e1b7d4f6a0c5e8b2d9f1a4c7e';
const SHEET_NAME = 'Sheet1'; // must match GOOGLE_SHEETS_WORKSHEET_NAME in .env

// Zoho CRM — create a Lead on the "Lumi Solar" layout for every new sheet row.
// Leave client/secret/refresh empty to skip Zoho and keep the FastAPI webhook only.
const ZOHO_ENABLED = true;
const ZOHO_ACCOUNTS_URL = 'https://accounts.zoho.com';
const ZOHO_API_DOMAIN = 'https://www.zohoapis.com';
const ZOHO_CLIENT_ID = '1000.70J86ANBK67TFMSWX7OJ1VD8FW1OTS';
const ZOHO_CLIENT_SECRET = 'ab372a92a87b33d0057725d2ba17287b5c9fc5b83c';
const ZOHO_REFRESH_TOKEN = '1000.29fc14cb52666e64df63a262884b3b37.99444b60806a15769f6ab4ba6cbc6642';
const ZOHO_LAYOUT_NAME = 'Lumi Solar';
const ZOHO_LAYOUT_ID = '7529216000000693264'; // optional; auto-looked-up from ZOHO_LAYOUT_NAME if empty

const COLUMN_HEADERS = {
  first_name: 'First Name',
  last_name: 'Last Name',
  address: 'Address',
  phone_no: 'Phone',
  email: 'Email',
  transactional_sms_consent: 'Transactional SMS Consent',
  offer_page: 'Offer Page',
  monthly_bill: 'Monthly Bill',
  home_owner: 'Owns Home',
  roof_shade: 'Roof Shade',
  terms_privacy_consent: 'Terms & Privacy Consent',
  bill_upload_url: 'Bill Upload URL',
  existing_solar: 'Existing Solar',
  utility: 'Utility',
};

/**
 * Run once BEFORE go-live to ignore rows already on the sheet.
 * Only rows added AFTER this run will auto-trigger calls.
 */
function initializeLastProcessedRow() {
  const sheet = getLeadSheet_();
  const lastRow = Math.max(sheet.getLastRow(), 1);
  PropertiesService.getScriptProperties().setProperty('lastProcessedRow', String(lastRow));
  Logger.log('lastProcessedRow set to ' + lastRow + ' — existing rows will not be called');
}

/**
 * Install BOTH triggers (run after every script save if auto-trigger stopped working):
 *   - onChange  → row pasted / inserted / edited on sheet
 *   - onFormSubmit → Google Form linked to this spreadsheet
 */
function setupSheetsWebhookTriggers() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const triggers = ScriptApp.getProjectTriggers();
  for (let i = 0; i < triggers.length; i++) {
    const fn = triggers[i].getHandlerFunction();
    if (fn === 'onSheetChange' || fn === 'onFormSubmitHandler') {
      ScriptApp.deleteTrigger(triggers[i]);
    }
  }
  ScriptApp.newTrigger('onSheetChange')
    .forSpreadsheet(ss)
    .onChange()
    .create();
  ScriptApp.newTrigger('onFormSubmitHandler')
    .forSpreadsheet(ss)
    .onFormSubmit()
    .create();
  Logger.log('Installed onChange + onFormSubmit triggers');
}

/** @deprecated use setupSheetsWebhookTriggers */
function setupSheetsWebhookTrigger() {
  setupSheetsWebhookTriggers();
}

/** onChange installable trigger */
function onSheetChange(e) {
  Logger.log('onSheetChange fired changeType=' + (e && e.changeType ? e.changeType : 'unknown'));
  Utilities.sleep(800);
  withLeadLock_(function () {
    processNewRows_();
  });
}

/** onFormSubmit installable trigger — most reliable for Google Form leads */
function onFormSubmitHandler(e) {
  Logger.log('onFormSubmitHandler fired');
  Utilities.sleep(800);
  withLeadLock_(function () {
    if (e && e.range) {
      const row = e.range.getRow();
      Logger.log('Form submitted row ' + row);
      sendRowIfNew_(row);
      return;
    }
    processNewRows_();
  });
}

/**
 * Only one trigger may create Zoho + call FastAPI at a time.
 * Without this, Google Form submit fires BOTH onFormSubmit and onChange,
 * which creates 2 Zoho leads and 2 webhook POSTs for the same sheet row.
 */
function withLeadLock_(fn) {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(45000)) {
    Logger.log('Lead lock busy — skipping (another trigger is already processing)');
    return;
  }
  try {
    fn();
  } finally {
    lock.releaseLock();
  }
}

/** Manual: force-process any rows after lastProcessedRow */
function processNewRows() {
  withLeadLock_(function () {
    processNewRows_();
  });
}

/** Manual: log why rows may not be sending */
function debugWebhookStatus() {
  const props = PropertiesService.getScriptProperties();
  const lastProcessed = parseInt(props.getProperty('lastProcessedRow') || '1', 10);
  const sheet = getLeadSheet_();
  const lastRow = sheet.getLastRow();
  const startRow = Math.max(lastProcessed + 1, 2);
  Logger.log('Sheet: ' + sheet.getName());
  Logger.log('lastProcessedRow: ' + lastProcessed);
  Logger.log('sheet lastRow: ' + lastRow);
  Logger.log('next startRow: ' + startRow);
  Logger.log('pending rows: ' + Math.max(0, lastRow - startRow + 1));
  Logger.log('WEBHOOK_URL: ' + WEBHOOK_URL);
  Logger.log('Zoho configured: ' + isZohoConfigured_());
  const triggers = ScriptApp.getProjectTriggers();
  Logger.log('Triggers installed: ' + triggers.length);
  for (let i = 0; i < triggers.length; i++) {
    Logger.log('  - ' + triggers[i].getHandlerFunction() + ' (' + triggers[i].getEventType() + ')');
  }
}

function getLeadSheet_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(SHEET_NAME);
  if (!sheet) {
    throw new Error(
      'Sheet tab "' + SHEET_NAME + '" not found. Tabs: ' +
      ss.getSheets().map(function (s) { return s.getName(); }).join(', ')
    );
  }
  return sheet;
}

/**
 * If rows were deleted and lastProcessedRow is past the sheet end,
 * clamp it so new rows near the top of the sheet still get processed.
 */
function syncLastProcessedRow_(props, lastRow) {
  var lastProcessed = parseInt(props.getProperty('lastProcessedRow') || '1', 10);
  if (!isFinite(lastProcessed) || lastProcessed < 1) {
    lastProcessed = 1;
  }
  if (lastRow > 1 && lastProcessed >= lastRow) {
    var resetTo = Math.max(lastRow - 1, 1);
    Logger.log(
      'lastProcessedRow (' + lastProcessed + ') is past sheet lastRow (' + lastRow +
      ') — resetting to ' + resetTo
    );
    lastProcessed = resetTo;
    props.setProperty('lastProcessedRow', String(lastProcessed));
  }
  return lastProcessed;
}

function normalizeHeader_(header) {
  return String(header || '').trim().toLowerCase();
}

function buildHeaderIndex_(headers) {
  const index = {};
  for (let i = 0; i < headers.length; i++) {
    const key = normalizeHeader_(headers[i]);
    if (key) {
      index[key] = i;
    }
  }
  return index;
}

function getCellByHeader_(rowValues, headerIndex, headerName) {
  const idx = headerIndex[normalizeHeader_(headerName)];
  if (idx === undefined) {
    return '';
  }
  return String(rowValues[idx] || '').trim();
}

function extractLeadFields_(rowValues, headerIndex) {
  return {
    first_name: getCellByHeader_(rowValues, headerIndex, COLUMN_HEADERS.first_name),
    last_name: getCellByHeader_(rowValues, headerIndex, COLUMN_HEADERS.last_name),
    address: getCellByHeader_(rowValues, headerIndex, COLUMN_HEADERS.address),
    phone_no: getCellByHeader_(rowValues, headerIndex, COLUMN_HEADERS.phone_no),
    email: getCellByHeader_(rowValues, headerIndex, COLUMN_HEADERS.email),
    transactional_sms_consent: getCellByHeader_(
      rowValues,
      headerIndex,
      COLUMN_HEADERS.transactional_sms_consent
    ),
    offer_page: getCellByHeader_(rowValues, headerIndex, COLUMN_HEADERS.offer_page),
    monthly_bill: getCellByHeader_(rowValues, headerIndex, COLUMN_HEADERS.monthly_bill),
    home_owner: getCellByHeader_(rowValues, headerIndex, COLUMN_HEADERS.home_owner),
    roof_shade: getCellByHeader_(rowValues, headerIndex, COLUMN_HEADERS.roof_shade),
    terms_privacy_consent: getCellByHeader_(
      rowValues,
      headerIndex,
      COLUMN_HEADERS.terms_privacy_consent
    ),
    bill_upload_url: getCellByHeader_(rowValues, headerIndex, COLUMN_HEADERS.bill_upload_url),
    existing_solar: getCellByHeader_(rowValues, headerIndex, COLUMN_HEADERS.existing_solar),
    utility: getCellByHeader_(rowValues, headerIndex, COLUMN_HEADERS.utility),
  };
}

function getHeaderContext_(sheet) {
  const lastCol = Math.max(sheet.getLastColumn(), 1);
  const headers = sheet.getRange(1, 1, 1, lastCol).getValues()[0];
  const headerIndex = buildHeaderIndex_(headers);
  const required = [
    COLUMN_HEADERS.first_name,
    COLUMN_HEADERS.last_name,
    COLUMN_HEADERS.address,
    COLUMN_HEADERS.phone_no,
  ];
  for (let i = 0; i < required.length; i++) {
    if (headerIndex[normalizeHeader_(required[i])] === undefined) {
      throw new Error('Missing required header: ' + required[i] + '. Found: ' + headers.join(', '));
    }
  }
  return { lastCol: lastCol, headerIndex: headerIndex };
}

function readRowValues_(sheet, row, lastCol) {
  // getRange(row, col, numRows, numColumns) — read one full data row
  return sheet.getRange(row, 1, 1, lastCol).getValues()[0];
}

function postLeadWebhook_(row, fields, zohoLeadId) {
  const payload = {
    row_number: row,
    first_name: fields.first_name,
    last_name: fields.last_name,
    address: fields.address,
    phone_no: fields.phone_no,
    email: fields.email,
    transactional_sms_consent: fields.transactional_sms_consent,
    offer_page: fields.offer_page,
    monthly_bill: fields.monthly_bill,
    zoho_lead_id: zohoLeadId || '',
    bill_upload_url: fields.bill_upload_url,
    existing_solar: fields.existing_solar,
    utility: fields.utility,
    home_owner: fields.home_owner,
    terms_privacy_consent: fields.terms_privacy_consent,
  };
  const options = {
    method: 'post',
    contentType: 'application/json',
    headers: { 'X-Sheets-Webhook-Secret': WEBHOOK_SECRET },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true,
  };
  const resp = UrlFetchApp.fetch(WEBHOOK_URL, options);
  return { code: resp.getResponseCode(), body: resp.getContentText() };
}

function sendRowIfNew_(row) {
  if (row < 2) {
    return;
  }
  const props = PropertiesService.getScriptProperties();
  const sheet = getLeadSheet_();
  const lastProcessed = syncLastProcessedRow_(props, sheet.getLastRow());
  if (row <= lastProcessed) {
    Logger.log('Row ' + row + ' already processed (lastProcessedRow=' + lastProcessed + ') — skip');
    return;
  }

  const ctx = getHeaderContext_(sheet);
  const values = readRowValues_(sheet, row, ctx.lastCol);
  const fields = extractLeadFields_(values, ctx.headerIndex);

  if (!fields.first_name && !fields.last_name && !fields.address && !fields.phone_no) {
    Logger.log('Row ' + row + ' is empty — skip');
    return;
  }

  dispatchNewLead_(row, fields, props, true);
}

function processNewRows_() {
  const props = PropertiesService.getScriptProperties();
  const sheet = getLeadSheet_();
  const lastRow = sheet.getLastRow();
  if (lastRow <= 1) {
    Logger.log('No data rows on sheet');
    return;
  }

  const lastProcessed = syncLastProcessedRow_(props, lastRow);
  const ctx = getHeaderContext_(sheet);
  const startRow = Math.max(lastProcessed + 1, 2);
  Logger.log('processNewRows_ lastProcessed=' + lastProcessed + ' startRow=' + startRow + ' lastRow=' + lastRow);

  if (startRow > lastRow) {
    Logger.log('No new rows to process');
    return;
  }

  for (let row = startRow; row <= lastRow; row++) {
    const values = readRowValues_(sheet, row, ctx.lastCol);
    const fields = extractLeadFields_(values, ctx.headerIndex);

    if (!fields.first_name && !fields.last_name && !fields.address && !fields.phone_no) {
      Logger.log('Row ' + row + ' empty — skip');
      continue;
    }

    const ok = dispatchNewLead_(row, fields, props, false);
    if (!ok) {
      break;
    }
  }
}

function dispatchNewLead_(row, fields, props, throwOnWebhookFail) {
  const zoho = createZohoLead_(row, fields);
  if (zoho.error) {
    Logger.log('WARNING Zoho lead failed row ' + row + ': ' + zoho.error);
    // Fail the run so Apps Script Executions shows the Zoho error clearly.
    throw new Error('Zoho lead failed row ' + row + ': ' + zoho.error);
  } else if (zoho.skipped) {
    Logger.log('Zoho skipped row ' + row + ': ' + zoho.skipped);
  } else {
    Logger.log(
      'Zoho lead ' + (zoho.created ? 'created' : 'exists') +
      ' row ' + row + ' id=' + zoho.id
    );
  }

  const zohoId = (zoho && zoho.id) ? String(zoho.id) : '';
  const result = postLeadWebhook_(row, fields, zohoId);
  if (result.code >= 200 && result.code < 300) {
    props.setProperty('lastProcessedRow', String(row));
    Logger.log('Webhook OK row ' + row + ': ' + result.body);
    return true;
  }

  Logger.log('Webhook FAILED row ' + row + ' HTTP ' + result.code + ': ' + result.body);
  if (throwOnWebhookFail) {
    throw new Error('Webhook failed HTTP ' + result.code + ': ' + result.body);
  }
  return false;
}

// ---------------------------------------------------------------------------
// Zoho CRM
// ---------------------------------------------------------------------------

function isZohoConfigured_() {
  return !!(
    ZOHO_ENABLED &&
    String(ZOHO_CLIENT_ID || '').trim() &&
    String(ZOHO_CLIENT_SECRET || '').trim() &&
    String(ZOHO_REFRESH_TOKEN || '').trim()
  );
}

function parseMonthlyBillAmount_(value) {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  if (typeof value === 'number' && value > 0) {
    return value;
  }
  const raw = String(value).trim();
  if (!raw) {
    return null;
  }
  const buckets = {
    under_100: 100,
    '100_150': 150,
    '150_200': 200,
    '200_300': 250,
    '300_400': 350,
    '400_plus': 500,
  };
  const key = raw.toLowerCase().replace(/ /g, '_').replace(/-/g, '_');
  if (buckets[key]) {
    return buckets[key];
  }
  const amount = parseFloat(raw.replace(/[$,]/g, '').trim());
  return amount > 0 ? amount : null;
}

function getZohoAccessToken_() {
  const props = PropertiesService.getScriptProperties();
  const cached = props.getProperty('zohoAccessToken') || '';
  const expiresAt = parseInt(props.getProperty('zohoAccessTokenExpiresAt') || '0', 10);
  if (cached && Date.now() < expiresAt - 60000) {
    return cached;
  }

  const resp = UrlFetchApp.fetch(ZOHO_ACCOUNTS_URL + '/oauth/v2/token', {
    method: 'post',
    payload: {
      grant_type: 'refresh_token',
      client_id: ZOHO_CLIENT_ID,
      client_secret: ZOHO_CLIENT_SECRET,
      refresh_token: ZOHO_REFRESH_TOKEN,
    },
    muteHttpExceptions: true,
  });
  const code = resp.getResponseCode();
  const body = resp.getContentText();
  if (code < 200 || code >= 300) {
    throw new Error('Zoho token refresh HTTP ' + code + ': ' + body);
  }
  const json = JSON.parse(body);
  if (!json.access_token) {
    throw new Error('Zoho token refresh missing access_token: ' + body);
  }
  const ttlMs = (parseInt(json.expires_in, 10) || 3600) * 1000;
  props.setProperty('zohoAccessToken', json.access_token);
  props.setProperty('zohoAccessTokenExpiresAt', String(Date.now() + ttlMs));
  if (json.api_domain) {
    props.setProperty('zohoApiDomain', json.api_domain);
  }
  return json.access_token;
}

function zohoApiDomain_() {
  const stored = PropertiesService.getScriptProperties().getProperty('zohoApiDomain');
  return (stored || ZOHO_API_DOMAIN).replace(/\/$/, '');
}

function zohoFetch_(path, options) {
  const token = getZohoAccessToken_();
  const merged = options || {};
  merged.muteHttpExceptions = true;
  merged.headers = merged.headers || {};
  merged.headers.Authorization = 'Zoho-oauthtoken ' + token;
  const resp = UrlFetchApp.fetch(zohoApiDomain_() + path, merged);
  return {
    code: resp.getResponseCode(),
    body: resp.getContentText(),
  };
}

function getZohoLayoutId_() {
  if (ZOHO_LAYOUT_ID) {
    return ZOHO_LAYOUT_ID;
  }
  const props = PropertiesService.getScriptProperties();
  const cached = props.getProperty('zohoLayoutId');
  if (cached) {
    return cached;
  }
  const result = zohoFetch_('/crm/v8/settings/layouts?module=Leads', { method: 'get' });
  if (result.code < 200 || result.code >= 300) {
    Logger.log('Zoho layout lookup skipped HTTP ' + result.code + ': ' + result.body);
    return '';
  }
  const json = JSON.parse(result.body);
  const layouts = json.layouts || [];
  const wanted = String(ZOHO_LAYOUT_NAME || '').trim().toLowerCase();
  for (let i = 0; i < layouts.length; i++) {
    if (String(layouts[i].name || '').trim().toLowerCase() === wanted) {
      props.setProperty('zohoLayoutId', layouts[i].id);
      return layouts[i].id;
    }
  }
  Logger.log(
    'Zoho layout "' + ZOHO_LAYOUT_NAME + '" not found. Layouts: ' +
    layouts.map(function (l) { return l.name; }).join(', ')
  );
  return '';
}

function isValidEmail_(value) {
  const email = String(value || '').trim();
  // Simple check — Zoho rejects anything that is not a real email shape
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

function isValidWebsiteUrl_(value) {
  const url = String(value || '').trim();
  // Zoho Website fields need a real http(s) URL with a host (e.g. https://a.com/...)
  if (!/^https?:\/\/.+/i.test(url)) {
    return false;
  }
  try {
    // Apps Script has no URL() in older runtimes — parse host manually
    const withoutProtocol = url.replace(/^https?:\/\//i, '').split('/')[0].split('?')[0];
    const host = withoutProtocol.split('@').pop(); // drop userinfo if any
    if (!host || host.indexOf('.') === -1) {
      return false;
    }
    // Reject obvious junk hosts
    if (host === '.' || host.indexOf('..') !== -1) {
      return false;
    }
    return true;
  } catch (e) {
    return false;
  }
}

function normalizeHomeOwnerPicklist_(value) {
  const raw = String(value || '').trim();
  if (!raw) {
    return '';
  }
  const lower = raw.toLowerCase();
  if (
    lower === 'yes' || lower === 'y' || lower === 'true' || lower === '1' ||
    lower === 'owner' || lower === 'homeowner' || lower.indexOf('own') !== -1
  ) {
    return 'Yes';
  }
  if (
    lower === 'no' || lower === 'n' || lower === 'false' || lower === '0' ||
    lower === 'renter' || lower === 'rent' || lower === 'tenant'
  ) {
    return 'No';
  }
  return raw;
}

function buildZohoLeadRecord_(row, fields) {
  const lastName = fields.last_name || fields.first_name || 'Unknown';
  const email = String(fields.email || '').trim();
  const phone = String(fields.phone_no || '').trim();

  // Always keep raw contact values in Description so nothing is lost if
  // Zoho rejects the typed Email/Phone fields.
  var descriptionParts = ['Imported from Google Sheet row ' + row];
  if (email) {
    descriptionParts.push('Email provided: ' + email);
  }
  if (phone) {
    descriptionParts.push('Phone provided: ' + phone);
  }

  // API names match Zoho Leads → Lumi Solar layout Developer Hub
  const record = {
    First_Name: fields.first_name || '',
    Last_Name: lastName,
    Addressss: fields.address || '',
    Offer_page: fields.offer_page || '',
    Sms_consent: fields.transactional_sms_consent || '',
    Description: descriptionParts.join('\n'),
  };

  // Always send whatever the lead typed — Zoho may reject; createZohoLead_ retries without them.
  if (phone) {
    record.Phone = phone;
  }
  if (email) {
    record.Email = email;
  }

  const layoutId = getZohoLayoutId_();
  if (layoutId) {
    record.Layout = { id: layoutId };
  }
  const bill = parseMonthlyBillAmount_(fields.monthly_bill);
  if (bill !== null) {
    record.Electric_Bill = bill;
  }
  const homeOwner = normalizeHomeOwnerPicklist_(fields.home_owner);
  if (homeOwner === 'Yes' || homeOwner === 'No') {
    record.Home_Owner1 = homeOwner;
  }
  if (fields.roof_shade) {
    record.Roof_shade = fields.roof_shade;
  }
  if (fields.terms_privacy_consent) {
    record.Terms_privacy_consent = fields.terms_privacy_consent;
  }
  if (fields.utility) {
    record.Utility = fields.utility;
  }
  if (fields.existing_solar) {
    record.Existing_solar = fields.existing_solar;
  }
  if (isValidWebsiteUrl_(fields.bill_upload_url)) {
    record.Bill_Upload_URL = String(fields.bill_upload_url).trim();
  } else if (fields.bill_upload_url) {
    Logger.log(
      'Skip Zoho Bill_Upload_URL — not a http(s) URL: ' +
      JSON.stringify(fields.bill_upload_url)
    );
  }
  return record;
}

function zohoCreateLeadRequest_(record) {
  return zohoFetch_('/crm/v8/Leads', {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify({
      data: [record],
      trigger: ['workflow', 'approval', 'blueprint'],
    }),
  });
}

function zohoCreateErrorApiName_(result) {
  try {
    const json = JSON.parse(result.body || '{}');
    const first = (json.data && json.data[0]) || {};
    if (first.details && first.details.api_name) {
      return String(first.details.api_name);
    }
  } catch (e) {
    // fall through
  }
  const body = String(result.body || '');
  if (body.indexOf('"api_name":"Email"') !== -1 || body.indexOf('"api_name": "Email"') !== -1) {
    return 'Email';
  }
  if (body.indexOf('"api_name":"Phone"') !== -1 || body.indexOf('"api_name": "Phone"') !== -1) {
    return 'Phone';
  }
  if (body.indexOf('Bill_Upload_URL') !== -1) {
    return 'Bill_Upload_URL';
  }
  return '';
}

function parseZohoCreateSuccess_(result) {
  if (result.code < 200 || result.code >= 300) {
    return { error: 'HTTP ' + result.code + ': ' + result.body };
  }
  try {
    const json = JSON.parse(result.body);
    const first = (json.data && json.data[0]) || {};
    if (first.status === 'error') {
      return {
        error: JSON.stringify(first),
        apiName: (first.details && first.details.api_name) || '',
      };
    }
    const details = first.details || {};
    if (!details.id) {
      return { error: result.body };
    }
    return { id: String(details.id), created: true };
  } catch (err) {
    return { error: String(err && err.message ? err.message : err) };
  }
}

function createZohoLead_(row, fields) {
  if (!ZOHO_ENABLED) {
    return { skipped: 'ZOHO_ENABLED is false' };
  }
  if (!isZohoConfigured_()) {
    return {
      skipped: 'set ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, and ZOHO_REFRESH_TOKEN',
    };
  }
  try {
    var record = buildZohoLeadRecord_(row, fields);
    var result = zohoCreateLeadRequest_(record);
    var parsed = parseZohoCreateSuccess_(result);

    // Strip fields Zoho rejects for format (Email / Phone / Bill_Upload_URL) and retry.
    // Raw email/phone remain in Description.
    var stripable = { Email: true, Phone: true, Bill_Upload_URL: true };
    var attempts = 0;
    while (parsed.error && attempts < 3) {
      var apiName = parsed.apiName || zohoCreateErrorApiName_(result);
      if (!apiName || !stripable[apiName] || record[apiName] === undefined) {
        break;
      }
      Logger.log(
        'Zoho rejected ' + apiName + '=' + JSON.stringify(record[apiName]) +
        ' — retrying create without it (value kept in Description when contact field)'
      );
      delete record[apiName];
      result = zohoCreateLeadRequest_(record);
      parsed = parseZohoCreateSuccess_(result);
      attempts++;
    }

    if (parsed.error) {
      return { error: parsed.error };
    }
    return { id: parsed.id, created: true };
  } catch (err) {
    return { error: String(err && err.message ? err.message : err) };
  }
}

/** Manual: verify Zoho OAuth + Lumi Solar layout lookup */
function testZohoConnection() {
  if (!isZohoConfigured_()) {
    throw new Error('Fill ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, and ZOHO_REFRESH_TOKEN first');
  }
  const token = getZohoAccessToken_();
  Logger.log('Access token ok (len=' + token.length + ')');
  const layoutId = getZohoLayoutId_();
  Logger.log('Layout "' + ZOHO_LAYOUT_NAME + '" id=' + (layoutId || '(default — settings scope not granted)'));
}



