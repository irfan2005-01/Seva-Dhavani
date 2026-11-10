# Seva Dhwani (ಸೇವಾ ಧ್ವನಿ)

Accessible, voice-based grievance and hospital service monitoring prototype for Karnataka government hospitals. This foundation covers non-emergency service complaints only. It does not collect patient names or medical details; a complainant phone number is optional and reserved for SMS updates.

## Project structure

```text
backend/
  app/
    main.py
    models.py
    database.py
    config.py
    seed.py
    routers/
    services/sarvam.py
    categorizer.py
  requirements.txt
  .env.example
frontend/
```

## Run locally

Python 3.10+ is recommended.

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload
```

The API is available at `http://127.0.0.1:8000`; API docs are at `/docs`. The `/health` endpoint checks the database connection. On startup, SQLAlchemy creates `backend/seva_dhwani.db` and the three demo hospitals and their authorities are seeded. Seeding is safe to repeat. To seed explicitly without launching the server, run `python -m app.seed` from `backend`.

## Categories and service targets

Categories, default authority roles, and SLA hours are in `backend/app/config.py` and can be adjusted for the pilot. Current targets range from 24 to 48 hours.

## Privacy and scope

Do not enter patient names, diagnoses, treatment details, or other medical information in complaint descriptions. The prototype is for service issues only. Emergency wording is redirected to hospital staff or 108, and voice audio is processed in memory and never saved as a file.

## Complaint API

Set distinct `OFFICER_API_KEY` and `ADMIN_API_KEY` values in `backend/.env`. Officer endpoints require `X-API-Key`; only the admin key may close a complaint. Run the tests from `backend` with `pytest -q`.

```sh
# Register (emergency submissions receive a redirect message and are flagged)
curl -X POST http://127.0.0.1:8000/api/complaints -H 'Content-Type: application/json' -d '{"description":"Medicine unavailable at pharmacy","language":"en","hospital_id":1,"channel":"assisted"}'

# Public status lookup
curl http://127.0.0.1:8000/api/complaints/SD-2026-00001

# Officer queue with filters and pagination
curl 'http://127.0.0.1:8000/api/complaints?hospital_id=1&status=Assigned&overdue=true&page=1&page_size=20' -H 'X-API-Key: replace-with-a-long-random-officer-key'

# Officer status update
curl -X PATCH http://127.0.0.1:8000/api/complaints/SD-2026-00001 -H 'Content-Type: application/json' -H 'X-API-Key: replace-with-a-long-random-officer-key' -d '{"status":"In Progress","action_note":"Issue is being reviewed."}'

# Officer action history
curl http://127.0.0.1:8000/api/complaints/SD-2026-00001/history -H 'X-API-Key: replace-with-a-long-random-officer-key'
```

## Voice flow

The same Uvicorn command serves the mobile page at `http://127.0.0.1:8000/`. Copy `backend/.env.example` to `backend/.env` and set `SARVAM_API_KEY` for Sarvam speech services. Saaras v4 accepts browser WebM/OGG uploads directly, so the server does not transcode or retain audio. If the key is absent or Sarvam fails, the page falls back to browser speech recognition and speech synthesis when the browser provides them. Microphone access requires `localhost` or HTTPS.

After installing dependencies, run the API and Sarvam mock tests from `backend`:

```powershell
python -m pytest -q
```

## Hospital administration dashboard

Open `http://127.0.0.1:8000/dashboard` after starting FastAPI. The page is a
single local HTML file with inline CSS/JavaScript and no CDN dependencies. Enter
an officer API key to load the dashboard; enter an admin key as well to enable
complaint closing. Seed the hospitals and 30 synthetic service complaints with
`cd backend; python -m app.seed --demo-data`. The generated demo records contain
no complainant names or phone numbers. Run tests from `backend` with
`python -m pytest -q tests`.

## No-smartphone channel demos

- **Voice:** open `/` and use the existing voice complaint form.
- **Assisted:** open `/assisted`, enter a service issue, choose a hospital, add a fake operator code (required), and optionally use a fake citizen number. Submit and confirm the operator reference appears in the complaint action history.
- **Feature-phone IVR:** open `/ivr`, press **Call / Start**, then keypad `1`, choose a language (`1` Kannada, `2` English, `3` Hindi), choose the hospital number, record or type a service issue, and press `1` to confirm. It reads the complaint ID digit by digit; press `1` to queue an SMS and enter a 10-digit demo number, or `2` to finish. Open `/sms` and enter that same number to view the simulated inbox. For status, start a new call, press `2`, choose a language, key in the nine digits from an ID such as `SD-2026-00001`, then press `#`. Press `9` at the main menu to hear the emergency instruction; no routine complaint is created.
- **Missed call:** on `/ivr`, submit a fake number in the missed-call panel. Open `/dashboard` with an officer key, then mark the masked callback request as called back.

All IVR speech inputs use `/api/voice/transcribe` when available and can be typed in the simulator. `/api/ivr/session` and `/api/ivr/session/{id}/input` own the state machine; the simulator only sends keypad/text events. SMS and callback features are simulations: no call or SMS is sent to a real phone.

## Follow-up and escalation demo

The follow-up engine runs every `FOLLOWUP_INTERVAL_SECONDS` (default 60). Tune
`REMINDER_BEFORE_DUE_HOURS`, `ESCALATE_AFTER_OVERDUE_HOURS`,
`ESCALATION_REPEAT_HOURS`, and `STALE_AFTER_HOURS` in `backend/.env`. The default
notification provider writes SMS (when a number exists) and in-app entries to
the SQLite outbox and logs them; it does not contact an SMS gateway.

For a judge demo, set `DEMO_MODE=true` in `backend/.env`, then start the server
as above. In a second PowerShell window run:

```powershell
cd backend
.\demo_followups.ps1
```

The script registers three complaints, backdates them to show a due-soon
reminder, an overdue reminder, and escalation, then prints `/api/followups` and
`/api/notifications`. It reads the officer API key from `.env` without printing
it. The requested one-off job endpoint is `POST /api/followups/run`; both it and
the follow-up queue and outbox require an officer API key.

Manual check: open `http://127.0.0.1:8000/`, allow microphone access, record a short Kannada service complaint, edit the recognized text, select a hospital, and submit. Confirm the displayed complaint ID is spoken, then use the status box to look it up. To check emergency handling, submit a phrase such as “accident” and confirm the red 108 notice appears without a routine complaint ID.

## Final demo run steps

From the project root in PowerShell, run `.\run.ps1`. It checks Python and installed dependencies, creates `backend/.env` from the example when needed, prints value-free preflight OK/WARN lines, and starts the API on port 8000 (or the next free port through 8010 if 8000 is busy). Set distinct `OFFICER_API_KEY` and `ADMIN_API_KEY` plus `DEMO_MODE=true` in `backend/.env` before the pitch. `SARVAM_API_KEY` is optional; typed entry and browser speech are available without it.

To reload curated fake data, from `backend` run `python -m app.seed --reset-demo` and type `yes`, or run `python -m app.seed --reset-demo --yes`. Tests: `C:\Users\ahmed\AppData\Local\Programs\Python\Python312\python.exe -m pytest -q tests` from `backend`.

See [DEMO.md](DEMO.md) for the five-minute pitch and [FEASIBILITY.md](FEASIBILITY.md) for the pilot plan. The SMS inbox and backdate control are demo-only. IVR, missed-call callbacks, and SMS delivery are simulated; the prototype does not place real calls or send real SMS.

## Pages

- `/` citizen voice/typed complaint and status check
- `/assisted` helpdesk / ASHA assisted registration
- `/ivr` feature-phone IVR simulator and missed-call simulation
- `/dashboard` officer queue, follow-ups, outbox, and demo controls
- `/sms` local demo phone inbox (only with `DEMO_MODE=true`)
- `/docs` Swagger UI; `/health` database health

## API endpoints

- `GET /api/hospitals`
- `POST /api/complaints`, `GET /api/complaints`, `GET /api/complaints/{complaint_id}`, `PATCH /api/complaints/{complaint_id}`, `GET /api/complaints/{complaint_id}/history`
- `POST /api/complaints/assisted`; officer detail at `GET /api/complaints/{complaint_id}/officer-detail`
- `POST /api/voice/transcribe`, `POST /api/voice/speak`
- `GET /api/stats`, `GET /api/followups`, `POST /api/followups/run`, `GET /api/notifications`
- `POST /api/demo/backdate/{complaint_id}` (demo mode only)
- `POST /api/ivr/session`, `POST /api/ivr/session/{id}/input`, `POST /api/ivr/missed-call`
- `POST /api/sms/inbox` (demo mode only), `GET /api/callbacks`, `PATCH /api/callbacks/{id}`, `GET /api/demo/status`
- Compatibility aliases also remain at `/api/complaints/followups`, `/api/complaints/notifications`, `/api/complaints/followups/run`, and `/api/complaints/demo/backdate/{complaint_id}`.
