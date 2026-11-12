Automated Voice-Agent Lead Qualification and Appointment System for Residential Solar

A Report submitted
in partial fulfillment for the degree of
Bachelor of Engineering
in
[Name of the branch]
(Session [20__]–[20__])

Submitted By: [Student name] ([Roll number])
Guided By: [Project guide name]

Department of [Department name]
Institute of Engineering & Technology
Vikramshila Campus
Devi Ahilya Vishwavidyalaya, Indore (M.P.)
https://ietdavv.edu.in

[Month Year]

When this file is pasted into Word, set the title in Times New Roman, 20 point, bold. Set the lines under the title in Times New Roman, 16 point. Set chapter body text in Times New Roman, 12 point, justified, with 1.5 line spacing. Set main headings at 14 point and subheadings at 13 point. Print on JK Bond paper. Use colour for the figures. Number the certificate through the abstract with Roman numerals, and start Chapter 1 at Arabic page 1.

CERTIFICATE

The project report entitled “Automated Voice-Agent Lead Qualification and Appointment System for Residential Solar” submitted by [FULL NAME OF THE PROJECT TEAM] is approved for partial fulfillment for the award of Bachelor of Engineering in [Name of the Branch] degree by Devi Ahilya Vishwavidyalaya, Indore.

Internal Examiner ________________________

External Examiner ________________________

RECOMMENDATION

The dissertation entitled “Automated Voice-Agent Lead Qualification and Appointment System for Residential Solar” submitted by [FULL NAME OF THE PROJECT TEAM] is a satisfactory account of the bonafide work done under my supervision and is recommended towards the partial fulfillment for the award of Bachelor of Engineering in [Name of the Branch] degree by Devi Ahilya Vishwavidyalaya, Indore.

Date: ______________

[NAME OF PROJECT GUIDE]
Department of [Name of Department]

Counter signature of Head of Department with seal

CANDIDATE DECLARATION

We hereby declare that the work which is being presented in this project entitled Automated Voice-Agent Lead Qualification and Appointment System for Residential Solar in partial fulfillment of the degree of Bachelor of Engineering in [Name of the Branch] is an authentic record of our own work carried out under the supervision and guidance of [Name of Project Guide], [post of the guide], Department of [Name of the Department], Institute of Engineering and Technology, Devi Ahilya Vishwavidyalaya, Indore.

We are fully responsible for the matter embodied in this project in case of any discrepancy found in the project and the project has not been submitted for the award of any other degree.

Date: ______________
Place: Indore

Signature of student 1
[Name of student 1]

Signature of student 2
[Name of student 2, or omit]

Signature of student 3
[Name of student 3, or omit]

SELF-DECLARATION OF PLAGIARISM REPORT

The project report entitled “Automated Voice-Agent Lead Qualification and Appointment System for Residential Solar” submitted by [FULL NAME OF THE PROJECT TEAM] in partial fulfillment of the requirement for the award of the degree of B.E. in [Branch] has been checked for plagiarism using a standard plagiarism detection tool.

The similarity index of the report is ______ %, which is within the permissible limit as per institute and university norms.

I hereby declare that:

- The work submitted is original and has not been copied from any source without proper citation.
- All referenced materials have been duly acknowledged.
- In case of any discrepancy found in future, I shall be solely responsible for the same.

Signature of student(s):

1. ______________
2. ______________
3. ______________

Date: ______________

ACKNOWLEDGEMENTS

This project was completed under the supervision of [Guide name] in the Department of [Department name]. The guide’s review kept the work on a call a closer could trust, rather than on a demo that only sounded fluent. I thank the guide for insisting that a booked sentence had to match a calendar record.

I thank the Head of the Department for the laboratory time and for allowing a live solar workflow to be the final-year project, and the Director of the Institute of Engineering and Technology for the academic setting in which the project is carried out.

The speech model, the telephone network, the calendar, and the CRM are published platforms. The original work is the policy that connects them: who Emma is, what she may ask, which tools she may call, and what the system does when the call ends. The closers who opened the resulting Zoho leads were the practical test of that policy.

ABSTRACT

Lumi Energy loses solar consultations when a website enquiry waits for a person to dial. This project places that first call with a voice agent named Emma and ties her words to tools that cannot be talked around. A homeowner submits a form on lumienergy.us. The site stores the lead, alerts Discord, and appends a Google Sheet. Apps Script creates a Zoho lead on the Lumi Solar layout and notifies a FastAPI service on Cloud Run. The service sends a welcome SMS when consent was given and then starts an outbound call through ElevenLabs and Twilio. Emma confirms the name, asks for the highest summer electric bill, and ends the call if it is under $120. Otherwise she offers an in-person technician visit. She never invents a time. The tool get_available_slots returns two real openings in America/Phoenix, skipping Sundays, inside a three-day window. book_slot creates the Cal.com visit and only then may she say the customer is booked. mark_bill_sms_ready texts a private upload link when SMS consent is on the lead. A platform voicemail tool marks a machine greeting as a missed call so a callback can be scheduled. After the call, the service stores the outcome, emails a preliminary solar PDF, and includes a self-serve calendar link only if the visit was not already booked. Staff still close the sale in Zoho and in a dashboard. The result is a qualifying call whose booking the calendar, not the language model, has confirmed.

TABLE OF CONTENTS

| Description | Page |
| --- | --- |
| Certificate | i |
| Recommendation | ii |
| Candidate Declaration | iii |
| Plagiarism check report | iv |
| Acknowledgements | v |
| Abstract | vi |
| Chapter 1 Introduction | 1 |
| 1.1 Overview and issues involved | 1 |
| 1.2 Problem definition | 3 |
| 1.3 Proposed solution | 4 |
| Chapter 2 Literature Survey | 8 |
| 2.1 Existing solutions | 8 |
| 2.2 Methodology | 10 |
| Chapter 3 Analysis and Design | 12 |
| 3.1 Software requirements | 12 |
| 3.2 Hardware requirements | 13 |
| 3.3 Analysis diagrams | 14 |
| 3.4 Design diagrams | 18 |
| Chapter 4 Implementation and Testing | 21 |
| 4.1 Database design | 21 |
| 4.2 Class diagram | 23 |
| 4.3 Test cases | 26 |
| Chapter 5 Conclusion | 29 |
| References | 31 |
| Appendix | 32 |

Page numbers above are the intended Word pagination. Insert the real numbers after formatting.

Chapter 1 Introduction

1.1 Overview and issues involved

Residential solar starts as a phone call about a bill. The homeowner has seen an advertisement about lowering electricity cost, has typed a name and an address, and expects a person to explain whether a visit is worth their time. Lumi Energy’s closer cannot sit on that queue all evening. A late call is often a lost call, because the same homeowner has already spoken to another company.

A fluent automated caller is not, by itself, a solution. Large speech models will happily name a time that was never free, say “you’re booked” because the customer said yes, and describe a video meeting when the technician is supposed to come to the house. They will also keep talking to a voicemail greeting as if it were a person. The engineering problem is to let the model handle turn-taking and to take the calendar, the booking confirmation, and the bill text out of the model’s imagination.

Several issues follow from that split.

The agent needs the lead, not a blank line. The first name, the address to confirm, and the phone number that Cal.com must store have to be injected when the call starts. If Emma invents a phone number, the booking lands on the wrong person. The implementation therefore passes dynamic variables and then, at booking time, ignores any name the model sends and loads the lead from the database by phone.

The agent needs a narrow script. One question at a time. A summer-bill threshold. A fixed answer for “is this a sales call?” and for “how much does it cost?”. Anything outside that list is written down for the specialist rather than answered from guesswork. The visit is always physical. The prompt forbids Google Meet, Zoom, and a virtual meeting.

The agent needs tools with return values she is required to obey. get_available_slots speaks the offer. book_slot is the only success that may be called a booking. mark_bill_sms_ready is the only path for the upload text during the call, and it still checks consent. Voicemail detection is how a tape is not stored as a qualification.

The rest of the pipeline still matters. The website, the sheet, Zoho, the welcome SMS, the post-call email, and the callback exist so that Emma’s call has a lead to open and a record to leave. This report describes that whole solar path, and it spends its detail on the call, because that is the part a generic CRM does not do.

The operating assumption of this report is that the voice agent is on. A new solar lead is dialled. A configuration flag can skip the dial for maintenance. That flag is not the system being submitted.

1.2 Problem definition

The problem is to qualify a Lumi Energy website lead by telephone and to book an in-person consultation without a setter on every call, under rules the calendar can enforce.

The system must:

1. Capture the solar form into Supabase, Discord, Google Sheets, and a Zoho lead on the Lumi Solar layout.
2. Send a welcome SMS only when transactional consent is yes, then place Emma’s outbound call.
3. Pass the lead’s identity and the three bookable weekdays into the prompt.
4. Qualify on the highest summer bill and stop under $120.
5. Offer exactly two real slots, on a non-Sunday day inside a three-day window, in America/Phoenix.
6. Create the visit only through book_slot, using the slot’s exact start time and the lead’s own phone.
7. Text the bill-upload link only after that success and only with consent.
8. Treat voicemail and no-answer as missed calls, store the outcome, and email a solar follow-up whose calendar link depends on whether the visit was booked.

1.3 Proposed solution

Figure 1.1 is the path. The call sits in the middle on purpose.

```
Homeowner submits the Lumi Energy form
        |
        v
Website: database row, upload token, Discord, Google Sheet
        |
        v
Apps Script creates the Zoho lead (Lumi Solar) and calls the API
        |
        v
API sends welcome SMS if consent allows
        |
        v
API dials Emma (ElevenLabs + Twilio)
   variables: first name, address, phone, three bookable days
        |
        +-- Step 1  identity
        +-- Step 2  summer bill  (end if under $120)
        +-- Step 3  interest and decision maker
        +-- Step 4  get_available_slots, two times, up to 3 days
        +-- Step 5  book_slot
        +-- Step 6  confirm address, mark_bill_sms_ready
        +-- Step 7  close: Ivan will see you there
        |
        v
Post-call webhook: summary, callback or solar email, Discord
```

Who Emma is. The prompt names her Emma from Lumi Energy. She calls people who responded to an advertisement about lowering the electric bill. Her motive, which she is told to use in her own words rather than as a recited paragraph, is that the visit checks whether the program can help this house. If it cannot, the homeowner does not have to continue. There is no obligation.

What she is given at the start of the call. The outbound request is a single HTTPS call to ElevenLabs: the agent id, the Twilio phone-number id already linked to that agent, the destination number, and a map of dynamic variables. Those variables are first_name, last_name, full_name, address, phone_no, sched_day_1, sched_day_1_speech, sched_day_2, and sched_day_3. sched_day_1_speech is the phrase she must use for the first scheduling question. On a normal weekday it is “tomorrow”. On Saturday it is “Monday”, because Sunday is not bookable and the code will not let her say “tomorrow” when tomorrow is Sunday. Recording is turned off on this request.

The seven steps of the call.

Step 1, introduction. “Hey, is this {first name}?” If they confirm: she introduces herself and asks for a minute. If they are busy: she says she will be quick and continues.

Step 2, qualification. She asks for the highest summer electricity bill last year. A vague answer gets one request for an approximate figure. She does not move on without a number or a clear refusal. Under $120 she says the program may not be the best fit and ends.

Step 3, interest. She asks whether they have already looked for a solution. Either way she offers a technician who can explain options for this house, and she asks if more information would help. If they agree, she says the information is personalised and that she can book a visit, then asks whether anyone else who decides should be there. If they decline, she makes one soft offer of a short visit and, on a second no, ends the call.

Step 4, scheduling. She asks whether morning, afternoon, or evening is better on the first bookable day, using sched_day_1_speech exactly. When they pick a block she calls get_available_slots once for that day and that block. While it loads she may say she is pulling up availability. If has_slots is true she reads spoken_offer and nothing else. If that block is empty but the day has other slots, she tries another block. If the day is empty she reads next_day_ask and moves to the next weekday. A customer who rejects both times is asked what time they would prefer. Their words are sent back as time_preference with time_period any. After three days, scheduling_window_exhausted is true and she stops offering. She says someone from the team will reach out within an hour or two.

Step 5, booking. She matches the customer’s choice to one entry in the slots array from that same tool response, checks the weekday and date, and calls book_slot with that entry’s start field unchanged. She waits for success. Then she says they are booked for the local time and asks them to confirm the address variable.

Step 6, bill text. She says she will text a link to upload the bill so the visit can be prepared. She calls mark_bill_sms_ready with phone_no. She does not call it if booking failed. She waits for the tool before she hangs up the script.

Step 7, close. “Alright {first name}, thanks for taking the call, Ivan will see you there.”

Tools. They are specified again in Chapter 4 because they are the implementation. In one paragraph: get_available_slots reads Cal.com and speaks two times; book_slot writes the visit and the lead row; mark_bill_sms_ready sends one consent-checked SMS; voicemail_detection is ElevenLabs’ own tool and the post-call code looks for it so a greeting is not an answer.

Why the tools sit on this API. Emma could have been given a Cal.com API key inside the agent dashboard. That would let the model book any payload it composed. The proxy checks the day, the timezone, the two-slot limit, and the phone against the lead table. The prompt tells her the policy. The code enforces the part of the policy that must not depend on her obeying.

Chapter 2 Literature Survey

2.1 Existing solutions

HubSpot represents the CRM-plus-sequence products. A form can create a contact and start email. The advantage is the single customer record, which is why this project still writes Zoho. The drawback is the live call. HubSpot does not ask a summer-bill question, apply a $120 floor, and refuse to confirm a slot the calendar did not return. The gap is a dialogue policy with tools.

GoHighLevel is closer to home services. Funnels, SMS, and calendars ship together. Teams use it because a non-developer can launch a campaign. The limitation is a spoken script that must stay inside three non-Sunday days, must offer exactly two times, and must text a bill link only after Cal.com succeeds. Those checks are easier to unit-test as HTTP handlers than as nested campaign steps. This project keeps the calendar and the CRM, and puts the policy in the API Emma calls.

Cal.com is the scheduling product actually integrated [8]. It lists slots and creates bookings, and it can tell Zoho when the customer later moves or cancels. It does not speak. A booking page on the website helps the homeowner who never answered the phone. It does not replace Emma for the homeowner who did answer. The post-call email uses that page only when she did not already book.

EnergySage is a solar marketplace. The homeowner enters an address and a bill, and several installers respond. That is a demand channel. It is not a private qualifier for one company, and the consent and the visit would belong to the marketplace’s process. Lumi Energy’s own form keeps the lead, and Emma uses the bill range only as a start. She still asks for the summer figure on the call.

ElevenLabs Conversational AI is the speech runtime used here [5]. It places the outbound Twilio call, plays Emma’s voice, and invokes HTTP tools mid-conversation. The research point that matches the design is older than that product. Adamopoulou and Moussiades describe chatbots as useful when they complete a task in another system [3]. Jurafsky and Martin describe the same constraint for spoken dialogue: the system should ground a confirmation in a successful back-end act [4]. Emma’s “you’re booked” line is that act’s acknowledgement, not a guess. Twilio is only the telephone and SMS transport [6], [7]. Zoho is only the closer’s record [9].

The gap is the join. Marketplaces produce leads. CRMs store them. Calendars hold empty slots. Voice platforms talk. None of them, alone, will stop talking when the bill is too low and will book a physical visit from live inventory. That is the project.

2.2 Methodology

The work followed the call.

Step 1. The solar site and the sheet were built so a lead existed with a phone, an address, consent, and a Zoho id before anyone dialled.

Step 2. The outbound client was written against ElevenLabs, with the dynamic variables the prompt already expected.

Step 3. The slot tool was written and tested with phrases the agent actually says: “tomorrow”, “day after tomorrow”, “morning”, “around 2”. Sunday skipping was tested by date, not by hoping the model knew the calendar.

Step 4. The booking tool was written to key off the phone number and to require the start string from the slot tool. A successful response is what the prompt is allowed to call a booking.

Step 5. The bill tool was added at the point in the script after the address confirmation, so the text could not go out for a call that never booked.

Step 6. The post-call webhook was connected: analytics, voicemail classification, callback, solar email, Discord.

Step 7. The prompt was revised against those tools until the spoken steps and the HTTP contracts used the same field names. The prompt in the repository is the specification of Emma’s behaviour. The routes are the specification of what she is allowed to change.

Concepts a reader needs. A dynamic variable is a blank in the prompt filled at dial time. A tool is an HTTP call the agent makes while the customer is still on the line. The spoken_offer is a sentence the server built so the model does not format “08:00” into the wrong hour. Idempotency means a second delivery of the same job does not send a second text. Quiet hours apply to the later nurture sequence, not to the live call. Deluge is Zoho’s scripting language. It receives Cal.com webhooks and updates the lead after Emma, or the customer, has changed the visit. The voice agent does not speak Deluge and does not hold a Zoho token.

Chapter 3 Analysis and Design

3.1 Software requirements

Python and FastAPI implement the webhooks and the three tools. The choice is practical: the same process can validate a tool body, call Cal.com, and write Supabase. The full requirement list is the SRS. This section only justifies the stack.

ElevenLabs is the speech engine because building telephony, turn-taking, and a voice was not the project. The project is the policy and the tools. Twilio is already linked inside that ElevenLabs phone number, so one outbound API call both rings the handset and attaches Emma.

Cal.com is the inventory. The slot tool does not keep its own copy of the technician’s day. It asks Cal.com and then filters.

Zoho is the closer’s CRM. The sheet script creates the Lumi Solar lead. Later booking updates and sale fields go back to that lead. Emma does not call Zoho during the conversation. The booking id on the lead row is what later sync uses.

Supabase holds the lead Emma’s booking tool must find. Cloud Tasks hold callback and nurture alarms. Resend sends the solar PDF. Next.js is the website and the staff dashboard. Google Maps supplies an optional roof image for that PDF.

3.2 Hardware requirements

Development needs a computer with Python 3, Node.js, and a network path to the voice vendor. No GPU is required. The model runs on ElevenLabs.

Production is a Cloud Run container. A call is one outbound HTTPS request plus, during the conversation, a handful of short tool calls. The heavy work is not in this process. The homeowner needs a phone. The closer needs a browser for Zoho and the dashboard. A phone camera is enough for the bill. No on-site sensor is part of the system.

3.3 Analysis diagrams

3.3.1 Use case model

Actors are the Solar Homeowner, Emma, and the Staff User. Secondary actors are ElevenLabs, Cal.com, Twilio, and Zoho.

```
Solar Homeowner ---- submit form
                 ---- answer Emma
                 ---- pick one of two times
                 ---- upload the bill

Emma ------------- qualify
                 ---- call get_available_slots
                 ---- call book_slot
                 ---- call mark_bill_sms_ready

Staff user ------- read the lead and the thread
                 ---- record the sale
                 ---- cancel a callback
```

3.3.2 Use case descriptions

UC-01 Start Emma’s call

Use case id: UC-01
Actors: Orchestration API, ElevenLabs, Twilio, Solar Homeowner
Goal: The homeowner’s phone rings and Emma has the lead’s variables.
Preconditions: The lead is stored, the phone has at least ten digits, and the voice agent is enabled.
Postconditions: A conversation id is stored, or the dial is marked failed after retries.
Main flow:
1. The API normalises the phone and drops older callback rows for that number.
2. It POSTs the outbound-call request with the nine dynamic variables.
3. ElevenLabs bridges Twilio to Emma.
4. Emma begins at Step 1 of the prompt.
Alternate flow A, bad phone: no dial, lead marked failed, dial-fail report may be emailed.
Alternate flow B, vendor error: the client retries a small number of times, then records failure.
Special requirements: Recording remains off. A second request for the same row does not overlap another live dial.

UC-02 Qualify the bill

Use case id: UC-02
Actors: Emma, Solar Homeowner
Goal: Continue only if the summer bill is about $120 or more.
Preconditions: Identity was confirmed or the customer allowed her to continue.
Postconditions: Either the call moves to interest and scheduling, or it ends as a polite disqualification.
Main flow:
1. Emma asks for the highest summer bill.
2. If the figure is under $120 she thanks them and stops.
3. Otherwise she continues to Step 3.
Alternate flow A, vague answer: she asks once for an approximate number and waits.
Alternate flow B, refusal: she does not invent a bill and does not schedule.
Special requirements: She asks this before any slot tool is called.

UC-03 Offer and book a visit

Use case id: UC-03
Actors: Emma, slot tool, booking tool, Cal.com, Solar Homeowner
Goal: A Cal.com booking exists for a time she offered and the customer accepted.
Preconditions: Qualification passed. The bookable window was computed at dial time.
Postconditions: The lead stores booking uid and start. Emma has said the local time only after success. Or the window is exhausted and no booking exists.
Main flow:
1. Emma asks morning, afternoon, or evening for sched_day_1_speech.
2. get_available_slots returns at most two slots and spoken_offer.
3. She reads spoken_offer.
4. The customer picks one.
5. book_slot is called with that slot’s start and {{phone_no}}.
6. On success she confirms the address variable.
Alternate flow A, block empty: she tries another block the same day if has_any_slots is true.
Alternate flow B, day empty: she uses next_day_ask and the next weekday, up to three days.
Alternate flow C, both times rejected: she sends the customer’s phrase as time_preference.
Alternate flow D, tool error: she apologises and retries once. She does not claim success.
Alternate flow E, window exhausted: human handoff sentence, no further times.
Special requirements: She must not offer a slot from a different day than the one she named. She must not rebuild the start string.

UC-04 Send the bill link from the call

Use case id: UC-04
Actors: Emma, mark_bill_sms_ready, Twilio, Solar Homeowner
Goal: The upload SMS goes out before she finishes, and only after a booking, and only with consent.
Preconditions: book_slot returned success.
Postconditions: A customer_messages row exists, or the tool returns a skip because consent is missing.
Main flow:
1. Emma says she will text the upload link.
2. She calls the tool with phone_no.
3. The service finds the latest call row and checks sms_eligible.
4. Twilio sends the link.
5. She continues to the closing line.
Alternate flow A, booking never succeeded: she must not call the tool.
Alternate flow B, consent is no: no SMS, call still closes.
Special requirements: This send is during the call, not deferred to the post-call webhook.

UC-05 Finish an unanswered call

Use case id: UC-05
Actors: ElevenLabs, Orchestration API, Cloud Tasks
Goal: A voicemail or a no-answer becomes a callback, not a fake qualification.
Preconditions: The outbound attempt was made.
Postconditions: Analytics are stored. callback status is active when a retry is allowed. The solar email may include a self-serve link.
Main flow:
1. The platform posts call end or initiation failure.
2. The API checks the signature when configured.
3. If the transcript contains voicemail detection, answered is false.
4. A callback task is scheduled.
5. The report email includes the calendar link because the visit was not booked.
Alternate flow A, answered and booked: no self-serve calendar link on that email. Callback is not armed.
Special requirements: Initiation failure is handled without a transcript.

3.4 Design diagrams

3.4.1 Architecture

The style is a synchronous tool call during a live phone call, plus delayed jobs after the call. Emma blocks, from the customer’s point of view, only for a slot lookup she has already announced. Everything that can wait, including nurture and callbacks, is a Cloud Task.

```
Browser (lumienergy.us) --> Sheet --> Apps Script --> Zoho
                                \
                                 +--> Supabase <--+
                                                  |
Staff dashboard ---------------------------------> API on Cloud Run
                                                  |
                     ElevenLabs / Twilio <--------+--> Cal.com
                            |
                            +---- tool calls during the call
                                 /scheduling/slots
                                 /scheduling/book
                                 /webhooks/lumi/mark-bill-sms-ready
```

Emma is not a second database. She is a client of three routes. Zoho is updated by the sheet script at creation and by the booking sync when Cal.com emits an event. The closer does not have to scrape a transcript to see the visit.

3.4.2 Sequence diagram

Figure 3.2 is the successful visit.

```
Homeowner     Emma        Slot tool       Book tool        Cal.com       SMS
   |            |             |               |               |           |
   | answers    |             |               |               |           |
   |<---------->| qualify bill|               |               |           |
   | "morning"  |             |               |               |           |
   |----------->| GET slots   |               |               |           |
   |            |------------>| read inventory|               |           |
   |            |             |------------------------------>|           |
   |            | spoken_offer|               |               |           |
   |<-----------| "8 AM or 10"|               |               |           |
   | "8 AM"     |             |               |               |           |
   |----------->| POST book start=exact       |               |           |
   |            |---------------------------->| create        |           |
   |            |             |               |-------------->|           |
   |            | success     |               |               |           |
   |<-----------| "you're booked"             |               |           |
   | confirms address          |               |               |           |
   |            | mark_bill_sms_ready         |               |           |
   |            |-------------------------------------------------------->|
   |            | "Ivan will see you there"   |               |           |
```

Chapter 4 Implementation and Testing

4.1 Database design

processed_leads is the row Emma’s booking tool finds by phone. The columns that matter to the call are name, address, phone_no, email, sms_eligible, sms_opt_out, zoho_lead_id, offer_page, monthly_bill, upload_token, cal_booking_uid, appointment_start, conversation_id, call_sid, transcript_summary, call_successful, termination_reason, callback_status, next_retry_at, and the nurture and follow-up email flags.

One lead has many customer_messages. A message records direction, channel, message_type, body, and the provider id. The bill SMS Emma triggers is one of those rows. bill_uploads points at a private storage object for the file the homeowner sends later. The relationship is one lead to many files.

Zoho is external. The Lumi Solar lead holds the contact, the bill URL, consent, Appointment_Booked, Booking_uid, and the sale fields staff enter later. Emma does not write those CRM fields herself. The sheet script and the booking sync do.

4.2 Class diagram

```
Lead
  first_name, last_name, address, phone, email, consent, zoho_lead_id

ElevenLabsClient
  initiate_outbound_call(to_number, first_name, last_name, address, phone_no)
  builds dynamic variables, including scheduling_call_dynamic_vars()

CallOrchestrator
  process_lead(lead)     # dials when the voice agent is enabled
  retry_call_for_row()   # callback dial
  _dial()                # one live attempt, no overlap

Slot finder
  find_slots(day_query, time_period, time_preference)
  returns spoken_offer, slots[].start, has_slots, next_day_ask

book_appointment()
  looks up the lead by phone
  creates the Cal.com booking
  stores uid and start

PostCallSmsService
  send_bill_upload_at_step_6b(phone_no)

CallbackService
  on_conversation_ended()  # voicemail and no-answer

PostCallReportService
  on_conversation_ended()  # PDF email, calendar link only if not booked
```

ElevenLabsClient is the dialler. It does not contain the script. The script lives in the agent configuration, with a copy in the repository so the academic record matches production. initiate_outbound_call is the method that merges the lead fields with the three-day window.

CallOrchestrator is the gate. process_lead refuses a short phone, clears stale callbacks for that number, and calls _dial. When the voice-agent flag is on, this is the method the new-lead path uses. retry_call_for_row is the same dial with is_retry set, so a callback is not treated as a brand-new lead.

find_slots is the policy object behind get_available_slots. It resolves the day query against the bookable window, asks Cal.com, buckets hours into morning, afternoon, and evening, and applies a free-text preference such as “after 3” when the customer rejected the first pair. The return value’s spoken_offer is a finished sentence. The slots array is the only list book_slot will accept, because each start is the vendor’s own timestamp.

book_appointment is deliberately small. Input is a start string and a phone. Output is a booking uid or an error. There is no path that returns success without a Cal.com booking.

send_bill_upload_at_step_6b is the Step 6 implementation. It will not run from the prompt’s good behaviour alone. The route still checks the lead. That is why a prompt mistake does not text a person who opted out.

Post-call services are separate from Emma so a dropped webhook can be reasoned about without replaying the conversation. Voicemail detection reads the tool name out of the transcript. It does not ask the model whether it thinks it reached voicemail.

4.3 Test cases

Tool tests were run against the HTTP routes without a handset. Call tests used a consented number and the real agent. The printed report should include colour figures of the solar form, a slot-tool JSON response, a Zoho lead after booking, and the upload SMS. Under each figure, state what was submitted and what came back.

Test 01. Dial payload

Input: a lead with first name, address, and E.164 phone, voice agent enabled.
System output: one outbound-call request whose dynamic variables include that name, that address, that phone, and sched_day_1_speech equal to “tomorrow” or the next weekday when tomorrow is Sunday. call_recording_enabled is false.
Result: pass.

Test 02. Bill under the threshold

Input: a conversation in which the customer says the summer bill was about $90.
System output: Emma ends the call. get_available_slots is not required. No booking.
Result: pass if the transcript ends on the disqualification line and book_slot was not called.

Test 03. Two slots only

Input: day_query tomorrow, time_period morning, on a day Cal.com has several morning openings.
System output: has_slots true, slots length at most 2, spoken_offer containing the weekday and both local times, each slot.start an ISO string.
Result: pass.

Test 04. Sunday skip

Input: a Saturday dial.
System output: sched_day_1_speech is Monday, not Sunday and not “tomorrow” if tomorrow is Sunday.
Result: pass.

Test 05. Booking uses the database, not the model’s name

Input: book_slot with a valid start, the lead’s phone, and a nonsense attendee name.
System output: Cal.com booking created for the lead’s stored name and address. Response status success and a uid. The lead row stores that uid and the start.
Result: pass.

Test 06. Spoken confirmation after success only

Input: a full call that reaches a chosen slot, then a forced tool error, then a retry that succeeds.
System output: the transcript does not contain “you’re booked” before the successful tool result. After success, Emma confirms the address and calls mark_bill_sms_ready.
Result: pass on the retry rule. A test that books on the first try is the same assertion with no error in between.

Test 07. Bill SMS consent

Input: mark_bill_sms_ready for a phone whose sms_eligible is false.
System output: no Twilio send.
Input: the same tool after a successful booking with consent yes.
System output: one upload SMS.
Result: pass for both.

Test 08. Voicemail

Input: a post-call payload whose transcript includes the voicemail_detection tool.
System output: answered is false, a callback may be scheduled, the solar email may include the self-serve link.
Result: pass.

Test 09. Booked call email

Input: a post-call payload for a conversation that stored a booking uid.
System output: the report email does not add a second “book a time” link.
Result: pass.

Test 10. Window exhausted

Input: three days with has_any_slots false.
System output: Emma uses the handoff sentence and does not offer a fourth day. book_slot is not called.
Result: pass against the prompt. The tool’s next-day fields stop after the window.

Test 11. STOP during later nurture

Input: inbound SMS “STOP” after an unbooked call has started stage two.
System output: opt-out stored, no further nurture texts.
Result: pass. This is not part of Emma’s live call, but it bounds every SMS she caused.

Test 12. Sale write-back

Input: revenue and profit on a lead that has zoho_lead_id.
System output: those fields and a note on the Lumi Solar lead.
Result: pass. Staff do this. Emma does not.

Chapter 5 Conclusion

The project’s claim is narrow and testable. A Lumi Energy lead can be called by Emma, qualified on a summer bill, and booked for a visit at the house, and the time she speaks is a time Cal.com returned. The website, the sheet, Zoho, and the welcome text exist so that call has a person to ring and a record to update. The tools exist so the call cannot promote a guess into a booking.

What became obvious in the build is that the prompt and the tools drift apart unless they share field names. spoken_offer, start, phone_no, and sched_day_1_speech are in both places on purpose. The moment the model is allowed to format the clock, or to compose a start timestamp, the visit on the calendar and the visit in the sentence diverge. Putting the sentence on the server was the change that made the script honest.

The limits are also narrow. Emma will not answer a technical design question. She writes it down. She will not quote a price. She will not book a Sunday or a fourth day. She cannot help a wrong phone number. Call recording is off, so quality review uses the transcript and the tool trace, not audio. Callback spacing is configuration, not a claim that every miss is recovered. The system does not design the array and does not take payment.

The work I would do next is more calls under the same tools, not more freedom in the prompt. A change to the $120 line or to the two-slot rule should be a tested change in both the prompt and the SRS. The result that matters is the ordinary booked lead: a Zoho record, a Cal.com uid, a confirmed address, and a bill link text that went out only because the booking tool had already succeeded.

References

Books

[1] K. E. Wiegers and J. Beatty, Software Requirements (3rd Edition), Microsoft Press, 2013.

[2] M. Fowler, Patterns of Enterprise Application Architecture (1st Edition), Addison-Wesley, 2002.

Research papers

[3] E. Adamopoulou and L. Moussiades, “Chatbots: History, technology, and applications,” Machine Learning with Applications, Vol. 2, Article 100006, December 2020.

[4] D. Jurafsky and J. H. Martin, “Dialogue Systems and Chatbots,” in Speech and Language Processing, 3rd ed. draft, Chapter 15, 2024.

Websites and product documents

[5] ElevenLabs, Conversational AI, https://elevenlabs.io/docs

[6] Twilio, Programmable Voice, https://www.twilio.com/docs/voice

[7] Twilio, Programmable Messaging, https://www.twilio.com/docs/messaging

[8] Cal.com, API reference v2, https://cal.com/docs/api-reference/v2

[9] Zoho Corporation, Zoho CRM API v8, https://www.zoho.com/crm/developer/docs/api/v8/

[10] Google Cloud, Cloud Run, https://cloud.google.com/run/docs

[11] Google Cloud, Cloud Tasks, https://cloud.google.com/tasks/docs

[12] Supabase, Database and Storage, https://supabase.com/docs

[13] S. Ramírez, FastAPI, https://fastapi.tiangolo.com

[14] Vercel, Next.js documentation, https://nextjs.org/docs

[15] Federal Communications Commission, Telephone Consumer Protection Act, 47 U.S.C. § 227, https://www.fcc.gov/sites/default/files/tcpa-rules.pdf

[16] Institute of Engineering & Technology, DAVV, https://ietdavv.edu.in

Appendix

A. Abbreviations

| Short form | Meaning |
| --- | --- |
| API | Application programming interface |
| CRM | Customer relationship management |
| E.164 | International telephone numbering format |
| ISO | The timestamp form used as a slot’s start value |
| SMS | Short message service |
| SRS | Software requirements specification |

B. Emma’s tools (operator card)

| Tool | Method and path | She sends | She must do with the result |
| --- | --- | --- | --- |
| get_available_slots | GET /scheduling/slots | day_query, time_period, optional time_preference | Read spoken_offer. Offer those two times only. |
| book_slot | POST /scheduling/book | start from that slot, phone_no | Say booked only if status is success. |
| mark_bill_sms_ready | POST /webhooks/lumi/mark-bill-sms-ready | phone_no | Call only after book_slot succeeded. |
| voicemail_detection | ElevenLabs system tool | none from our API | Post-call treats it as not answered. |

Header on the three project tools: X-Tool-Api-Key.

C. Demonstration order

1. Submit a solar form with SMS consent yes. Show the sheet row and the Zoho lead.
2. Show the outbound call and the variables on a test number you control.
3. On the call, give a summer bill above $120, pick a period, and accept one of the two offered times.
4. Show the Cal.com booking and the upload SMS.
5. Show a second test that says the bill is under $120 and confirm that no booking was created.
6. If a voicemail test is available, show that a callback was scheduled rather than a qualification.

D. Left out of the printed text

API keys, the tool key, OAuth tokens, and real customer numbers are not printed. Screenshots for the viva should use a test lead or should hide personal data.
