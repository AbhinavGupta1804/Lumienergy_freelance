/**
 * Lumi Lights sheet → FastAPI.
 *
 * Columns (row 1): Name, Address, Email, Phone, Offer Page, SMS Consent, T&C Consent, Submitted
 *
 * Setup:
 *   1. Extensions → Apps Script → paste this file
 *   2. Run setupLightsWebhookTriggers() and authorize
 *   3. Run initializeLastProcessedRow() once so existing rows are not texted
 */

const WEBHOOK_URL = 'https://arizona-solar-581026638648.us-west4.run.app/webhooks/sheets/lights/new-lead';
const WEBHOOK_SECRET = 'lumi-sheets-wh-8f3c2a9e1b7d4f6a0c5e8b2d9f1a4c7e';
const SHEET_NAME = 'Sheet1';

const COLUMN_HEADERS = {
  name: 'Name',
  address: 'Address',
  email: 'Email',
  phone: 'Phone',
  offer_page: 'Offer Page',
  sms_consent: 'SMS Consent',
  tc_consent: 'T&C Consent',
  submitted: 'Submitted',
};

function initializeLastProcessedRow() {
  const sheet = getLeadSheet_();
  const lastRow = Math.max(sheet.getLastRow(), 1);
  PropertiesService.getScriptProperties().setProperty('lightsLastProcessedRow', String(lastRow));
  Logger.log('lightsLastProcessedRow set to ' + lastRow);
}

function setupLightsWebhookTriggers() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const triggers = ScriptApp.getProjectTriggers();
  for (let i = 0; i < triggers.length; i++) {
    const fn = triggers[i].getHandlerFunction();
    if (fn === 'onLightsSheetChange' || fn === 'onLightsFormSubmit') {
      ScriptApp.deleteTrigger(triggers[i]);
    }
  }
  ScriptApp.newTrigger('onLightsSheetChange').forSpreadsheet(ss).onChange().create();
  ScriptApp.newTrigger('onLightsFormSubmit').forSpreadsheet(ss).onFormSubmit().create();
  Logger.log('Installed Lumi Lights triggers');
}

function onLightsSheetChange() {
  Utilities.sleep(800);
  processNewLightsRows_();
}

function onLightsFormSubmit(e) {
  Utilities.sleep(800);
  if (e && e.range) {
    sendLightsRow_(e.range.getRow());
    return;
  }
  processNewLightsRows_();
}

function processNewLightsRows_() {
  const sheet = getLeadSheet_();
  const props = PropertiesService.getScriptProperties();
  const lastRow = sheet.getLastRow();
  let lastProcessed = Number(props.getProperty('lightsLastProcessedRow') || '1');
  if (lastProcessed < 1) lastProcessed = 1;
  for (let row = lastProcessed + 1; row <= lastRow; row++) {
    sendLightsRow_(row);
  }
}

function sendLightsRow_(row) {
  if (row < 2) return;
  const sheet = getLeadSheet_();
  const props = PropertiesService.getScriptProperties();
  const lastProcessed = Number(props.getProperty('lightsLastProcessedRow') || '1');
  if (row <= lastProcessed) return;

  const lastCol = Math.max(sheet.getLastColumn(), 1);
  const headers = sheet.getRange(1, 1, 1, lastCol).getValues()[0];
  const index = {};
  headers.forEach(function (header, i) {
    index[String(header || '').trim().toLowerCase()] = i;
  });
  const values = sheet.getRange(row, 1, 1, lastCol).getValues()[0];
  function cell(header) {
    const at = index[header.toLowerCase()];
    if (at === undefined) return '';
    const value = values[at];
    if (value instanceof Date) return Utilities.formatDate(value, Session.getScriptTimeZone(), "yyyy-MM-dd'T'HH:mm:ss");
    return value == null ? '' : String(value).trim();
  }

  const name = cell(COLUMN_HEADERS.name);
  const address = cell(COLUMN_HEADERS.address);
  const phone = cell(COLUMN_HEADERS.phone);
  if (!name && !address && !phone) {
    Logger.log('Row ' + row + ' is empty — skip');
    return;
  }

  const payload = {
    row_number: row,
    name: name,
    address: address,
    email: cell(COLUMN_HEADERS.email),
    phone: phone,
    offer_page: cell(COLUMN_HEADERS.offer_page),
    sms_consent: cell(COLUMN_HEADERS.sms_consent),
    tc_consent: cell(COLUMN_HEADERS.tc_consent),
    submitted: cell(COLUMN_HEADERS.submitted),
  };
  const resp = UrlFetchApp.fetch(WEBHOOK_URL, {
    method: 'post',
    contentType: 'application/json',
    headers: { 'X-Sheets-Webhook-Secret': WEBHOOK_SECRET },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true,
  });
  Logger.log('Lights row ' + row + ' HTTP ' + resp.getResponseCode() + ' ' + resp.getContentText());
  if (resp.getResponseCode() >= 200 && resp.getResponseCode() < 300) {
    props.setProperty('lightsLastProcessedRow', String(row));
  }
}

function getLeadSheet_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(SHEET_NAME) || ss.getSheets()[0];
  if (!sheet) throw new Error('No sheet found');
  return sheet;
}
