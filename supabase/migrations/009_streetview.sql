-- Cached Google Street View photo for a lead's home.
ALTER TABLE processed_leads
  ADD COLUMN IF NOT EXISTS streetview_storage_path TEXT,
  ADD COLUMN IF NOT EXISTS streetview_fetched_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS streetview_render_path TEXT,
  ADD COLUMN IF NOT EXISTS streetview_render_fetched_at TIMESTAMPTZ;
