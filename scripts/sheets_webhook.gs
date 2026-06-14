/**
 * Google Apps Script — push new sheet rows to Lumi FastAPI instantly.
 *
 * Setup:
 * 1. Open your Google Sheet → Extensions → Apps Script
 * 2. Paste this file (replace WEBHOOK_URL and WEBHOOK_SECRET)
 * 3. Run setupSheetsWebhookTrigger() once (authorize when prompted)
 * 4. Add a test row — your server should receive POST /webhooks/sheets/new-lead
 *
 * Row 1 headers must include: First Name, Last Name, Street Address, Phone
 * (other columns like Timestamp, Email, Zip are ignored)
 */

const WEBHOOK_URL = 'https://maya-unanemic-honey.ngrok-free.dev/webhooks/sheets/new-lead';
const WEBHOOK_SECRET = 'lumi-sheets-wh-8f3c2a9e1b7d4f6a0c5e8b2d9f1a4c7e';
const SHEET_NAME = 'Sheet1'; // must match GOOGLE_SHEETS_WORKSHEET_NAME

const COLUMN_HEADERS = {
  first_name: 'First Name',
  last_name: 'Last Name',
  address: 'Street Address',
  phone_no: 'Phone',
};

/**
 * Run once BEFORE going live if the sheet already has data rows.
 * Skips all existing rows — only rows added AFTER this run will trigger calls.
 */
function initializeLastProcessedRow() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(SHEET_NAME) || ss.getActiveSheet();
  const lastRow = Math.max(sheet.getLastRow(), 1);
  PropertiesService.getScriptProperties().setProperty('lastProcessedRow', String(lastRow));
  Logger.log('lastProcessedRow set to ' + lastRow + ' — existing rows will not be called');
}

/**
 * Run once from the Apps Script editor to install the onChange trigger.
 */
function setupSheetsWebhookTrigger() {
  const triggers = ScriptApp.getProjectTriggers();
  for (const t of triggers) {
    if (t.getHandlerFunction() === 'onSheetChange') {
      ScriptApp.deleteTrigger(t);
    }
  }
  ScriptApp.newTrigger('onSheetChange')
    .forSpreadsheet(SpreadsheetApp.getActive())
    .onChange()
    .create();
  Logger.log('Installed onChange trigger for onSheetChange');
}

/**
 * Installable trigger — fires when rows are added, edited, or pasted.
 */
function onSheetChange(e) {
  processNewRows_();
}

/**
 * Manual test from Apps Script editor: Run → processNewRows
 */
function processNewRows() {
  processNewRows_();
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
  };
}

function processNewRows_() {
  const props = PropertiesService.getScriptProperties();
  const lastProcessed = parseInt(props.getProperty('lastProcessedRow') || '1', 10);

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(SHEET_NAME) || ss.getActiveSheet();
  const lastRow = sheet.getLastRow();
  const lastCol = Math.max(sheet.getLastColumn(), 1);

  if (lastRow <= 1) {
    return;
  }

  const headers = sheet.getRange(1, 1, 1, lastCol).getValues()[0];
  const headerIndex = buildHeaderIndex_(headers);

  const required = Object.values(COLUMN_HEADERS);
  for (let i = 0; i < required.length; i++) {
    if (headerIndex[normalizeHeader_(required[i])] === undefined) {
      Logger.log('Missing required header: ' + required[i]);
      return;
    }
  }

  const startRow = Math.max(lastProcessed + 1, 2);

  for (let row = startRow; row <= lastRow; row++) {
    const values = sheet.getRange(row, 1, 1, lastCol).getValues()[0];
    const fields = extractLeadFields_(values, headerIndex);

    if (!fields.first_name && !fields.last_name && !fields.address && !fields.phone_no) {
      continue;
    }

    const payload = {
      row_number: row,
      first_name: fields.first_name,
      last_name: fields.last_name,
      address: fields.address,
      phone_no: fields.phone_no,
    };

    const options = {
      method: 'post',
      contentType: 'application/json',
      headers: { 'X-Sheets-Webhook-Secret': WEBHOOK_SECRET },
      payload: JSON.stringify(payload),
      muteHttpExceptions: true,
    };

    const resp = UrlFetchApp.fetch(WEBHOOK_URL, options);
    const code = resp.getResponseCode();
    const body = resp.getContentText();

    if (code >= 200 && code < 300) {
      props.setProperty('lastProcessedRow', String(row));
      Logger.log('Webhook OK row ' + row + ': ' + body);
    } else {
      Logger.log('Webhook FAILED row ' + row + ' HTTP ' + code + ': ' + body);
      break;
    }
  }
}
