/**
 * POST /api/upload
 * multipart/form-data fields:
 *   file  — the bill (image or PDF, max 20 MB)
 *   token — the upload token from the SMS link query string
 *
 * Workflow:
 *   1. Validate token (same checks as validate-token endpoint)
 *   2. Stream file to Supabase Storage bucket "bill_upload"
 *   3. Insert metadata row into bill_uploads table
 *   4. Mark upload_token_used = true on processed_leads
 *   5. Return { ok: true }
 */

const { createClient } = require('@supabase/supabase-js');
const Busboy = require('busboy');
const { Readable } = require('stream');
const path = require('path');
const { randomUUID } = require('crypto');

const supabase = createClient(
  process.env.SUPABASE_URL,
  process.env.SUPABASE_SERVICE_ROLE_KEY,
);

const BUCKET = 'bill_upload';
const MAX_SIZE_BYTES = 20 * 1024 * 1024; // 20 MB
const TOKEN_EXPIRY_DAYS = 7;

async function parseForm(req) {
  // Bun local dev server passes a pre-parsed FormData object.
  if (req._formData) {
    const formData = req._formData;
    const token = formData.get('token');
    const file = formData.get('file');
    if (!file || typeof file === 'string') {
      const err = new Error('No file received');
      err.code = 'NO_FILE';
      throw err;
    }
    if (file.size > MAX_SIZE_BYTES) {
      const err = new Error('File too large');
      err.code = 1009;
      throw err;
    }
    const buffer = Buffer.from(await file.arrayBuffer());
    return {
      fields: { token },
      files: {
        file: {
          _buffer: buffer,
          originalFilename: file.name,
          mimetype: file.type || 'application/octet-stream',
          size: file.size,
        },
      },
    };
  }

  // Vercel / Node — buffer body then parse with busboy (formidable breaks on Vercel).
  const contentType = req.headers['content-type'] || '';
  if (!contentType.includes('multipart/form-data')) {
    const err = new Error('Expected multipart form data');
    err.code = 'NO_FILE';
    throw err;
  }

  let body;
  if (Buffer.isBuffer(req.body)) {
    body = req.body;
  } else if (typeof req.body === 'string') {
    body = Buffer.from(req.body, 'binary');
  } else {
    const chunks = [];
    for await (const chunk of req) {
      chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
    }
    body = Buffer.concat(chunks);
  }

  if (!body.length) {
    const err = new Error('No file received');
    err.code = 'NO_FILE';
    throw err;
  }

  return new Promise((resolve, reject) => {
    const fields = {};
    const files = {};
    const pending = [];

    const busboy = Busboy({
      headers: req.headers,
      limits: { fileSize: MAX_SIZE_BYTES },
    });

    busboy.on('field', (name, value) => {
      fields[name] = value;
    });

    busboy.on('file', (name, stream, info) => {
      const chunks = [];
      pending.push(
        new Promise((res, rej) => {
          stream.on('data', (chunk) => chunks.push(chunk));
          stream.on('limit', () => {
            const err = new Error('File too large');
            err.code = 1009;
            rej(err);
          });
          stream.on('close', () => {
            const buffer = Buffer.concat(chunks);
            files[name] = {
              _buffer: buffer,
              originalFilename: info.filename,
              mimetype: info.mimeType || 'application/octet-stream',
              size: buffer.length,
            };
            res();
          });
          stream.on('error', rej);
        }),
      );
    });

    busboy.on('error', reject);
    busboy.on('close', async () => {
      try {
        await Promise.all(pending);
        resolve({ fields, files });
      } catch (err) {
        reject(err);
      }
    });

    Readable.from(body).pipe(busboy);
  });
}

module.exports = async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', process.env.ALLOWED_ORIGIN || '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');

  if (req.method === 'OPTIONS') return res.status(204).end();
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

  // ── 1. Parse multipart form ──────────────────────────────────
  let fields, files;
  try {
    ({ fields, files } = await parseForm(req));
  } catch (err) {
    console.error('upload: parse error:', err);
    const msg = err.code === 1009
      ? 'File is too large. Maximum allowed size is 20 MB.'
      : 'Could not read the uploaded file.';
    return res.status(400).json({ error: msg });
  }

  const token = Array.isArray(fields.token) ? fields.token[0] : fields.token;
  const file  = Array.isArray(files.file)   ? files.file[0]   : files.file;

  if (!token) return res.status(400).json({ error: 'Missing upload token.' });
  if (!file)  return res.status(400).json({ error: 'No file received.' });

  // ── 2. Validate token ────────────────────────────────────────
  const { data: lead, error: dbErr } = await supabase
    .from('processed_leads')
    .select('row_key, name, phone_no, upload_token_used, processed_at')
    .eq('upload_token', token)
    .maybeSingle();

  if (dbErr) {
    console.error('upload: db lookup error:', dbErr.message);
    return res.status(500).json({ error: 'Database error. Please try again.' });
  }

  if (!lead)                  return res.status(400).json({ error: 'This link is not valid.' });
  if (lead.upload_token_used) return res.status(400).json({ error: 'This link has already been used.' });

  const createdAt = new Date(lead.processed_at);
  const expiresAt = new Date(createdAt.getTime() + TOKEN_EXPIRY_DAYS * 24 * 60 * 60 * 1000);
  if (new Date() > expiresAt) return res.status(400).json({ error: 'This link has expired.' });

  // ── 3. Upload to Supabase Storage ────────────────────────────
  const ext          = path.extname(file.originalFilename || file.newFilename || '').toLowerCase() || '';
  const safeName     = `${lead.row_key}/${randomUUID()}${ext}`;
  const fileBuffer  = file._buffer;
  const contentType = file.mimetype || 'application/octet-stream';

  const { error: storageErr } = await supabase.storage
    .from(BUCKET)
    .upload(safeName, fileBuffer, {
      contentType,
      upsert: false,
    });

  if (storageErr) {
    console.error('upload: storage error:', storageErr.message);
    return res.status(500).json({ error: 'Could not save your file. Please try again.' });
  }

  // ── 4. Insert metadata row ───────────────────────────────────
  const { error: insertErr } = await supabase
    .from('bill_uploads')
    .insert({
      lead_row_key:   lead.row_key,
      upload_token:   token,
      storage_path:   safeName,
      original_name:  file.originalFilename || null,
      content_type:   contentType,
      size_bytes:     file.size,
      status:         'received',
    });

  if (insertErr) {
    // Non-fatal — file is already stored; just log and continue.
    console.error('upload: insert metadata error:', insertErr.message);
  }

  // ── 5. Mark token as used ────────────────────────────────────
  const { error: updateErr } = await supabase
    .from('processed_leads')
    .update({ upload_token_used: true })
    .eq('upload_token', token);

  if (updateErr) {
    console.error('upload: mark used error:', updateErr.message);
  }

  // ── 6. Notify Lumi API → send consultation confirmation SMS ──
  await notifyBillUploadComplete(token);

  return res.status(200).json({ ok: true });
};

async function notifyBillUploadComplete(uploadToken) {
  const url = process.env.LUMI_API_BILL_UPLOAD_WEBHOOK_URL;
  const secret = process.env.BILL_UPLOAD_WEBHOOK_SECRET;
  if (!url || !secret) {
    console.warn('upload: confirmation webhook not configured (skip SMS)');
    return;
  }
  try {
    const resp = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Bill-Upload-Webhook-Secret': secret,
      },
      body: JSON.stringify({ upload_token: uploadToken }),
    });
    if (!resp.ok) {
      const text = await resp.text();
      console.error('upload: confirmation webhook HTTP', resp.status, text);
    }
  } catch (err) {
    console.error('upload: confirmation webhook error:', err.message);
  }
}
