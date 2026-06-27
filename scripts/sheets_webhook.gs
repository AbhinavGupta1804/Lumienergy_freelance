/**
 * Google Apps Script — push new sheet rows to Lumi FastAPI instantly.
 *
 * Setup (run once after pasting this file):
 *   1. Set WEBHOOK_URL and WEBHOOK_SECRET below
 *   2. Run setupSheetsWebhookTriggers() — authorize when prompted
 *   3. (Optional) Run initializeLastProcessedRow() to skip existing rows
 *   4. Submit a NEW form row or add a row at the bottom of the sheet
 *
 * Row 1 headers must include: First Name, Last Name, Address, Phone
 * Add an Email column when NOTIFICATION_CHANNEL=email on the server.
 *
 * Troubleshooting:
 *   - Run debugWebhookStatus() — shows lastProcessedRow vs sheet lastRow
 *   - Run processNewRows() manually to force-send pending rows
 *   - Re-run setupSheetsWebhookTriggers() if auto-trigger stopped after edits
 *   - Check Apps Script → Executions for errors
 *   - WEBHOOK_URL must match your current ngrok / PUBLIC_BASE_URL
 */

const WEBHOOK_URL = 'https://maya-unanemic-honey.ngrok-free.dev/webhooks/sheets/new-lead';
const WEBHOOK_SECRET = 'lumi-sheets-wh-8f3c2a9e1b7d4f6a0c5e8b2d9f1a4c7e';
const SHEET_NAME = 'Sheet1'; // must match GOOGLE_SHEETS_WORKSHEET_NAME in .env

const COLUMN_HEADERS = {
  first_name: 'First Name',
  last_name: 'Last Name',
  address: 'Address',
  phone_no: 'Phone',
  email: 'Email',
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
  processNewRows_();
}

/** onFormSubmit installable trigger — most reliable for Google Form leads */
function onFormSubmitHandler(e) {
  Logger.log('onFormSubmitHandler fired');
  Utilities.sleep(800);
  if (e && e.range) {
    const row = e.range.getRow();
    Logger.log('Form submitted row ' + row);
    sendRowIfNew_(row);
    return;
  }
  processNewRows_();
}

/** Manual: force-process any rows after lastProcessedRow */
function processNewRows() {
  processNewRows_();
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
  // getRange(row, col, numRows, numColumns) — third arg is height (1 row), not end row
  return sheet.getRange(row, 1, 1, lastCol).getValues()[0];
}

function postLeadWebhook_(row, fields) {
  const payload = {
    row_number: row,
    first_name: fields.first_name,
    last_name: fields.last_name,
    address: fields.address,
    phone_no: fields.phone_no,
    email: fields.email,
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
  const lastProcessed = parseInt(props.getProperty('lastProcessedRow') || '1', 10);
  if (row <= lastProcessed) {
    Logger.log('Row ' + row + ' already processed (lastProcessedRow=' + lastProcessed + ') — skip');
    return;
  }

  const sheet = getLeadSheet_();
  const ctx = getHeaderContext_(sheet);
  const values = readRowValues_(sheet, row, ctx.lastCol);
  const fields = extractLeadFields_(values, ctx.headerIndex);

  if (!fields.first_name && !fields.last_name && !fields.address && !fields.phone_no) {
    Logger.log('Row ' + row + ' is empty — skip');
    return;
  }

  const result = postLeadWebhook_(row, fields);
  if (result.code >= 200 && result.code < 300) {
    props.setProperty('lastProcessedRow', String(row));
    Logger.log('Webhook OK row ' + row + ': ' + result.body);
  } else {
    Logger.log('Webhook FAILED row ' + row + ' HTTP ' + result.code + ': ' + result.body);
    throw new Error('Webhook failed HTTP ' + result.code + ': ' + result.body);
  }
}

function processNewRows_() {
  const props = PropertiesService.getScriptProperties();
  const lastProcessed = parseInt(props.getProperty('lastProcessedRow') || '1', 10);

  const sheet = getLeadSheet_();
  const lastRow = sheet.getLastRow();
  if (lastRow <= 1) {
    Logger.log('No data rows on sheet');
    return;
  }

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

    const result = postLeadWebhook_(row, fields);
    if (result.code >= 200 && result.code < 300) {
      props.setProperty('lastProcessedRow', String(row));
      Logger.log('Webhook OK row ' + row + ': ' + result.body);
    } else {
      Logger.log('Webhook FAILED row ' + row + ' HTTP ' + result.code + ': ' + result.body);
      break;
    }
  }
}
