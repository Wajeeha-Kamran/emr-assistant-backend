# Module 9.2 — Postman Collection Runbook

Collection: `docs/postman_collection.json` — 19 requests covering the full
consultation workflow end to end, in the order a doctor would actually perform it.

All 19 URLs were checked against the application's registered routes before this
runbook was written. The collection stores the JWT, session id, note id, section id
and suggestion id automatically, so requests chain without manual copying.

---

## Before you start

Two services must be running, in two separate terminals, from the repository root.

**Terminal 1 — the API**

```
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```

**Terminal 2 — the simulated EMR**

```
.\.venv\Scripts\python.exe -m uvicorn simulated_emr_service.main:app --port 8001
```

The second one matters: signing a note triggers a background sync to the simulated
EMR, so TC-09 and TC-10 cannot pass without it. `SIMULATED_EMR_URL` in `.env`
must point at port 8001.

Note that this run uses the development database (`emr_assistant`), not the test
database. Records created here persist, which is what makes the screenshots
evidence rather than a transient.

---

## The run

Import `docs/postman_collection.json` into Postman, then send each request in
order. Only request 5 needs input from you.

| # | Request | What to expect | Covers |
|---|---|---|---|
| 0 | Health Check | `200`, `{"status":"ok"}`. If this fails the API is not running. | — |
| 1 | Register Doctor | `201`, or `400` if already registered from a previous run — either is fine. | — |
| 2 | Login | `200`, stores the JWT automatically. | — |
| 3 | Create Session | `201`, stores the session id. | — |
| 4 | Start Recording | `200`, status `RECORDING`. | TC-01 |
| 5 | Stop Recording — Upload Audio | `200`, status `STOPPED`. **Attach the audio here** (see below). | TC-02 |
| 6 | Get Transcript | Poll. `processing` at first; re-send every 30s until `completed`. | TC-06 |
| 7 | Retry Transcription | **Optional.** This is the alternate flow. After a successful transcription it may return an error — that is correct behaviour. | UC-06 alt |
| 8 | Generate SOAP Note | `201`, stores the note id. | TC-07 |
| 9 | Get SOAP Note | `200`, four sections. | TC-07 |
| 10 | Edit SOAP Section | `200`, edited content saved. | TC-03 |
| 11 | Generate Code Suggestions | `200`, 10 suggestions (5 ICD-10, 5 CPT). | TC-08 |
| 12 | Get Code Suggestions | `200`, ranked 1–10 with no gaps. | TC-08 |
| 13 | Accept a Suggestion | `200`, `accepted: true`. | UC-08 |
| 14 | Sign SOAP Note | `201`. The note is now immutable. | TC-04 |
| 15 | Get Sync Status | `200`. Sync runs in the background — re-send if still pending. | TC-09 / TC-10 |
| 16 | Trigger Retention Sweep | `200`. Development endpoint. | TC-05 |
| 17 | Current Doctor | `200`, the logged-in doctor. | — |
| 18 | Simulated EMR docs | `200`, confirms the EMR service is reachable. | — |

### Request 5 — attaching the audio

Open the **Body** tab, find the `file` row, click **Select Files**, and choose:

```
docs\evidence\human_distinct\consult_1.wav
```

This is the female-doctor / male-patient recording that scored 100% speaker
accuracy. Using it means the resulting SOAP note has a properly populated
Subjective section, drawn from real PATIENT speech, rather than the
"Not documented in dialogue." fallback that appears when diarization fails.

Transcription takes a minute or two on CPU. That is expected and is documented in
`docs/module_8_3_performance.md`.

---

## What to capture

Five responses are worth screenshotting for the report, because between them they
evidence five STD test cases against a live system:

| Screenshot | Evidences |
|---|---|
| Request 6 — diarized transcript with DOCTOR/PATIENT labels | TC-06 |
| Request 9 — the four-section SOAP note | TC-07 |
| Request 12 — ranked ICD-10 and CPT suggestions | TC-08 |
| Request 14 — signature created | TC-04 |
| Request 15 — sync status showing success | TC-09 |

---

## If something fails

- **Request 0 fails** — the API is not running, or something else is using port 8000.
- **Request 1 returns 400** — the doctor already exists from a previous run. Continue;
  request 2 will still log in. To start clean, change the `email` collection variable.
- **Request 6 stays `processing`** — transcription is still running. Give it longer
  before assuming failure; a 95-second recording takes a minute or two on CPU.
- **Request 6 returns `failed`** — check Terminal 1 for the traceback. This is the
  real error, not a Postman problem.
- **Request 15 shows a sync failure** — check Terminal 2 is running and that
  `SIMULATED_EMR_URL` in `.env` points at port 8001.

Record the outcome of the run here or in PROGRESS.md when complete. An unrun
collection is not evidence of anything.

---

## Run outcome — 15 August 2026

All 19 requests executed against a live server. Audio:
`docs/evidence/human_distinct/consult_1.wav`. Every request returned as expected
after the three defects below were fixed.

The manual run found three defects that 107 passing automated tests did not, and
could not: each one lives in the gap between what a test constructs and what a
real client sends.

### 1. WAV uploads rejected from Windows clients

`POST /sessions/{id}/stop-recording` returned
`400 Unsupported file type: audio/wave`.

`ALLOWED_CONTENT_TYPES` accepted `audio/wav` and `audio/x-wav` but not
`audio/wave`, which is what Windows reports for the same file. WAV has never had
one agreed MIME type. The automated tests construct the upload in Python and set
the header themselves, so they never exercised a real client's content-type
negotiation — and a .NET MAUI client on Windows would have hit exactly this.

Fixed in `app/services/audio_manager.py`: all five WAV spellings now accepted,
along with the other formats' variants.

### 2. Transcript segments returned in arbitrary order

`GET /sessions/{id}/transcript` returned the segment starting at 38.12s ahead of
the one starting at 0.64s.

The `Transcript.segments` relationship had no `order_by`, so PostgreSQL returned
rows in storage order, which is neither insertion order nor stable. A client
rendering the list shows the consultation out of sequence.

SOAP generation was unaffected — `soap_note_service.py` applies its own
`.order_by(TranscriptSegment.start_time)`. Fixed at the relationship in
`app/models/transcript.py` so every consumer inherits the ordering.

### 3. Stale completion timestamp after a retry

After `POST .../transcript/retry`, the transcript returned status `processing`
while still carrying `finalized_at` from the previous attempt. A client would
show a completion time next to a spinner.

Fixed in `app/api/v1/endpoints/transcripts.py`: the retry path clears
`finalized_at` when it resets the status.

---

## Finding recorded for Module 3, not fixed here

The SOAP note generated on this run has a correctly populated **Subjective**
section — the direct result of the Module 9.1 Part B diarization work, since that
section is built from PATIENT speech and was previously always empty. But the
classification of doctor speech into Objective / Assessment / Plan is poor:

- **Plan** contained `"Good morning. Please take a seat. What brings you in today?"`
- **Assessment** was empty, although the doctor said *"This looks like migraine with aura"*
- **Objective** contained the examination findings, the diagnosis and the entire
  treatment plan together

The cause is granularity. Classification runs once per Whisper segment, and one
segment here was a 30-second block containing examination, diagnosis and plan in
sequence. A single segment can only be assigned to one section, so all of it
landed in Objective. Conversely, short segments such as a greeting carry almost no
clinical signal and are assigned close to arbitrarily.

The fix is to split each doctor segment into sentences and classify per sentence,
so that "Your blood pressure is 140 over 90" reaches Objective, "This looks like
migraine with aura" reaches Assessment, and "I am going to prescribe..." reaches
Plan. That is a change to `app/services/soap_service.py` and belongs to Module 3.
It needs measuring after the change, not just changing, so it was deliberately not
attempted during this run.
