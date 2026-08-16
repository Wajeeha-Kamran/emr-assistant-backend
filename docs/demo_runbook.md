# Demonstration runbook

For showing the working system to a supervisor or examiner. Roughly five minutes,
with a fallback for the part that takes time.

Written down so it does not have to be improvised under pressure.

---

## Before they arrive (two minutes)

```
.\run_backend.ps1
```

Wait for "Backend is up". Confirm PostgreSQL is running if it complains.

Open these three tabs in advance:

| Tab | Address | For |
|---|---|---|
| API docs | http://127.0.0.1:8000/docs | The live demonstration |
| Simulated EMR | http://127.0.0.1:8001/docs | Showing the sync destination |
| Postman | the imported collection | Alternative to /docs if preferred |

**Run through the demo once yourself first.** Doing so leaves a completed session
in the database, which is the fallback described in step 4.

---

## The demonstration

### 1. Frame it before touching anything (30 seconds)

> A doctor records a consultation. The system transcribes it, works out who was
> speaking, drafts a SOAP note, suggests billing codes, and syncs it to the EMR
> once the doctor signs. Everything runs locally — no audio leaves the machine,
> and no real patient data is used anywhere in this project.

That last sentence matters. Say it early.

### 2. Start a consultation (1 minute)

In `/docs`, or with the Postman collection in order:

1. `POST /auth/register` then `POST /auth/login` — obtain a token
2. `POST /sessions/` — create the session
3. `POST /sessions/{id}/start-recording` — status becomes RECORDING
4. `POST /sessions/{id}/stop-recording` — attach **`docs/evidence/demo_clip.wav`**

Use the demo clip, not a full recording. It is 33 seconds and transcribes in
roughly 25; a full script takes about 90 seconds, which is a long silence.

### 3. Talk while it transcribes (25 seconds)

This is the honest moment. Do not pretend it is instant — explain why it is not:

> Whisper is running on the CPU. That is a measured constraint, not a bug — the
> requirements document specifies a GPU, and we measured the difference rather
> than assuming it. Concurrency was measured too: ten simultaneous sessions all
> completed successfully.

### 4. Show the transcript (1 minute)

`GET /sessions/{id}/transcript` — poll until `completed`.

Point at the alternating DOCTOR and PATIENT labels. This is the part with the
most engineering behind it, and worth one sentence:

> Speaker separation was rebuilt three times. The measured result is 100% on this
> recording, and we tested it under three different conditions to establish where
> it breaks.

**If transcription is still running**, switch to the session you prepared earlier
and show its completed transcript. Say that you are doing so — an examiner will
respect "here's an earlier run while that one finishes" far more than a stall.

### 5. The SOAP note (1 minute)

`POST /sessions/{id}/soap-notes/generate`, then `GET .../soap-notes`.

This is the deliverable. Point out:

- **Subjective** is built from what the patient said
- **Objective** holds the examination findings
- **Assessment** holds the diagnosis
- **Plan** holds the prescription and follow-up
- No greeting, no questions — only what belongs in a clinical note

> Classification is measured at 97.4% against hand-labelled ground truth, and
> checked against a held-out set of consultations the system was not developed
> against, to make sure the rules were not fitted to the test data.

### 6. Codes, signing and sync (1 minute)

1. `POST /soap-notes/{id}/code-suggestions/generate` — five ICD-10 and five CPT, ranked
2. `POST /soap-notes/{id}/sign` — the note becomes immutable
3. `GET /soap-notes/{id}/sync-status` — confirms it reached the EMR

Then try to edit the signed note and let it fail with 409:

> Signing is deliberately irreversible. A clinical record that can be altered
> after signature is not a record.

That failure is worth demonstrating on purpose. It shows the system enforces
something, rather than only doing what it is told.

---

## If asked for evidence rather than a demonstration

Three commands, about a minute each:

```
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m scripts.evaluate_soap
.\.venv\Scripts\python.exe -m scripts.evaluate_soap --heldout
```

The test run prints a traceability table mapping results to TC-01…TC-10 from the
STD. The other two print accuracy against hand-labelled ground truth.

For a supervisor, this is often more persuasive than the live demo: the numbers
are reproducible on the spot, and the held-out set answers the obvious question
about whether the system was tuned to its own tests.

---

## Questions worth having an answer ready for

**"Does it work with any two speakers?"**
Not equally. It meets the target when the voices are acoustically distinguishable
and the pace is conversational, and degrades when the voices are similar or
turn-taking is rapid. That was measured across three recording conditions rather
than assumed. Recommended future work is voice enrolment — the doctor is a
logged-in user, so their voice can be registered once, which turns "separate two
unknown voices" into the much easier "find the known voice".

**"What if the SOAP note is wrong?"**
It is a draft. The doctor reviews and edits every section before signing, and
that edit step is a first-class part of the API rather than an afterthought. The
system produces a starting point, not a record.

**"Is this using ChatGPT?"**
No. Whisper for speech, pyannote for speakers, ClinicalBERT for classification —
all running locally. The generation is extractive, meaning every word in the note
came from the transcript, so nothing can be invented. BioGPT was tested and
deliberately left off the critical path because it produced text unrelated to
what was actually said.

**"How do you know the accuracy figures are real?"**
Every one is produced by a script in `scripts/` that can be run in front of you,
against recordings and labels committed to the repository.
