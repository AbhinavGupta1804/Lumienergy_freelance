/**
 * Google Apps Script — create a Lumi Lights Zoho lead, then notify the webhook.
 *
 * Share the sheet with the service account is separate; this script only creates the CRM lead and notifies the Lumi Lights webhook.
 *
 * Setup (run once after pasting this file):
 *   1. Set WEBHOOK_URL and WEBHOOK_SECRET below
 *   2. Run testZohoConnection() — authorize when prompted
 *   3. Run setupSheetsWebhookTriggers()
 *   4. Run initializeLastProcessedRow() so rows already on the sheet are not sent
 *   5. Add a new row, or submit the linked Google Form
 *
 * Sheet tab: Sheet1
 * Row 1 headers: Name, Email, Phone, Address
 * Also read when present: Offer Page, SMS Consent, T&C Consent, Submitted, Business Unit,
 *   Homeowner, Cares most about, Budget, Notes, Other
 *
 * Troubleshooting:
 *   - Run debugWebhookStatus() to compare lastProcessedRow with the sheet
 *   - Run processNewRows() to send pending rows
 *   - Re-run setupSheetsWebhookTriggers() if the automatic trigger stops after an edit
 */

const WEBHOOK_URL = 'https://arizona-solar-581026638648.us-west4.run.app/webhooks/sheets/lights/new-lead';
const WEBHOOK_SECRET = 'lumi-sheets-wh-8f3c2a9e1b7d4f6a0c5e8b2d9f1a4c7e';
const SHEET_NAME = 'Sheet1';
const BUSINESS_UNIT = 'Lumi Lights';

const ZOHO_ENABLED = true;
const ZOHO_ACCOUNTS_URL = 'https://accounts.zoho.com';
const ZOHO_API_DOMAIN = 'https://www.zohoapis.com';
const ZOHO_CLIENT_ID = '1000.70J86ANBK67TFMSWX7OJ1VD8FW1OTS';
const ZOHO_CLIENT_SECRET = 'ab372a92a87b33d0057725d2ba17287b5c9fc5b83c';
const ZOHO_REFRESH_TOKEN = '1000.29fc14cb52666e64df63a262884b3b37.99444b60806a15769f6ab4ba6cbc6642';
const ZOHO_LAYOUT_NAME = 'Lumi Lights';
const ZOHO_LAYOUT_ID = '7529216000001933001';

const COLUMN_HEADERS = {
  name: 'Name',
  email: 'Email',
  phone: 'Phone',
  address: 'Address',
  offer_page: 'Offer Page',
  sms_consent: 'SMS Consent',
  tc_consent: 'T&C Consent',
  submitted: 'Submitted',
  business_unit: 'Business Unit',
  homeowner: 'Homeowner',
  cares_most_about: 'Cares most about',
  budget: 'Budget',
  notes: 'Notes',
  other: 'Other',
};

/**
 * Run once before go-live so rows already on the sheet are not sent.
 * Only rows added after this run are posted.
 */
function initializeLastProcessedRow() {
  const sheet = getLeadSheet_();
  const lastRow = Math.max(sheet.getLastRow(), 1);
  PropertiesService.getScriptProperties().setProperty('lastProcessedRow', String(lastRow));
  Logger.log('lastProcessedRow set to ' + lastRow + ' — existing rows will not be sent');
}

/**
 * Install both triggers:
 *   - onChange for a row pasted, inserted, or edited on the sheet
 *   - onFormSubmit for a Google Form linked to this spreadsheet
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

/** onChange installable trigger */
function onSheetChange(e) {
  Logger.log('onSheetChange fired changeType=' + (e && e.changeType ? e.changeType : 'unknown'));
  Utilities.sleep(800);
  withLeadLock_(function () {
    processNewRows_();
  });
}

/** onFormSubmit installable trigger */
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
 * A linked form fires both onFormSubmit and onChange.
 * The lock lets only one of them post a given row.
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

/** Manual: post any rows after lastProcessedRow */
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
  Logger.log('WEBHOOK_URL set: ' + (WEBHOOK_URL ? 'yes' : 'no'));
  Logger.log('Zoho configured: ' + isZohoConfigured_());
  Logger.log('Zoho layout: ' + ZOHO_LAYOUT_NAME);
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
 * If rows were deleted and lastProcessedRow is past the end of the sheet,
 * clamp it to the current last row. Equal means that row was already sent.
 */
function syncLastProcessedRow_(props, lastRow) {
  var lastProcessed = parseInt(props.getProperty('lastProcessedRow') || '1', 10);
  if (!isFinite(lastProcessed) || lastProcessed < 1) {
    lastProcessed = 1;
  }
  if (lastRow > 1 && lastProcessed > lastRow) {
    Logger.log(
      'lastProcessedRow (' + lastProcessed + ') is past sheet lastRow (' + lastRow +
      ') — resetting to ' + lastRow
    );
    lastProcessed = lastRow;
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
    name: getCellByHeader_(rowValues, headerIndex, COLUMN_HEADERS.name),
    email: getCellByHeader_(rowValues, headerIndex, COLUMN_HEADERS.email),
    phone: getCellByHeader_(rowValues, headerIndex, COLUMN_HEADERS.phone),
    address: getCellByHeader_(rowValues, headerIndex, COLUMN_HEADERS.address),
    offer_page: getCellByHeader_(rowValues, headerIndex, COLUMN_HEADERS.offer_page),
    sms_consent: getCellByHeader_(rowValues, headerIndex, COLUMN_HEADERS.sms_consent),
    tc_consent: getCellByHeader_(rowValues, headerIndex, COLUMN_HEADERS.tc_consent),
    submitted: getCellByHeader_(rowValues, headerIndex, COLUMN_HEADERS.submitted),
    business_unit: BUSINESS_UNIT,
    homeowner: getCellByHeader_(rowValues, headerIndex, COLUMN_HEADERS.homeowner),
    cares_most_about: getCellByHeader_(rowValues, headerIndex, COLUMN_HEADERS.cares_most_about),
    budget: getCellByHeader_(rowValues, headerIndex, COLUMN_HEADERS.budget),
    notes: getCellByHeader_(rowValues, headerIndex, COLUMN_HEADERS.notes),
    other: getCellByHeader_(rowValues, headerIndex, COLUMN_HEADERS.other),
  };
}

function isEmptyLead_(fields) {
  return !fields.name && !fields.email && !fields.phone && !fields.address;
}

function getHeaderContext_(sheet) {
  const lastCol = Math.max(sheet.getLastColumn(), 1);
  const headers = sheet.getRange(1, 1, 1, lastCol).getValues()[0];
  const headerIndex = buildHeaderIndex_(headers);
  const required = [
    COLUMN_HEADERS.name,
    COLUMN_HEADERS.email,
    COLUMN_HEADERS.phone,
    COLUMN_HEADERS.address,
  ];
  for (let i = 0; i < required.length; i++) {
    if (headerIndex[normalizeHeader_(required[i])] === undefined) {
      throw new Error('Missing required header: ' + required[i] + '. Found: ' + headers.join(', '));
    }
  }
  return { lastCol: lastCol, headerIndex: headerIndex };
}

function readRowValues_(sheet, row, lastCol) {
  return sheet.getRange(row, 1, 1, lastCol).getValues()[0];
}

function postLeadWebhook_(row, fields, zohoLeadId) {
  if (!WEBHOOK_URL) {
    throw new Error('WEBHOOK_URL is empty');
  }
  const payload = {
    row_number: row,
    name: fields.name,
    email: fields.email,
    phone: fields.phone,
    address: fields.address,
    offer_page: fields.offer_page,
    sms_consent: fields.sms_consent,
    tc_consent: fields.tc_consent,
    submitted: fields.submitted,
    Business_unit: BUSINESS_UNIT,
    zoho_lead_id: zohoLeadId || '',
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
  if (isEmptyLead_(fields)) {
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
    if (isEmptyLead_(fields)) {
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
    Logger.log('Zoho lead failed row ' + row + ': ' + zoho.error);
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

function isZohoConfigured_() {
  return !!(
    ZOHO_ENABLED &&
    String(ZOHO_CLIENT_ID || '').trim() &&
    String(ZOHO_CLIENT_SECRET || '').trim() &&
    String(ZOHO_REFRESH_TOKEN || '').trim()
  );
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
  const cached = props.getProperty('lumiLightsZohoLayoutId');
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
      props.setProperty('lumiLightsZohoLayoutId', layouts[i].id);
      return layouts[i].id;
    }
  }
  Logger.log(
    'Zoho layout "' + ZOHO_LAYOUT_NAME + '" not found. Layouts: ' +
    layouts.map(function (layout) { return layout.name; }).join(', ')
  );
  return '';
}

function splitLeadName_(fullName) {
  const name = String(fullName || '').trim() || 'Unknown';
  const space = name.indexOf(' ');
  if (space === -1) {
    return { firstName: '', lastName: name };
  }
  return {
    firstName: name.substring(0, space).trim(),
    lastName: name.substring(space + 1).trim() || name,
  };
}

function buildZohoLeadRecord_(row, fields) {
  const parts = splitLeadName_(fields.name);
  const email = String(fields.email || '').trim();
  const phone = String(fields.phone || '').trim();
  const descriptionParts = ['Imported from Lumi Lights sheet row ' + row];
  if (email) {
    descriptionParts.push('Email provided: ' + email);
  }
  if (phone) {
    descriptionParts.push('Phone provided: ' + phone);
  }
  if (fields.submitted) {
    descriptionParts.push('Submitted: ' + fields.submitted);
  }

  const record = {
    First_Name: parts.firstName,
    Last_Name: parts.lastName,
    Addressss: fields.address || '',
    Offer_page: fields.offer_page || '',
    Sms_consent: fields.sms_consent || '',
    Terms_privacy_consent: fields.tc_consent || '',
    Business_unit: BUSINESS_UNIT,
    Description: descriptionParts.join('\n'),
  };
  if (phone) {
    record.Phone = phone;
  }
  if (email) {
    record.Email = email;
  }
  if (fields.homeowner) {
    record.Homeowner = fields.homeowner;
  }
  if (fields.cares_most_about) {
    record.Cares_most_about = fields.cares_most_about;
  }
  if (fields.budget) {
    record.Budget = fields.budget;
  }
  if (fields.notes) {
    record.Lead_Notes = fields.notes;
  }
  if (fields.other) {
    record.Other = fields.other;
  }
  const layoutId = getZohoLayoutId_();
  if (layoutId) {
    record.Layout = { id: layoutId };
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
    return { skipped: 'set ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, and ZOHO_REFRESH_TOKEN' };
  }
  try {
    var record = buildZohoLeadRecord_(row, fields);
    var result = zohoCreateLeadRequest_(record);
    var parsed = parseZohoCreateSuccess_(result);
    var stripable = {
      Email: true,
      Phone: true,
      Homeowner: true,
      Cares_most_about: true,
      Budget: true,
      Lead_Notes: true,
      Other: true,
    };
    var attempts = 0;
    while (parsed.error && attempts < 3) {
      var apiName = parsed.apiName || zohoCreateErrorApiName_(result);
      if (!apiName || !stripable[apiName] || record[apiName] === undefined) {
        break;
      }
      Logger.log('Zoho rejected ' + apiName + ' — retrying create without it');
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

/** Manual: verify Zoho login and the Lumi Lights layout */
function testZohoConnection() {
  if (!isZohoConfigured_()) {
    throw new Error('Fill ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, and ZOHO_REFRESH_TOKEN first');
  }
  const token = getZohoAccessToken_();
  Logger.log('Access token ok (len=' + token.length + ')');
  const layoutId = getZohoLayoutId_();
  Logger.log('Layout "' + ZOHO_LAYOUT_NAME + '" id=' + (layoutId || '(not found)'));
  if (!layoutId) {
    throw new Error('Zoho layout "' + ZOHO_LAYOUT_NAME + '" was not found');
  }
}
