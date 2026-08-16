# Frontend integration guide

For the .NET MAUI client. Written from the API as it actually behaves, not from
how it might be assumed to behave.

Contract: `docs/openapi.json`. Live documentation: `http://127.0.0.1:8000/docs`.

---

## 1. Reaching the backend

Start it with `.\run_backend.ps1` from the repository root. It binds `0.0.0.0`,
which is what makes it reachable from anything other than the laptop itself.

**The base URL is different on every target.** This is the single most common
cause of "the app cannot reach the API", and it is not an error in your code.

| Running on | Base URL | Why |
|---|---|---|
| Windows (MAUI desktop) | `http://127.0.0.1:8000` | Same machine |
| Android emulator | `http://10.0.2.2:8000` | `10.0.2.2` is the emulator's alias for the host machine. `127.0.0.1` means the emulator itself. |
| Physical Android phone | `http://<laptop-LAN-IP>:8000` | e.g. `http://192.168.1.14:8000`. Both devices must be on the same WiFi. |
| iOS simulator | `http://127.0.0.1:8000` | Shares the host network |

`run_backend.ps1` prints the emulator and LAN addresses when it starts, so they do
not have to be looked up each time.

Select it at compile time rather than hardcoding one and editing it constantly:

```csharp
public static class ApiConfig
{
#if ANDROID
    // 10.0.2.2 is the Android emulator's route to the host. For a physical
    // device, replace with the laptop's LAN address printed by run_backend.ps1.
    public const string BaseUrl = "http://10.0.2.2:8000";
#else
    public const string BaseUrl = "http://127.0.0.1:8000";
#endif
}
```

### Two Android-only obstacles

**Cleartext HTTP is blocked by default.** Android refuses plain `http://` traffic
unless told otherwise, and the failure is not obvious from the error. For
development, set `android:usesCleartextTraffic="true"` in
`Platforms/Android/AndroidManifest.xml`. Remove it before any real deployment —
production must be HTTPS.

**A physical device needs the firewall opened.** Run PowerShell as Administrator:

```
New-NetFirewallRule -DisplayName "EMR Assistant API (dev)" -Direction Inbound `
  -LocalPort 8000 -Protocol TCP -Action Allow -Profile Private
```

Private profile only. Never allow this on a public network — it would expose the
API to everyone sharing that WiFi. The emulator does not need this rule.

---

## 2. Authentication

`POST /api/v1/auth/login` uses form encoding, not JSON — it follows the OAuth2
password flow. The `username` field takes the doctor's **email address**.

```csharp
var form = new FormUrlEncodedContent(new[]
{
    new KeyValuePair<string, string>("username", email),
    new KeyValuePair<string, string>("password", password),
});
var response = await http.PostAsync("/api/v1/auth/login", form);
```

Send the returned token on every other request:

```
Authorization: Bearer <token>
```

Store it in `SecureStorage`, not `Preferences`. `Preferences` is plain text on
disk; this token grants access to clinical records.

The token expires. When any call returns **401**, send the user back to the login
screen rather than retrying — a retry with an expired token fails identically.

---

## 3. The workflow, and where it will surprise you

The order is enforced by the session's state machine. Calling out of order returns
a 4xx, so the UI should follow it rather than working around it.

```
register / login
  -> POST /sessions/                              create
  -> POST /sessions/{id}/start-recording          status becomes RECORDING
  -> POST /sessions/{id}/stop-recording           upload audio (multipart)
  -> GET  /sessions/{id}/transcript               POLL until completed
  -> POST /sessions/{id}/soap-notes/generate      draft the note
  -> PATCH /soap-notes/{id}/sections/{sid}        doctor edits
  -> POST /soap-notes/{id}/code-suggestions/generate
  -> POST /soap-notes/{id}/sign                   irreversible
  -> GET  /soap-notes/{id}/sync-status            confirm the EMR push
```

### Transcription is asynchronous — this shapes the interface

`stop-recording` returns as soon as the audio is stored. **Transcription then runs
in the background and takes roughly as long as the recording itself on CPU.** A
90-second consultation takes about 90 seconds.

The client must poll `GET /sessions/{id}/transcript` and read `status`:

| status | Meaning | UI |
|---|---|---|
| `processing` | Still running | Progress indicator; poll again in ~3s |
| `completed` | Segments are ready | Show the transcript |
| `failed` | Something went wrong | Show an error and offer retry |

Poll every 2-3 seconds, not every 200ms. Give the user something honest to look at
— "Transcribing, this takes about as long as the recording" is better than a
spinner that looks stuck.

Do not design a screen that blocks until the transcript arrives. The waiting state
is a real part of this application, not an edge case.

### Uploading the audio

`stop-recording` takes multipart form data with the field name `file`. WAV, MP3,
M4A, OGG and WebM are accepted, including every MIME spelling of WAV that clients
send in practice — Windows reports `audio/wave` where browsers send `audio/wav`,
and both work.

```csharp
using var content = new MultipartFormDataContent();
using var stream = File.OpenRead(path);
var fileContent = new StreamContent(stream);
fileContent.Headers.ContentType = new MediaTypeHeaderValue("audio/wav");
content.Add(fileContent, "file", "consultation.wav");
var response = await http.PostAsync($"/api/v1/sessions/{id}/stop-recording", content);
```

Set a long timeout on the `HttpClient` — the default is 100 seconds, which the ASR
polling will not hit but a large upload on a slow connection might.

---

## 4. Error codes, and what the UI should do

| Code | Meaning | What to show |
|---|---|---|
| 400 | Bad input — wrong file type, mismatched IDs | The `detail` message; it is written to be readable |
| 401 | Missing or expired token | Return to login |
| 404 | Not found, **or belongs to another doctor** | "Not found". The API deliberately does not confirm that another doctor's resource exists. |
| 409 | Wrong state — already recording, already signed, transcript not ready | Explain the state, do not retry |
| 422 | Validation failure — e.g. empty section content | Highlight the field |
| 503 | NLP engine timeout | Offer retry; the `Retry-After` header suggests when |

**404 does not always mean "missing".** Requesting another doctor's session
returns 404 rather than 403, so the API does not leak the existence of other
people's records. Do not write "this record was deleted" — write "not found".

---

## 5. Suggested build order

Build each screen against the running API from the start. Do not build the UI
first and integrate later — the asynchronous transcription step changes the shape
of the screens, and discovering that after the layouts are finished means
rebuilding them.

1. **Login** — proves connectivity, auth and secure token storage. If this works,
   the hard part of integration is done.
2. **Session list / new session** — create a session, show its status.
3. **Record** — start recording, capture audio, upload. Use a file picker first;
   add real microphone capture once the upload path works.
4. **Transcript** — the polling screen. Build the waiting state properly here.
5. **SOAP note** — display four sections; make them editable. This is the screen
   the whole product exists for, so give it the most attention.
6. **Codes** — ranked list with accept toggles.
7. **Sign** — a confirmation dialog, because it is irreversible, then show sync
   status.

Screen 1 is the milestone that matters today. Everything after it is the same
pattern repeated.

---

## 6. What the app must never imply

The SOAP note is a **draft for clinical review**. The doctor edits it and signs
it; signing is what makes it a record. The interface should make editing feel
expected rather than exceptional, and the signing step should require deliberate
confirmation.

Two measured limitations are worth designing around:

- **Speaker labels can be wrong.** Diarization meets its accuracy target when the
  two voices are distinguishable and the pace is conversational, and degrades
  otherwise. Let the doctor correct a speaker label rather than presenting it as
  fact.
- **Section placement can be wrong.** Classification is measured at 97.4%, which
  means roughly one sentence in forty lands in the wrong section. Editing must be
  easy.

Neither is a reason to hide the feature. Both are reasons to make correction
cheap.

---

## 7. Recovering consultations that did not finish

Added 16 Aug 2026, for the dashboard.

A consultation runs **record -> transcribe -> generate note -> sign -> sync**.
Every stage can be interrupted, and none of them recovers on its own. Until
now nothing in the API enumerated a doctor's consultations, so an interrupted
one was unreachable from the client.

This matters beyond convenience. The retention worker deletes consultation
audio only when its note is both `SIGNED` and `SUCCESS`. A consultation stuck
at any earlier stage keeps a recording of a patient's voice on disk
indefinitely. Finishing or discarding these is what stops recordings
accumulating.

### `GET /api/v1/attention`

Returns the current doctor's stuck consultations. Under normal use it returns
zero items — it is an exception list, not a work queue.

```json
{
  "items": [
    {
      "session_id": 58,
      "note_id": 41,
      "reason": "SYNC_FAILED",
      "action": "RETRY_SYNC",
      "created_at": "2026-08-16T09:14:22.108Z",
      "last_edited_at": null
    }
  ],
  "count": 1,
  "counts": {
    "TRANSCRIPT_FAILED": 0,
    "TRANSCRIPT_STALLED": 0,
    "NOTE_NOT_GENERATED": 0,
    "NOT_SIGNED": 0,
    "SYNC_FAILED": 1
  }
}
```

`counts` always contains every reason, zero-filled, so no client has to handle
a missing key.

| `reason` | What happened | `action` | Call |
|---|---|---|---|
| `TRANSCRIPT_FAILED` | Transcription errored or exceeded its time budget | `RESUME_TRANSCRIPTION` | `POST /api/v1/sessions/{session_id}/transcript/retry` |
| `TRANSCRIPT_STALLED` | Still `processing` past the point where the job could be running — the API process died mid-job | `RESUME_TRANSCRIPTION` | same as above |
| `NOTE_NOT_GENERATED` | Transcript ready, note never generated | `GENERATE_NOTE` | `POST /api/v1/sessions/{session_id}/soap-notes/generate` |
| `NOT_SIGNED` | Note drafted, never signed | `SIGN_NOTE` | open the note screen; `POST /api/v1/soap-notes/{note_id}/sign` |
| `SYNC_FAILED` | Signed, but the push to the EMR failed and nothing re-sends it | `RETRY_SYNC` | `POST /api/v1/soap-notes/{note_id}/retry-sync` |

`action` is included so the recovery path is decided in one place rather than
re-derived from `reason` in every client.

Signing never appears here. It is synchronous: a failure is returned to the
caller and nothing is written, so there is no stored "signing failed" state.

`note_id` is null for the two stages that happen before a note exists.
`session_id` is always present and is what the client navigates with — both the
transcript and the note are fetched by session.

**Two deliberate exclusions.**

Anything younger than `ATTENTION_GRACE_MINUTES` (default 30) is not reported,
so a note being written right now never appears in its own author's attention
list. A transcript still inside its ASR time budget is not reported either;
transcription is slower than real time and a running job is not a stuck one.

A session whose recording was started but never stopped is not reported. No
audio was stored and no transcript row was created, so there is nothing to
resume and nothing on disk to clean up.

### How `TRANSCRIPT_STALLED` is decided

`ASRService` gives itself `max(ASR_TIMEOUT_FLOOR_SECONDS, duration *
ASR_TIMEOUT_FACTOR)` and marks the transcript failed when that elapses. A
transcript still `processing` past that budget plus
`ATTENTION_STALL_BUFFER_SECONDS` was therefore not timed out by the service —
it was abandoned, which is what happens when the process dies mid-job.
Background tasks run inside the API process and nothing resumes them on
restart.

The same rule now bounds the concurrency guard on
`POST /api/v1/sessions/{session_id}/transcript/retry`. That guard used to
refuse any transcript in `processing`, which made a stalled one permanent —
the only recovery path rejected the only state that needed it. A genuinely
running pass is still refused.

### `POST /api/v1/soap-notes/{note_id}/retry-sync`

Re-queues a failed sync. Returns `{"sync_status": "PENDING"}` — the response
reports that the job was queued, not that it succeeded. Poll
`GET /api/v1/soap-notes/{note_id}/sync-status` for the outcome, exactly as the
sign screen already does.

| Status | Meaning |
|---|---|
| 200 | Queued. Poll for the result. |
| 409 | The note's sync status is not `FAILED`. A `PENDING` sync is refused deliberately: a job already in flight would be duplicated in the receiving EMR. |
| 404 | No such note, or it belongs to another doctor. |

Note that `EMRSyncClient` already makes three attempts with backoff **inside a
single job**. This endpoint is for the case where all three were exhausted and
the job ended.
