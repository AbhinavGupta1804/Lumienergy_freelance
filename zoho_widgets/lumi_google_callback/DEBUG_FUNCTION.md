# Debug: empty function logs + "Could not schedule callback"

## What empty logs mean

The Deluge function **never ran**. Zoho only writes Function logs when
the function body actually starts. Empty logs = the widget's
`ZOHO.CRM.FUNCTIONS.execute("create_google_callback", …)` failed
*before* Deluge (wrong API name, wrong function type, or no permission).

## 1) See the real error (30 seconds)

1. Open a Lead → click the Schedule button (widget open)
2. Press **F12** → **Console** tab
3. Click **Schedule Callback** again
4. Look for:
   - `Calling Zoho function: create_google_callback …`
   - `FUNCTIONS.execute threw: …`
   - `Google callback function response: …`

That response/object is the truth. Common cases:

| Console / response | Meaning |
|---|---|
| Function does not exist / INVALID_DATA | API name wrong or function not saved |
| permission / AUTHORIZATION_FAILED | Profile can't run functions from widgets |
| NO_PERMISSION | Missing `ZohoCRM.functions.execute` style scope |
| `{ code: … }` with no `details.output` | Function never invoked |
| `details.output` starts with `ERROR:` | Function ran — check Connection / Calendar |

## 2) Confirm the function exists with the EXACT API name

Setup → Developer Space → **Functions**

- Must exist with **API Name** = `create_google_callback`
  (not display name alone — open the function and check API Name)
- Must be callable from CRM (Automation / Standalone that widgets can execute)
- **REST API** functions that take `Map crmAPIRequest` are for webhooks —
  those do **not** show up in logs when the widget calls `FUNCTIONS.execute`

If the function is missing, create it from:
`zoho functions/create_google_callback.dg`

## 3) Confirm argument names match

Widget sends:

```json
{
  "lead_id": "...",
  "lead_name": "...",
  "phone": "...",
  "date": "YYYY-MM-DD",
  "time": "HH:mm",
  "duration_minutes": "5",
  "notes": "..."
}
```

Function parameters must use these **exact** names.

## 4) After fixing — prove the path

Use the temp version in `create_google_callback.dg` (returns success JSON
and `info` log). Click Schedule again:

- Widget should say success
- Function logs should show one entry

Then uncomment the Google Calendar `invokeurl` and set your Connection link name.

## 5) Re-upload widget (shows real errors in the UI)

Updated `app/widget.html` now prints the real failure message instead of
only “Check the function execution log.”

Rebuild zip:

```bash
cd zoho_widgets/lumi_google_callback
../node_modules/.bin/zet pack
# upload dist/lumi_google_callback.zip
# Index Page: /app/widget.html
```

Remember: delete + recreate widget if Zoho keeps the old hosted files.
