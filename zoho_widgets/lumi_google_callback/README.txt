Lumi Energy — Google Callback Widget (Zoho CRM)

What it does
  Opens from a Lead detail custom button, loads the Lead, and calls the
  REST API custom function create_google_callback to create a FREE
  (non-blocking) Google Calendar event in America/Phoenix.

Zip layout (required by ZET / Zoho internal hosting)
  plugin-manifest.json
  app/widget.html
  app/img/logo.png

Upload in Zoho CRM
  1. Setup → Developer Hub → Widgets → Create New Widget
  2. Hosting: Zoho
  3. Upload this zip
  4. Index URL (critical):  /app/widget.html
     (leading slash required — wrong path = "Page not found")
  5. Save

Attach to a Lead button
  Setup → Customization → Modules and Fields → Leads → Links & Buttons
  → Create New Button → View page / Detail
  → Action: Invoke a Widget → select "Schedule Follow Up"

Prerequisites
  - Custom function API name: create_google_callback
  - Function must accept arguments: lead_id, lead_name, phone, date,
    time, duration_minutes, notes
  - Google Calendar connection configured in Zoho
