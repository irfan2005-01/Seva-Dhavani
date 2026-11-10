# Seva Dhwani: five-minute live demo

## Before the room

Run `python -m app.seed --reset-demo --yes` from `backend` to load 25 synthetic complaints, then start the app with `..\run.ps1`. Confirm the dashboard keys and `DEMO_MODE=true` in `backend/.env`. Keep `/`, `/dashboard`, `/ivr`, and `/assisted` open in tabs. Use a demo phone such as `9876543210`; messages are queued locally and no SMS is sent.

## Timed script

| Time | What to click and say | If it fails |
|---|---|---|
| 0:00–0:25 | Open `/`. Point out the DEMO MODE and Offline/typed mode labels and the non-emergency notice. | If the banner is absent, verify `DEMO_MODE=true`; continue with the typed complaint form. |
| 0:25–1:10 | Click Voice complaint, select a hospital, record in Kannada: “ನಮ್ಮ ಆಸ್ಪತ್ರೆಯಲ್ಲಿ ಕುಡಿಯುವ ನೀರು ಇಲ್ಲ.” Review/correct the transcript, add `9876543210`, submit. Show the ID and SMS acknowledgement. | If the mic or Sarvam is unavailable, type “Drinking water is unavailable at the hospital”; the same categorisation and registration work. If TTS fails, show the ID on screen and use Listen/browser speech. |
| 1:10–1:40 | Open `/sms`, enter the same phone, show the queued SMS. | If there is no SMS row, confirm a phone number was supplied during registration; otherwise show the authority reminder in the dashboard outbox. |
| 1:40–2:05 | Open `/dashboard`, enter officer key. Find the new complaint and show category, assigned role, age, and attention panel. | If the key is rejected, check `OFFICER_API_KEY` in backend/.env; show the read-only citizen status page while correcting it. |
| 2:05–2:30 | Open the row. Add an action note, set In Progress, then Resolved. Explain the officer action trail. | If a request errors, refresh and use an existing In Progress demo row; status changes require the configured officer key and a note to resolve. |
| 2:30–3:05 | Select the fresh `[DEMO]` complaint and backdate it by 55 hours. Click “Run follow-up job now”. Show overdue badge, reminder in notifications, and the escalation to Medical Superintendent. A pre-seeded complaint shows the next hop to DHO. | If controls are hidden, confirm DEMO_MODE=true and reconnect as officer; use a pre-seeded overdue/escalated complaint in the attention panel. |
| 3:05–3:35 | Point to the recurring drinking-water issue alert for four complaints at one hospital in seven days. | If filters hide the cluster, clear table filters; stats and recurring alert use their own data request. |
| 3:35–4:20 | Open `/ivr`, press Call, choose register, Kannada, hospital, then record or type a non-emergency issue and confirm. Explain that this keypad simulator models the feature-phone flow. Then show `/assisted` and its registered-by field. | If mic/audio fails, type into the IVR speech box or assisted description; captions and keypad state machine remain usable. |
| 4:20–5:00 | In IVR press 9 (or submit “ಅಪಘಾತ” in a complaint) and show the Kannada/English instruction to contact staff or call 108; confirm no routine complaint is created. Close with the outbox and escalation chain. | If speech output is unavailable, read the on-screen emergency notice; do not submit an emergency as a normal grievance. |

## Likely judge questions

- **What data is stored?** Service complaint text and workflow metadata only. No patient names or medical details are requested. Phone is optional, masked in officer callback lists, and used for message delivery/inbox matching.
- **How are emergencies handled?** Keyword/LLM emergency checks block routine registration and direct the person to hospital staff or 108. This is not an emergency-response service.
- **How accurate is Kannada?** Sarvam transcription is optional; users review and edit text. Kannada keyword coverage is a prototype and needs validation with local speakers before a pilot.
- **Cost per complaint?** It depends on audio duration, provider pricing, SMS count, and hosting. Measure these in a controlled pilot; this prototype makes no fixed price claim.
- **Can real telephony/SMS be connected?** Yes, the IVR and notification provider interfaces are intended extension points. The current IVR, callback, and SMS inbox are simulations; no real calls/SMS are placed.
- **Will it scale?** SQLite is for this single-host demo. A pilot should move to managed PostgreSQL, background workers, monitoring, backups, and load testing before wider rollout.
- **Who updates status?** Authorized hospital officers update status in the dashboard; an admin key is required to close a complaint.
- **How does a complaint reach the right authority?** Category rules select the hospital's mapped role and SLA, then the follow-up engine reminds and escalates through the configured authority chain.

