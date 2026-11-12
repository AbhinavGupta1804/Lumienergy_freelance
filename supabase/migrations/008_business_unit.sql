-- Brand/company for nurture SMS (Lumi Energy vs Lumi Lights).
ALTER TABLE processed_leads
  ADD COLUMN IF NOT EXISTS business_unit TEXT;
