AUTOMATED VOICE-AGENT LEAD QUALIFICATION AND APPOINTMENT SYSTEM FOR RESIDENTIAL SOLAR

Name of the Student: [Full name]
Email and mobile: [Email] / [Mobile number]

Name of the 2nd Student: [Full name, or write “Not applicable”]
Email and mobile: [Email] / [Mobile number]

Name of the 3rd Student: [Full name, or write “Not applicable”]
Email and mobile: [Email] / [Mobile number]

Name of the Supervisor: [Guide name]
Email and mobile: [Email] / [Mobile number]

Name of the Department at IET: [Department name]

Keywords: conversational voice agent, outbound qualification, appointment scheduling, solar CRM automation, tool-using dialogue

1. INTRODUCTION

A residential solar company does not usually lose the sale on the roof. It loses the sale in the hour after a homeowner fills in a form and nobody calls back with a clear next step. The form already holds a name, a phone number, an address, and a rough electric bill. What is missing is a consistent first conversation: confirm the person, ask whether the summer bill is high enough for the program to help, and put a technician on the calendar for a visit to the house. Doing that by hand means a setter watches a spreadsheet and dials until the list is stale.

This project builds that first conversation as a voice agent and wires it into the rest of the Lumi Energy pipeline. The public website at lumienergy.us collects the enquiry. The site stores the lead, alerts the team on Discord, and appends a Google Sheet. An Apps Script creates a Zoho CRM lead on the Lumi Solar layout and notifies a Python service on Google Cloud Run. That service sends a welcome SMS when the form recorded consent, then places an outbound call. The caller is Emma, a conversational agent on ElevenLabs, with Twilio carrying the telephone leg. Emma does not browse the calendar herself and does not guess a time. She calls tools on the same service: one tool returns two real appointment slots, a second tool books the chosen slot, and a third tool texts a private link so the homeowner can upload a power bill before the visit.

The work sits in the area of task-oriented spoken dialogue. A survey of chatbots argues that an agent is useful when it can complete a back-end action, not when it only talks [1]. Spoken-dialogue design makes the same demand in stronger form: the system should not tell the user a transaction succeeded until the back end has confirmed it [2]. Emma is built to that rule. She may offer only times that the slot tool returned, and she may say “you’re booked” only after the booking tool returns success. Zoho remains the record the closer reads. The voice agent is the worker that qualifies the lead and fills the appointment.

2. LITERATURE SURVEY

HubSpot and similar CRMs store a contact and can start an email sequence from a form. Their advantage is one screen for the sales team. Their drawback here is the live phone call. A sequence cannot ask a follow-up question about last summer’s bill, refuse a home whose bill is under the program threshold, and then book a physical visit from live calendar inventory. The CRM remains necessary. It is not sufficient for the first conversation.

GoHighLevel and other home-service platforms combine funnels, SMS, and calendars. They are fast to configure. The limitation appears when the phone call has to follow a strict policy: exactly two offered times, Arizona clock, no Sundays, no invented slots, and a bill-upload text that fires only after a successful booking. Those rules are easier to test as code behind the agent than as a chain of generic workflow blocks.

Calendly and Cal.com solve scheduling only. Cal.com is the calendar used in this project because it exposes slots and bookings over an API and sends webhooks when a booking is created, moved, or cancelled [3]. On its own it does not know the summer-bill rule and it does not speak to the homeowner. The voice agent is the layer that turns a free slot into a sentence the customer can accept or reject.

EnergySage and similar solar marketplaces collect an address and a bill range, then share the lead with several installers. That creates demand. It does not give one company a private qualifying call, a consent record, and a visit on its own technician’s calendar. Lumi Energy’s site keeps the enquiry, and Emma continues it.

Hosted voice agents, including ElevenLabs Conversational AI, can place an outbound call and follow a prompt while invoking HTTP tools [4]. Used alone, the agent has no lead row, no consent flag, and no right to write Zoho. Twilio supplies the telephone network and the SMS path [5]. Zoho CRM is the system of record for the closer [6]. None of these products, used alone, both speaks the qualification script and refuses to confirm a visit that the calendar did not accept. That gap is why the tools live on the project’s own API rather than inside the prompt.

3. PROBLEM DOMAIN

The problem is the missing, unreliable first call. A new solar lead should be phoned while the enquiry is fresh. The caller should use the name and address already on the form, should ask for the highest summer bill, should end politely when the bill is under about $120, and should book an in-person visit only on a real open slot. The caller must not invent a time, must not describe the appointment as a video meeting, and must not say the visit is booked before the calendar has accepted it. If nobody answers, the system should retry. If the person books, follow-up nudges should stop and a bill-upload link should go out by text when consent allows. The closer, opening Zoho the next morning, should see the appointment rather than a bare form submission.

The objectives are:

1. Capture a Lumi Energy website lead into Google Sheets, Discord, Supabase, and a Zoho lead on the Lumi Solar layout.
2. Place an outbound voice-agent call automatically once that lead is stored.
3. Give the agent tools for slot lookup, booking, voicemail detection, and the bill-upload text, and forbid confirmation that those tools did not return.
4. Pass the form’s first name, address, and phone into the call as dynamic variables, plus the three bookable weekdays.
5. Persist the transcript outcome, schedule a callback when the call is not answered, and email a preliminary solar note that includes a calendar link only if the visit was not already booked.
6. Keep SMS consent and STOP in force for every text the agent or the nurture sequence sends.

4. SOLUTION DOMAIN

The pipeline has four stages. The voice agent is the stage that does the qualification.

Capture. The Next.js site inserts a row in processed_leads, creates a one-time bill-upload token, posts a Discord embed, and appends the sheet. Apps Script creates the Zoho lead and calls the Cloud Run webhook with the new Zoho id. The API stores the lead and sends the welcome SMS when transactional consent is yes.

Dial. With the voice agent enabled, the orchestration service then starts an outbound call through ElevenLabs and Twilio. The payload carries dynamic variables the prompt can read: first_name, last_name, full_name, address, phone_no, and the three scheduling days. The first day is spoken as “tomorrow” when tomorrow is bookable, and as the weekday name when tomorrow is Sunday, because Sunday visits are not offered. Call recording is left off.

The conversation, agent name Emma. She asks whether she has reached the first name on the lead. She says she is calling from Lumi Energy about lowering the electric bill and asks for a minute. She asks for the highest summer bill. Under $120, she thanks the person and ends. Otherwise she asks whether they have already looked for a solution, explains that a technician visit is personalised and carries no obligation, and asks who else should be present for the decision. She then schedules.

Scheduling policy and tools. Emma never computes a clock time. For one day and one part of the day she calls get_available_slots. That tool is GET /scheduling/slots on the project API. It resolves phrases such as “tomorrow” in America/Phoenix, skips Sunday, reads Cal.com, and returns at most two slots plus a spoken_offer string she is supposed to read aloud, for example “Monday, June 15 — 8 AM or 10 AM”. If that part of the day is empty but the day has other openings, she tries another part of the day. If the day is empty, the tool returns next_day_ask and she moves to the second, then the third, bookable day. If all three days fail, she does not invent a fourth day. She says someone from the team will call within an hour or two. When the customer picks one of the two offered times, she calls book_slot with that slot’s exact start value and the phone number from the prompt variable. The booking handler loads the real name and address from the database, creates the Cal.com booking, and returns success only after Cal.com accepts it. Only then may she say the visit is booked. She confirms the address, warns that the consultant is holding the time, and calls mark_bill_sms_ready. That tool texts the upload link immediately, and only if the sheet recorded SMS consent and the booking step was reached. She closes by saying Ivan will see them at the house.

A fourth tool, voicemail detection, is the platform’s system tool. The post-call handler treats that outcome as an unanswered call rather than as a completed qualification, so a callback can be scheduled.

After the call. ElevenLabs posts a signed webhook. The API stores duration, summary, and how the call ended. An answered booking suppresses the self-serve calendar link on the follow-up email. A no-answer, a failed dial, or a call that did not book can still email the preliminary solar PDF with a link to book. Unanswered calls enter a callback schedule. Inbound STOP opts the phone out. Stage-two SMS, ten touches over about three weeks, runs only while the lead has not booked and has not replied.

Staff still use Zoho and a dashboard for the thread and for sale figures. The voice agent does not replace that screen. It fills the appointment the closer will walk into.

5. SYSTEM DOMAIN

The solar site and the staff dashboard are Next.js applications. The orchestration service is Python with FastAPI, deployed on Cloud Run. Lead state is PostgreSQL through Supabase, with the same store available on SQLite for local development. Timed callbacks, nurture texts, and follow-up email use Google Cloud Tasks. The voice agent is ElevenLabs Conversational AI, bridged to a Twilio number that is already attached to the agent. Tools are ordinary HTTPS endpoints on the project API, gated by a shared tool key that is also configured on the agent. The calendar is Cal.com’s API. The CRM is Zoho, reached with an OAuth refresh token. Email uses Resend. The solar PDF can include a roof image from the Google Maps Static API.

These choices keep each vendor on the job it already does. ElevenLabs holds the speech model and the turn-taking. The project holds the business rules, because a prompt alone cannot be trusted to invent neither a slot nor a booking. Cal.com holds the technician’s calendar. Zoho holds the lead the closer opens. Cloud Tasks holds the alarm for a retry, so the API does not have to stay awake until the next attempt.

A developer laptop can run the API and play a test call against a consented number. Production needs Cloud Run, Supabase, Zoho, Twilio, ElevenLabs, and Cal.com. No special appliance is required.

6. APPLICATION DOMAIN

The system applies to Lumi Energy’s residential solar intake in Arizona. A homeowner who submits a form is texted, then called by Emma, and either booked for an in-home consultation or released with a reason: bill too low, not interested, no answer, or no slot inside three bookable days. The same pattern fits other appointment businesses that already own a CRM and a calendar and need the first call to obey a written script. The visit in this project is physical. The agent is instructed never to offer Google Meet, Zoom, or a virtual meeting.

7. EXPECTED OUTCOME

- A Lumi Energy website lead stored in the database, on the sheet, in Discord, and on the Lumi Solar layout in Zoho.
- An automatic outbound call by Emma, using the lead’s name, address, and phone.
- Qualification on the summer bill, with a polite end under about $120.
- A home visit booked only through get_available_slots and book_slot, never from a time the model invented.
- A consent-checked bill-upload SMS from mark_bill_sms_ready after a successful booking, and voicemail treated as a missed call.
- A post-call record, a callback when the call is not answered, and a solar email whose calendar link depends on whether the visit was already booked.
- Consent and STOP enforced on every automated text.
- This synopsis, the software requirements specification, and the project report.

References

[1] E. Adamopoulou and L. Moussiades, “Chatbots: History, technology, and applications,” Machine Learning with Applications, vol. 2, Dec. 2020, Art. 100006.

[2] D. Jurafsky and J. H. Martin, “Dialogue Systems and Chatbots,” in Speech and Language Processing, 3rd ed. draft, ch. 15, 2024. [Online]. Available: https://web.stanford.edu/~jurafsky/slp3/

[3] Cal.com, “API reference v2,” 2024. [Online]. Available: https://cal.com/docs/api-reference/v2

[4] ElevenLabs, “Conversational AI documentation.” [Online]. Available: https://elevenlabs.io/docs

[5] Twilio, “Programmable Messaging and Programmable Voice.” [Online]. Available: https://www.twilio.com/docs

[6] Zoho Corporation, “Zoho CRM API v8.” [Online]. Available: https://www.zoho.com/crm/developer/docs/api/v8/

[7] Google Cloud, “Cloud Tasks documentation.” [Online]. Available: https://cloud.google.com/tasks/docs

[8] K. E. Wiegers and J. Beatty, Software Requirements, 3rd ed. Redmond, WA, USA: Microsoft Press, 2013.

[9] Federal Communications Commission, Telephone Consumer Protection Act, 47 U.S.C. § 227.

[10] S. Ramírez, FastAPI documentation, 2024. [Online]. Available: https://fastapi.tiangolo.com

[11] Supabase, “Database and Storage documentation.” [Online]. Available: https://supabase.com/docs

[12] Vercel, “Next.js App Router documentation.” [Online]. Available: https://nextjs.org/docs/app

Appendix A

The work was carried out on the live Lumi Energy stack: the Next.js solar site, the FastAPI service and the ElevenLabs agent prompt in this repository, the Google Sheet script, and the Zoho CRM Lumi Solar lead layout. Leads used during development were ordinary form submissions in processed_leads. No separate public dataset was required.

Notes for submission

Set the body to Times New Roman, 12 point, single column, with about one inch of margin on each side before printing. Every group member signs the synopsis, and the supervisor endorses it. The external supervisor must hold at least an M.E. or M.Tech. Keep a weekly diary of meetings with the guide, signed by the guide, and bring it to the external viva. Do not send the work to a conference or a journal without the permission of the Head of Department.
