Software Requirements Specification
for
Automated Voice-Agent Lead Qualification and Appointment System for Residential Solar
Version 1.0 approved
Prepared by [Student name]
Institute of Engineering & Technology, Devi Ahilya Vishwavidyalaya, Indore
[Date]

Document status: describes the Lumi Energy solar system as operated with the voice agent switched on. Lighting products are outside this specification.

Revision History

| Name | Date | Reason for changes | Version |
| --- | --- | --- | --- |
| [Student name] | [Date] | Initial SRS. Scope limited to Lumi Solar. Voice agent treated as enabled. | 1.0 |

Table of Contents

1. Introduction
2. Overall Description
3. External Interface Requirements
4. System Features
5. Other Nonfunctional Requirements
6. Other Requirements
Appendix A: Glossary
Appendix B: Analysis Models
Appendix C: To Be Determined List

1. Introduction

1.1 Purpose

This specification describes version 1.0 of the Lumi Energy intake system. The product covered here is the path from the solar website to a Zoho lead and an in-person consultation, with the outbound voice agent Emma as the component that qualifies the homeowner and books the visit. It includes the website, the sheet script, the orchestration API, the agent prompt and tools, the post-call handler, and the staff dashboard used for solar leads. It does not specify the internals of ElevenLabs, Twilio, Cal.com, or Zoho.

1.2 Document Conventions

Requirements use the identifiers REQ-xx and are individually prioritised. “Shall” means required. Field names in backticks are Zoho API names or database columns. Phoenix time means America/Phoenix. The appointment in this specification is a physical visit to the home. The agent shall not describe it as a video call.

No credential, tool key, or customer record appears in this document.

1.3 Intended Audience and Reading Suggestions

Examiners and the project guide should read Sections 1, 2, and 4.4 through 4.6 first. Those sections are the voice agent. Developers maintaining tools should read Section 3.3 and features 4.5 and 4.6. Staff who use Zoho and the dashboard should read Sections 2.3 and 4.9.

1.4 Product Scope

The business goal is a booked technician visit with a homeowner whose summer bill is high enough for the program, without a person retyping the form or inventing a calendar time.

In scope:

- Solar lead capture, Discord alert, sheet row, and a Zoho lead on the Lumi Solar layout.
- Welcome SMS when consent was given, then an automatic outbound call.
- Emma’s qualification script, scheduling policy, and four tools.
- Post-call storage, callbacks, the solar email, and the bill-upload page.
- Staff inbox and sale write-back for solar leads.

Out of scope:

- Any second brand, lighting website, or Google Meet reminder.
- Taking payment or scheduling the installation crew.
- A native mobile application.

1.5 References

[1] K. E. Wiegers and J. Beatty, Software Requirements, 3rd ed. Microsoft Press, 2013.

[2] Federal Communications Commission, Telephone Consumer Protection Act, 47 U.S.C. § 227.

[3] ElevenLabs, “Conversational AI documentation.” [Online]. Available: https://elevenlabs.io/docs

[4] Cal.com, “API reference v2.” [Online]. Available: https://cal.com/docs/api-reference/v2

[5] The project synopsis in docs/academic/SYNOPSIS.md.

2. Overall Description

2.1 Product Perspective

The product is the integration around tools Lumi Energy already uses, plus a voice agent that is allowed to act only through the project API. Zoho holds the lead. Cal.com holds the technician calendar. Twilio carries SMS and the telephone audio. ElevenLabs holds the speech model and turn-taking. The new software is the lead path and the tool API that makes Emma’s words match a real booking.

```
Homeowner on lumienergy.us
        |
        v
Sheet + Discord + Supabase row
        |
        v
Apps Script -> Zoho lead (Lumi Solar layout)
        |
        v
Cloud Run API
   |-- welcome SMS (if consent)
   |-- outbound call: Emma
            |
            +-- get_available_slots
            +-- book_slot
            +-- mark_bill_sms_ready
            +-- voicemail_detection (platform tool)
        |
        v
Post-call webhook -> transcript, callback, solar email
        |
        v
Staff dashboard and Zoho
```

2.2 Product Functions

- Accept a solar enquiry and create the Zoho lead.
- Send the welcome SMS only with consent.
- Dial Emma automatically and pass the lead’s name, address, phone, and the three bookable days.
- Qualify on identity, summer bill, interest, and who decides.
- Offer exactly two live slots at a time and book only the slot the customer picked.
- Text the bill-upload link after a successful booking when consent allows.
- Treat voicemail and no-answer as missed calls and schedule a callback.
- Email a preliminary solar PDF, with a self-serve calendar link only when the visit is not already booked.
- Let staff read the thread and write a sale back to Zoho.

2.3 User Classes and Characteristics

Solar homeowner. Uses the site once and takes one phone call. May be busy, sceptical, or unsure of the bill. Must be able to answer short questions and pick one of two times. This is the primary user of the voice agent.

Closer. Uses Zoho daily and the dashboard for the text thread and the sale. Should see a booked visit without listening to every recording. Call recording is disabled on the outbound request.

Operator. Deploys the API and edits the agent prompt and tool URLs. This class changes credentials and the qualification threshold.

Emma, the voice agent. Not a person. She may speak only from the prompt and from tool results. She is the most important automated actor in this specification.

2.4 Operating Environment

The API runs as a Linux container on Google Cloud Run. The solar site and the dashboard are Next.js applications. Data is in Supabase. The agent runs on ElevenLabs and calls a Twilio number linked to that agent. The business timezone is America/Phoenix. Browsers are current Chrome, Safari, Firefox, and Edge. The homeowner’s phone is the device that receives the call and the SMS.

2.5 Design and Implementation Constraints

- SMS follows the Telephone Consumer Protection Act. No nurture or bill-upload text shall be sent without consent, and STOP shall opt the phone out [2].
- The agent shall not compute dates. Slot times come from Cal.com through get_available_slots.
- The agent shall not say the customer is booked until book_slot returns success.
- Sunday is not a bookable visit day. The window is the next three bookable days.
- All spoken times are Arizona time unless the customer asks otherwise.
- The visit is at the house. The prompt forbids Google Meet, Zoom, a virtual meeting, and a calendar invite.
- book_slot shall ignore a name typed by the model and shall load the name and address from the lead row that matches the phone number.
- Tool endpoints shall reject a wrong tool API key when that key is configured.
- Call recording on the outbound request shall remain disabled.
- Secrets shall stay in environment variables and in the agent’s server-side tool configuration.

2.6 User Documentation

The homeowner’s instructions are the call itself, the SMS, and the upload page. The operator’s script is the agent prompt in the repository and the comments on the Apps Script. This SRS, the synopsis, and the project report are the academic documents. Closers need a one-page note that a booked visit was made by Emma and that the Zoho note from a later customer reschedule was automatic.

2.7 Assumptions and Dependencies

- The voice agent is enabled in the operating configuration this SRS describes. A disabled flag would skip the dial. That mode is not the system under specification.
- ElevenLabs remains able to place a Twilio outbound call to the agent id configured for Emma.
- The tool base URL configured on the agent points at this API, and the tool key matches.
- Cal.com continues to return slots for the solar event type and to notify Zoho when a booking changes.
- Zoho refresh tokens remain valid.
- The sheet headers stay aligned with the script.
- A homeowner on a landline can be called but may not receive the bill-upload SMS.

3. External Interface Requirements

3.1 User Interfaces

Solar website. Home page and offer landings collect first name, last name, email, phone, address, bill range, utility, home ownership, existing solar, SMS consent, and terms consent. Address entry may suggest completions. Thank-you states follow a successful submit. /upload/{token} accepts a bill photo or PDF. /appointment-confirmed shows the booked visit from query parameters name, start, address, and booking id, and offers a reschedule link.

Voice interface. There is no screen. Emma speaks short turns and asks one question at a time. She addresses the customer by first name. She reads spoken_offer rather than an ISO timestamp. She does not mention tools, APIs, or calendars by those words.

Staff dashboard. Leads, Inbox, and Sales for solar records. The inbox sends an SMS reply. Sales writes revenue and profit to Zoho.

Zoho. Closers use the Lumi Solar lead layout. The product fills the lead. It does not replace the Zoho screen.

3.2 Hardware Interfaces

No custom hardware. The call uses the public telephone network through Twilio. The homeowner answers a mobile or landline. A phone camera is enough for the bill photo. Roof images in the PDF come from Google’s map API, not from a camera attached to this system.

3.3 Software Interfaces

| System | Direction | Data |
| --- | --- | --- |
| Solar website | Writes Supabase, Discord, and the sheet | Lead fields and upload URL |
| Google Apps Script | Creates the Zoho lead and POSTs the webhook | Row plus zoho_lead_id |
| ElevenLabs outbound-call API | API starts the call | agent id, Twilio phone-number id, destination, dynamic variables |
| Emma’s tools | Agent calls the API during the call | See feature 4.5 |
| ElevenLabs post-call webhook | Platform posts to the API | Transcript, termination, tool trace, conversation id |
| Cal.com API | Slot tool reads inventory. book_slot creates the visit. | Start time, attendee, booking uid |
| Zoho CRM API | Script and API read and write Leads and Notes | Lumi Solar fields |
| Twilio SMS | Welcome, bill link, nurture, inbound STOP | To, from, body |
| Cloud Tasks | Callbacks, nurture, follow-up email | JSON plus job secret |
| Resend | Solar and follow-up email | Body and PDF |
| Supabase | Lead, messages, bill files | processed_leads, customer_messages, bill_uploads |

Dynamic variables passed at dial time shall include first_name, last_name, full_name, address, phone_no, sched_day_1, sched_day_1_speech, sched_day_2, and sched_day_3.

3.4 Communications Interfaces

Service calls use HTTPS. Sheet webhooks and internal jobs use a shared secret. ElevenLabs post-call requests shall be checked with the platform signature when the secret is set. Tool calls use the header X-Tool-Api-Key. A failed tool authentication shall return HTTP 401. A booking that Cal.com rejects shall return an error so Emma can apologise and retry once, which is what the prompt tells her to do. She shall not treat an error body as a success.

4. System Features

4.1 Solar lead capture

4.1.1 Description and Priority

The website accepts the enquiry that Emma will call. Priority: High.

4.1.2 Stimulus/Response Sequences

The homeowner submits the form. The site inserts processed_leads with business unit Lumi Energy and an upload token, alerts Discord, and appends the sheet. The script creates the Zoho lead on the Lumi Solar layout and calls the API.

4.1.3 Functional Requirements

REQ-1: The form shall collect name, email, phone, address, and the consent answers, and shall accept bill range, utility, ownership, and existing solar.

REQ-2: The site shall create a row key and a single-use upload token before the sheet append.

REQ-3: The sheet script shall create the Zoho lead on the Lumi Solar layout and shall send zoho_lead_id to the API.

REQ-4: The API shall persist the lead and bind the Zoho id when it is present.

4.2 Automatic outbound call

4.2.1 Description and Priority

After the lead is stored, Emma calls. This is the centre of the product. Priority: High.

4.2.2 Stimulus/Response Sequences

The orchestration service normalises the phone, cancels older callback rows for that same number, and POSTs to the ElevenLabs Twilio outbound-call endpoint. The agent id and the linked Twilio number are the configured solar agent. If the number is unusable, the lead is marked failed and the dial-fail email path may run. If ElevenLabs returns an error, the client retries a small number of times. A second dial for a row already in progress shall not start.

4.2.3 Functional Requirements

REQ-5: With the voice agent enabled, acceptance of a new solar lead shall start Emma’s outbound call. This SRS assumes that flag is on.

REQ-6: The call request shall include the dynamic variables in Section 3.3.

REQ-7: The call request shall set call recording off.

REQ-8: An invalid phone shall not be dialled and shall be stored as a failed attempt.

REQ-9: A repeated webhook for the same row key shall not place a second simultaneous call.

4.3 Emma’s conversation

4.3.1 Description and Priority

The spoken policy. Priority: High.

4.3.2 Stimulus/Response Sequences

Emma asks “is this {first name}?”. If the person is busy she offers to be brief. She asks for the highest summer electricity bill. If the answer is vague she asks once for an approximate figure and does not continue without a number or a clear refusal. Under $120 she ends politely. Otherwise she asks whether they have already looked for a solution, offers a technician visit with no obligation, and asks whether anyone else decides. She then schedules inside three bookable days, morning, afternoon, or evening. She offers two times by reading spoken_offer. If the customer rejects both, she asks what time they prefer and calls the slot tool again with that phrase. If the window is exhausted she hands the lead to a human within an hour or two and does not offer more times. After a successful booking she confirms the address, says the consultant is holding the time, triggers the bill text, and closes with the line that Ivan will see them there.

Objections she is allowed to answer are limited. A question she cannot answer is written down for the specialist, not invented. “Is this a sales call?” is answered as a check of whether the program fits the home. Price is deferred until the visit has the facts. Company experience is answered with the fixed line about seven-plus and fifteen-plus years. Lasting lack of interest ends the call.

4.3.3 Functional Requirements

REQ-10: The agent shall identify herself as Emma from Lumi Energy and shall use the first name from the lead.

REQ-11: The agent shall end the qualification when the summer bill is under $120.

REQ-12: The agent shall ask one question at a time and shall keep turns short.

REQ-13: The agent shall describe the appointment only as a visit to the home.

REQ-14: The agent shall never offer more than two times in one turn, and those times shall be the tool’s spoken_offer for the day she named.

REQ-15: The agent shall not speak an ISO timestamp to the customer.

REQ-16: The agent shall not claim a booking, a confirmation, or a scheduled visit before book_slot succeeds.

REQ-17: On a tool failure she shall apologise briefly and retry that tool once.

REQ-18: She shall not mention internal systems, APIs, tools, or calendars.

4.4 Scheduling window

4.4.1 Description and Priority

The calendar rules the prompt is not allowed to relax. Priority: High.

4.4.2 Stimulus/Response Sequences

At dial time the API computes the next three dates that are not Sunday. sched_day_1_speech is “tomorrow” when tomorrow is one of those dates, otherwise the weekday, which is the Saturday-to-Monday case. Emma’s first scheduling question uses that variable exactly. Later days are referred to by weekday name from sched_day_2 and sched_day_3.

4.4.3 Functional Requirements

REQ-19: Slot search shall interpret day queries in America/Phoenix.

REQ-20: Sunday shall be excluded from the bookable window.

REQ-21: The window shall contain three bookable days and shall not be extended by the agent when it is exhausted.

REQ-22: A slot lookup shall be one day per tool call. The agent shall not bulk-fetch the three days in one call during the normal flow.

4.5 Agent tools

4.5.1 Description and Priority

The tools are the only way Emma changes the outside world. Priority: High.

4.5.2 Stimulus/Response Sequences

get_available_slots. The agent calls GET /scheduling/slots with day_query, time_period (morning, afternoon, evening, or any), an optional time_preference such as “around 2”, and a limit. The service reads Cal.com, filters to the period or the spoken preference, and returns resolved_date, weekday, has_slots, has_any_slots, a slots array whose start values are the only legal booking inputs, and spoken_offer. If the day has no openings it also returns next_day_query and next_day_ask.

book_slot. The agent calls POST /scheduling/book with the chosen start and attendee.phoneNumber equal to the phone_no variable. The service finds the lead by that phone, books on Cal.com, and stores the booking id and start. The response status is success only when the booking exists. The name field on the request is ignored.

mark_bill_sms_ready. After success, and not otherwise, the agent calls POST /webhooks/lumi/mark-bill-sms-ready with phone_no. The service sends the upload-link SMS if the latest call row for that phone is allowed to receive transactional SMS. It does not wait for the post-call webhook.

voicemail_detection. This is ElevenLabs’ system tool, not an endpoint in this API. If the transcript shows that tool, the call is classified as voicemail rather than as a finished qualification.

4.5.3 Functional Requirements

REQ-23: Every custom tool shall require the tool API key when the key is configured.

REQ-24: get_available_slots shall return at most two slots for the offer the agent reads, and each slot shall include the exact start string required by book_slot.

REQ-25: spoken_offer shall include the weekday and the local times so the agent does not format the clock herself.

REQ-26: book_slot shall load name and address from the lead row and shall not trust the model’s attendee name.

REQ-27: book_slot shall persist the Cal.com booking uid and the start on the lead.

REQ-28: mark_bill_sms_ready shall send at most the consent-checked upload SMS and shall not send it when consent is missing.

REQ-29: A voicemail detection in the transcript shall be treated as not answered.

4.6 After the call

4.6.1 Description and Priority

The call has to leave a record even when Emma never reaches a booking. Priority: High.

4.6.2 Stimulus/Response Sequences

ElevenLabs posts call end or initiation failure. The API verifies the signature, stores analytics, and decides whether the conversation was answered. A miss schedules a callback through Cloud Tasks. The solar report email is sent according to the outcome: booked visits do not also receive a self-serve booking link; unbooked, unanswered, and failed dials may include that link. Discord receives a call-ended summary. A later Cal.com create, reschedule, or cancel still updates the Zoho lead, including an automatic note when the customer changes the visit.

4.6.3 Functional Requirements

REQ-30: The post-call handler shall store duration, success, summary, and termination reason against the conversation.

REQ-31: An unanswered call or a voicemail shall be eligible for a callback. Staff shall be able to cancel pending callbacks.

REQ-32: The solar email shall include the self-serve calendar link only when the visit was not booked on the call.

REQ-33: Initiation failure shall be handled without waiting for a transcript.

REQ-34: Inbound STOP shall set sms_opt_out and shall cancel an active nurture sequence. Any other reply from a known lead shall cancel stage two without a global opt-out.

4.7 Follow-up when the visit was not booked

4.7.1 Description and Priority

Emma does not always book. The sequence continues. Priority: Medium.

4.7.2 Stimulus/Response Sequences

Stage two sends touch 1 immediately and schedules touches 2 to 10 on day offsets 0, 1, 2, 4, 6, 8, 11, 14, 18, and 22. Quiet hours in Phoenix move a nurture text forward. A task whose lead is no longer active does not send. Booking turns follow-up emails off in Zoho.

4.7.3 Functional Requirements

REQ-35: A nurture SMS shall not be sent without consent or after opt-out.

REQ-36: Each automated SMS shall end with a STOP instruction.

REQ-37: A task shall re-read the lead and shall skip when the sequence is not active or the attempt was already sent.

4.8 Bill upload

4.8.1 Description and Priority

The visit is more useful if the closer has the bill. Priority: Medium.

4.8.2 Stimulus/Response Sequences

The homeowner opens the token URL from the SMS Emma triggered, or from the sheet link. An image or PDF is stored in the private bucket and attached to the Zoho lead. A confirmation SMS is sent at most once.

4.8.3 Functional Requirements

REQ-38: The upload URL shall not reveal other customers’ files. The bucket shall not be public.

REQ-39: Allowed types shall include JPEG, PNG, WEBP, HEIC, and PDF.

REQ-40: A successful upload shall mark the token used.

4.9 Staff dashboard and sale close

4.9.1 Description and Priority

People still close the sale. Priority: Medium.

4.9.2 Stimulus/Response Sequences

Staff open solar leads, read the thread, reply by SMS, and submit revenue, pre-inspection profit, post-inspection profit, and sale date. The API writes those fields on the Zoho lead and adds a note.

4.9.3 Functional Requirements

REQ-41: Sale write-back shall use the stored Zoho id when it exists, and otherwise a unique email or phone match on the Lumi Energy business unit.

REQ-42: The API shall not pick an arbitrary Zoho lead when several leads share one email.

REQ-43: Inbox replies shall be logged as outbound messages.

5. Other Nonfunctional Requirements

5.1 Performance Requirements

The form should return in a few seconds. The dial is started after the lead is stored and shall not be performed inside the homeowner’s browser request. Slot lookup should return before Emma’s filler sentence (“Let me just pull up our availability”) becomes awkward, which means a few seconds, not a minute. Post-call work may send email and Discord after the webhook is accepted, but the webhook itself should not wait on a long retry loop beyond the call client’s own retries.

5.2 Safety Requirements

The agent shall not promise a bill reduction. She shall not quote a price. She shall not tell the customer a technician is booked until Cal.com has accepted the slot. The visit shall be described as optional. Financing or savings language in email shall stay preliminary. Bill files are private.

5.3 Security Requirements

Tool keys, Twilio credentials, and Zoho tokens shall not be placed in the prompt text that could be spoken, and shall not be committed into the academic documents. Post-call signatures shall be verified when the secret is set. The upload bucket shall be private. Inbound speech and SMS shall be treated as untrusted data, never as commands to the server.

5.4 Software Quality Attributes

Correctness of the booking is preferred over a smoother conversation. A skipped duplicate text is a success. The slot tool and the booking tool shall be testable without a live phone call by calling the HTTP endpoints with the tool key. Logs shall include the row key, the conversation id, and the skip reason.

5.5 Business Rules

- The program threshold on the call is a summer bill under $120, which ends qualification.
- Visits are in person, on the address stored for the lead, and not on Sunday.
- Emma may offer only two times, both from the latest slot response for the day she named.
- The closer’s name used at the close of a booked call is Ivan.
- Sale figures are entered by staff. Emma does not invent revenue.
- A customer who later moves or cancels the visit on the booking page is recorded in Zoho as the customer’s own action.

6. Other Requirements

The operational tables are processed_leads, customer_messages, and bill_uploads, as described in the project report. Copy is English. Dates spoken on the call and shown on the confirmation page are America/Phoenix.

The agent prompt is a controlled artefact. Changing the bill threshold, the number of offered times, or the visit type requires a prompt change and a matching change to this SRS. Changing Cal.com or the timezone requires a change to the slot tool, not only to the prompt.

Appendix A: Glossary

| Term | Meaning |
| --- | --- |
| Emma | The Lumi Energy outbound voice agent |
| Dynamic variable | A value injected into the prompt at dial time, written {{first_name}} and similar |
| spoken_offer | The exact phrase the slot tool returns for Emma to read |
| book_slot | The tool that creates the Cal.com visit |
| get_available_slots | The tool that returns two real openings |
| mark_bill_sms_ready | The tool that texts the upload link after a successful booking |
| Bookable window | The next three non-Sunday days |
| Stage 2 | The ten-touch SMS sequence used when the visit was not booked |
| STOP | The inbound keyword that opts the phone out |

Appendix B: Analysis Models

The component diagram is in Section 2.1. Lead states relevant to the agent are: new, dialling, answered-and-booked, answered-not-booked, voicemail or no-answer, callback scheduled, disqualified on bill, and opted out. Use-case text is in the project report, Chapter 3.

Appendix C: To Be Determined List

TBD-1: Student name, roll number, guide, and department on the printed cover.

TBD-2: The exact staff login method on the deployed dashboard. The requirement is that lead and sale APIs are not anonymous.

TBD-3: The number and spacing of callback attempts can be tuned in configuration. The requirement is that a miss can be retried and that staff can cancel the retry.
