# Zoho CRM — Schedule Callback Widget

## Why internal hosting failed

Zoho’s hosted zip at `zappsusercontent.com` never updated after re-upload
(old broken SDK + old manifest still live). That causes **Page Not Found**.

## Recommended: External hosting (works reliably)

### 1. Deploy the HTML (already in repo)

File:
`admin_dashboard/public/zoho-widgets/schedule-callback.html`

After deploying the admin dashboard (Vercel), open:

`https://lumienergy-freelance.vercel.app/zoho-widgets/schedule-callback.html`

(Confirm that URL loads in a browser first.)

### 2. Create a NEW widget in Zoho CRM

1. Setup → Developer Hub → Widgets  
2. **Delete** the old “Schedule follow up” widget (or leave it unused)  
3. Create New Widget:
   - Name: `Schedule follow up`
   - Type: **Button**
   - Hosting: **External**
   - URL: `https://lumienergy-freelance.vercel.app/zoho-widgets/schedule-callback.html`
4. Save

### 3. Point the button at the new widget

Leads → Links & Buttons → “Schedule Follow up on calendar”  
→ Open a Widget → select the new widget → Save

### 4. Test

Open a Lead → click the button. You should see the Schedule Callback form.

---

## Optional: Internal hosting (if you insist)

1. Delete the old widget completely  
2. Create New (do not only “Change” zip on the old one — Zoho often keeps the old hash)  
3. Upload `lumi_google_callback_widget_zet_upload.zip`  
4. Index Page: `/app/widget.html`  
5. Save, then re-link the button  

Verify after upload by opening BaseURL + `/widget.html` in a browser;
if you still see the old `js.zohostatic.com/crm/v8/...` SDK, the zip did not deploy.
