/**
 * GET /api/validate-token?token=<uuid>
 *
 * Returns { valid: true } if the token exists in processed_leads,
 * has not been used yet, and is not expired (tokens expire after 7 days).
 */

const { createClient } = require('@supabase/supabase-js');

const supabase = createClient(
  process.env.SUPABASE_URL,
  process.env.SUPABASE_SERVICE_ROLE_KEY,
);

const TOKEN_EXPIRY_DAYS = 7;

module.exports = async function handler(req, res) {
  // CORS — allow requests from the same Vercel deployment only in production.
  res.setHeader('Access-Control-Allow-Origin', process.env.ALLOWED_ORIGIN || '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');

  if (req.method === 'OPTIONS') return res.status(204).end();
  if (req.method !== 'GET') return res.status(405).json({ error: 'Method not allowed' });

  const { token } = req.query;

  if (!token || token.length < 10) {
    return res.status(400).json({ valid: false, reason: 'missing_token' });
  }

  const { data, error } = await supabase
    .from('processed_leads')
    .select('upload_token, upload_token_used, processed_at')
    .eq('upload_token', token)
    .maybeSingle();

  if (error) {
    console.error('validate-token db error:', error.message);
    return res.status(500).json({ valid: false, reason: 'db_error' });
  }

  if (!data) {
    return res.status(200).json({ valid: false, reason: 'not_found' });
  }

  if (data.upload_token_used) {
    return res.status(200).json({ valid: false, reason: 'already_used' });
  }

  // Check expiry
  const createdAt = new Date(data.processed_at);
  const expiresAt = new Date(createdAt.getTime() + TOKEN_EXPIRY_DAYS * 24 * 60 * 60 * 1000);
  if (new Date() > expiresAt) {
    return res.status(200).json({ valid: false, reason: 'expired' });
  }

  return res.status(200).json({ valid: true });
};
