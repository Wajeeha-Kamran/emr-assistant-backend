# AI-Powered EMR Assistant — Backend

Final-year project, Quaid-e-Azam University.
Wajeeha Kamran · Supervisor: Dr. Ayyaz Hussain

A doctor records a consultation. The system transcribes it, works out who was
speaking, drafts a SOAP note, suggests billing codes, and — once the doctor has
reviewed and signed it — syncs the note to an EMR and deletes the audio.

**The note is a draft for clinical review, not a record.** Everything the system
generates is intended to be corrected by a clinician before signing. That is the
design, not a disclaimer.

---

## Requirements

- Python 3.11+ (developed on 3.14)
- PostgreSQL 14+
- FFmpeg on PATH (Whisper uses it to decode audio)
- ~2 GB disk for the ML models, downloaded on first run

## Setup

```bash
python -m venv .venv
.\.venv\Scripts\activate            # Windows
pip install -r requirements.txt
```

Create two databases:

```sql
CREATE DATABASE emr_assistant;
CREATE DATABASE simulated_emr;
```

Copy `.env.example` to `.env` and fill it in:

| Variable | What it is |
|---|---|
| `APP_ENV` | `development` or `production`. Required — the app exits at startup if it is absent |
| `DATABASE_URL` | PostgreSQL URL for `emr_assistant` |
| `SIMULATED_EMR_DATABASE_URL` | PostgreSQL URL for `simulated_emr` |
| `SIMULATED_EMR_URL` | Where the simulated EMR service listens (default `http://localhost:8001`) |
| `JWT_SECRET` | JWT signing key |
| `ENCRYPTION_KEY` | Fernet key for encrypting clinical text at rest. Generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `HF_TOKEN` | Hugging Face read token, required for speaker diarization (see below) |
| `AUDIO_STORAGE_DIR` | Where uploaded recordings are written |

`.env` is gitignored and must never be committed.

**Speaker diarization needs three gated Hugging Face licences accepted**, not two.
Loading `speaker-diarization-3.1` under pyannote 4.x pulls checkpoints from
`community-1`, which is not mentioned in the error the other two produce:

- `pyannote/segmentation-3.0`
- `pyannote/speaker-diarization-3.1`
- `pyannote/speaker-diarization-community-1`

Then run the migrations and seed the reference codes:

```bash
alembic upgrade head
python -m scripts.seed_codes
```

## Running

Two services, two terminals:

```bash
python -m uvicorn app.main:app --port 8000                     # the API
python -m uvicorn simulated_emr_service.main:app --port 8001   # the simulated EMR
```

Interactive API documentation: <http://127.0.0.1:8000/docs>

The simulated EMR must be running for note syncing to succeed.

## Testing

```bash
python -m pytest -q
```

107 tests. They run against a **separate database** (`emr_assistant_test`),
created and seeded automatically on first run — the development database is never
touched, and a guard refuses to run against any database whose name does not end
in `_test`.

Every test is mapped to an STD test case, and the suite prints the traceability
table at the end of each run. Run one test case's tests with its marker:

```bash
python -m pytest -m tc06 -q      # diarization
python -m pytest -m tc04 -q      # signing and immutability
```

The mapping is enforced at collection: renaming a mapped test fails the run by
name, and adding an unmapped test fails it too, so the matrix cannot silently
drift.

## Measuring accuracy

Requirements are measured, not asserted. Each script writes its evidence into
`docs/evidence/`.

```bash
python -m scripts.evaluate_accuracy --audio-dir docs/evidence/human_distinct
python -m scripts.evaluate_soap
python -m scripts.load_test
```

| Script | Measures | Write-up |
|---|---|---|
| `evaluate_accuracy.py` | ASR word accuracy, speaker accuracy | `docs/module_9_1_accuracy.md` |
| `evaluate_soap.py` | SOAP section classification | `docs/module_3_soap_classification.md` |
| `load_test.py` | Concurrency and timing | `docs/module_8_3_performance.md` |
| `diagnose_gaps.py` | Evidence the pause heuristic cannot work | — |

---

## How it works

```
audio ──> Whisper ──> pyannote ──> ClinicalBERT ──> ICD-10 / CPT ──> sign ──> EMR
          words       who spoke     SOAP sections    suggestions             sync
```

**Transcription** — OpenAI Whisper `base.en`, with word-level timestamps. Behind
an `ASREngine` protocol so an alternative engine can be substituted. Inference is
serialised on a lock: concurrent calls into one Whisper model corrupt its
attention cache.

**Speaker separation** — pyannote.audio, after three home-built approaches were
built and measured. Word timestamps are mapped to speaker turns, then the
clinician is identified by which speaker asks the questions — history-taking is
question-driven, so this is a majority vote rather than a guess about who spoke
first.

**SOAP drafting** — extractive, so every word is traceable to the transcript.
Patient speech becomes Subjective. Doctor speech is split into sentences and each
sentence classified into Objective, Assessment or Plan by ClinicalBERT zero-shot
similarity. Questions, greetings and announcements are excluded. BioGPT is
retained in the codebase but not on this path: it performed autoregressive
completion rather than following instructions, producing text unrelated to the
transcript.

**Code suggestions** — Assessment text is matched against ICD-10, Plan text
against CPT, five of each, ranked without gaps.

**Signing** — locks the note, finalises the session, and queues the EMR sync.
Irreversible by design.

**Retention** — audio is deleted once the note has synced and the retention window
has elapsed. A scheduled sweep enforces this; clinical text is encrypted at rest
with Fernet.

---

## Measured limitations

Stated plainly because they are measured, and a system whose limits are known is
more useful than one whose limits are assumed away.

**Speaker separation** meets its 85% target when the two voices are acoustically
distinguishable and speak at a conversational pace. It degrades when the voices
are similar, and when turn-taking is rapid enough that turns become very short.
Measured across three recording conditions.

**SOAP Assessment classification is weak** — 1 of 5 diagnostic statements reached
the Assessment section; most were filed under Objective. ClinicalBERT's embedding
captures what a sentence is *about*, not what the speaker is *doing* with it, and
diagnosing, measuring and instructing are speech acts that topic similarity cannot
separate. Filtering of non-clinical speech is solved: 0% of greetings and
questions now reach the note, down from 100%.

**Transcription is CPU-bound** and does not meet the SRS timing target without a
GPU, consistent with the SRS's own hardware constraint. Concurrency does meet its
requirement.

---

## Project layout

```
app/
  api/v1/endpoints/   HTTP endpoints, one module per resource
  core/               settings, logging, error handling, metrics
  db/                 SQLAlchemy base and session
  ml/                 Whisper, pyannote, ClinicalBERT, BioGPT engines
  models/             database models
  schemas/            request and response models
  services/           business logic
  workers/            scheduled retention sweep
docs/                 measurements, evidence, Postman collection, runbooks
scripts/              seeding, evaluation and load-testing tools
simulated_emr_service/  stand-in external EMR
tests/                unit and integration tests, mapped to TC-01…TC-10
```

`PROGRESS.md` tracks completed and outstanding work, including known gaps.

## Before deployment

- Restrict CORS. `allow_origins=["*"]` in `app/main.py` is a development setting.
- Rotate the remaining secrets together: the database password, `JWT_SECRET`
  and `ENCRYPTION_KEY`. Rotating `ENCRYPTION_KEY` invalidates every
  Fernet-encrypted row, so it is done once at deployment alongside the others
  rather than piecemeal. The Hugging Face token was already rotated after being
  visible in a screenshot during development, and no secret has ever been
  committed -- verified against the full git history on 16 August 2026.
- Remove or protect `POST /api/v1/admin/retention/sweep`.
- Provision a GPU if the SRS timing target must be met.

## Licence and data

Academic project. All consultation recordings in `docs/evidence/` are scripted
fiction performed by volunteers. **No real patient data has been used at any
point, and none should be.**
