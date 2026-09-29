-- Store Zoho CRM Lead ID for stable nurture matching
ALTER TABLE processed_leads
  ADD COLUMN IF NOT EXISTS zoho_lead_id TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_processed_leads_zoho_lead_id
  ON processed_leads (zoho_lead_id)
  WHERE zoho_lead_id IS NOT NULL AND zoho_lead_id <> '';
