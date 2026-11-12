-- OpenAI lighting preview saved next to the Street View photo.
ALTER TABLE processed_leads
  ADD COLUMN IF NOT EXISTS streetview_render_path TEXT,
  ADD COLUMN IF NOT EXISTS streetview_render_fetched_at TIMESTAMPTZ;
