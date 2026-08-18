# AI-Powered EMR Assistant — Backend

Final year project, Quaid-e-Azam University, Islamabad.
Wajeeha Kamran · Supervisors: Dr. Ayyaz Hussain and Dr. Shahid Khan

A doctor records a consultation. The system transcribes it, works out who was
speaking, drafts a SOAP note, suggests billing codes, and once the doctor has
reviewed and signed the note it syncs it to an EMR and deletes the audio.

The note the system produces is a **draft**. The doctor corrects it, and their
signature is what turns it into a clinical record. That review step is built into
the workflow rather than added as a warning at the end.

**Everything runs on the machine you install it on.** No audio, transcript or note
is sent to any external service. See [What runs where](#what-runs-where) below.

---

## Current status

Phases 0 to 9 of the roadmap are complete and Phase 10 is partly done. All nine
use cases from the SRS are implemented and covered by tests. `PROGRESS.md` has the
module by module log, including the parts that are still open.

---

## What you need

- Python 3.11 or later (I developed on 3.14)
- PostgreSQL 14 or later
- FFmpeg on your PATH — Whisper uses it to decode audio
- About 2 GB of disk for the models, which download the first time you run the
  pipeline

## Setting it up

```bash
python -m venv .venv
.\.venv\Scripts\activate            # Windows
pip install -r requirements.txt
```

Create the two databases:

```sql
CREATE DATABASE emr_assistant;
CREATE DATABASE simulated_emr;
```

Copy `.env.example` to `.env` and fill it in. Copy the file rather than writing
one from memory — it is the authoritative list.

| Variable | What it is |
|---|---|
| `APP_ENV` | `development` or `production`. Required. The app exits at startup if it is missing |
| `DATABASE_URL` | PostgreSQL URL for `emr_assistant` |
| `SIMULATED_EMR_DATABASE_URL` | PostgreSQL URL for `simulated_emr` |
| `SIMULATED_EMR_URL` | Where the simulated EMR listens. Default `http://localhost:8001` |
| `JWT_SECRET` | Key used to sign JWTs |
| `ENCRYPTION_KEY` | Fernet key for encrypting clinical text at rest. Generate one with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `HF_TOKEN` | Hugging Face read token. Needed to download the speaker separation models — see below |
| `AUDIO_STORAGE_DIR` | Where uploaded recordings are written |

`.env` is gitignored. Do not commit it.

### The Hugging Face token, and why you will get stuck without it

This is the step that trips people up, so it is worth reading before you start.

If `HF_TOKEN` is missing, the API still starts, you can still log in, and audio
still uploads. Transcription then fails the moment pyannote loads. It looks like a
broken pipeline when it is actually a missing setting.

Create a read token at <https://huggingface.co/settings/tokens>, then accept the
licence on **all three** of these model pages while signed in:

- `pyannote/segmentation-3.0`
- `pyannote/speaker-diarization-3.1`
- `pyannote/speaker-diarization-community-1`

The third one catches most people out. Loading `speaker-diarization-3.1` under
pyannote 4.x pulls checkpoints from `community-1`, and the error message the other
two produce does not mention it.

### Finally

```bash
alembic upgrade head
python -m scripts.seed_codes
```

## Running it

Two services, two terminals:

```bash
python -m uvicorn app.main:app --port 8000                     # the API
python -m uvicorn simulated_emr_service.main:app --port 8001   # the simulated EMR
```

On Windows, `.\run_backend.ps1` starts both, waits until `/health` actually
answers, and prints the addresses for this machine, an Android emulator and a
phone on the same network.

Interactive API documentation is at <http://127.0.0.1:8000/docs>. You can drive
the whole workflow from that page.

Note syncing only succeeds while the simulated EMR is running.

## Running the tests

```bash
python -m pytest -q
```

The tests run against a **separate database** (`emr_assistant_test`), which is
created and seeded automatically the first time. Your development database is
never touched, and a guard refuses to run against any database whose name does not
end in `_test`.

Every test is mapped to one of the ten STD test cases, and the suite prints the
traceability table at the end of each run. To run the tests for a single test
case, use its marker:

```bash
python -m pytest -m tc06 -q      # speaker separation
python -m pytest -m tc04 -q      # signing and immutability
```

The mapping is enforced when pytest collects the tests. If you rename a mapped
test the run fails by name, and if you add a test without a marker the run fails
too. This is deliberate: a traceability matrix that is maintained by hand goes out
of date, and this one cannot.

## Reproducing the measurements

None of the accuracy figures in this project are asserted. Each one is produced by
a script, and each script writes its evidence into `docs/evidence/`.

```bash
python -m scripts.evaluate_accuracy --audio-dir docs/evidence/human_distinct
python -m scripts.evaluate_soap
python -m scripts.load_test docs/evidence/load_clip.wav
```

| Script | What it measures | Write-up |
|---|---|---|
| `evaluate_accuracy.py` | ASR word accuracy and speaker accuracy | `docs/module_9_1_accuracy.md` |
| `evaluate_soap.py` | SOAP section classification | `docs/module_3_soap_classification.md` |
| `load_test.py` | Concurrency and timing | `docs/module_8_3_performance.md` |
| `diagnose_gaps.py` | Why the original pause based speaker split could not work | — |

---

## How it works

```
audio ──> Whisper ──> pyannote ──> ClinicalBERT ──> ICD-10 / CPT ──> sign ──> EMR
          words       who spoke     SOAP sections    suggestions             sync
```

**Transcription.** OpenAI Whisper `base.en` with word level timestamps. It sits
behind an `ASREngine` protocol so another engine could be dropped in. Inference is
serialised on a lock, because concurrent calls into a single Whisper model corrupt
its attention cache — that was a real bug, not a precaution.

**Speaker separation.** pyannote.audio, arrived at after three home-built
approaches were built and measured. Word timestamps are mapped onto speaker turns,
and the doctor is then identified by which speaker asks the questions. History
taking is question driven, so this is a majority vote across the consultation
rather than a guess based on who spoke first.

**SOAP drafting.** Extractive, which means every word in the note came from the
transcript. Patient speech becomes Subjective. Doctor speech is split into
sentences, and each sentence is classified into Objective, Assessment or Plan
using ClinicalBERT similarity combined with speech act rules. Questions, greetings
and announcements are filtered out. BioGPT is still in the codebase but not on
this path — it performed autoregressive completion rather than following
instructions, and produced text unrelated to the transcript.

**Code suggestions.** Assessment text is matched against ICD-10 and Plan text
against CPT, five of each, ranked by similarity. The doctor accepts or rejects
them.

**Signing.** Locks the note, finalises the session and queues the EMR sync. It is
irreversible by design; after signing, the note is a record rather than a draft.

**Retention.** Audio is deleted once the note has been signed and synced and the
retention window has passed. A scheduled sweep does this. Clinical text in the
database is encrypted at rest with Fernet.

---

## What runs where

Every model runs locally. Nothing about a consultation is sent anywhere.

If you want to check that claim rather than take it, the only outbound HTTP client
in `app/ml` and `app/services` is `emr_sync_client.py`, and it talks to
`SIMULATED_EMR_URL` on localhost. Everything else loads model weights from disk
through `from_pretrained` or `whisper.load_model`.

Two things that look like exceptions but are not:

- **The Hugging Face token** authorises a one time *download* of the pyannote
  weights. Hugging Face hosts model files the way PyPI hosts packages; it is not a
  processing service and never receives consultation data.
- **The package is called `openai-whisper`**, which sounds like the OpenAI API. It
  is OpenAI's open source model released for local use. No API key, no network
  call, transcription on your own CPU.

If you want to remove all doubt, set `HF_HUB_OFFLINE=1` and
`TRANSFORMERS_OFFLINE=1` once the models have been downloaded. The libraries then
load only from the local cache, and you can disconnect the machine from the
internet and still process a full consultation.

---

## Limitations, measured

These are here because they were measured. A system whose limits are known is
easier to work with than one that does not mention them.

**Speaker separation** meets its 85% target when the two voices are acoustically
distinguishable and the pace is conversational. It degrades when the voices are
similar, and when turn taking is rapid enough that turns become very short.
Measured across three recording conditions:

| Condition | Word accuracy | Speaker accuracy |
|---|---|---|
| Distinct voices, conversational | 86.4% | 77.6% |
| Similar voices, rapid turns | 92.1% | 35.9% |
| Synthetic control | 95.3% | 99.9% |

Word accuracy meets the 85% target everywhere. Speaker accuracy does not, in the
similar-voice condition. If you are recording test audio, use two clearly
different voices and leave a small gap between turns.

**SOAP classification** started out weak and was rebuilt. Sorting sentences by
clinical topic alone reached 74.4% accuracy and let every greeting and scheduling
remark through, because those are topically close to the consultation. Adding
speech act rules — who is speaking, and whether the sentence reports, observes,
concludes or instructs — raised it to 97.4% with no non-clinical speech reaching
the note, and the Assessment section went from 0 of 5 correct to 5 of 5. A
held-out set of unseen scenarios scored 38 of 38.

The caveat worth knowing: I wrote both the rules and the held-out sentences, so
this shows the classifier generalises across clinical scenarios but not
necessarily across other people's phrasing.

**Transcription is CPU-bound** and does not meet the SRS timing target without a
GPU, which the SRS itself allows for. Whisper costs about 3.3 seconds per 30
seconds of audio on this hardware, so a 10 minute consultation is roughly 70
seconds of computation. Concurrency does meet its requirement, at 10 of 10
sessions.

---

## Where things live

```
app/
  api/v1/endpoints/   HTTP endpoints, one module per resource
  core/               settings, logging, error handling, metrics
  db/                 SQLAlchemy base and session
  ml/                 Whisper, pyannote, ClinicalBERT and BioGPT engines
  models/             database models
  schemas/            request and response models
  services/           business logic
  workers/            the scheduled retention sweep
docs/                 measurements, evidence, Postman collection, runbooks
scripts/              seeding, evaluation and load testing tools
simulated_emr_service/  the stand-in external EMR
tests/                unit and integration tests, mapped to TC-01 to TC-10
```

`PROGRESS.md` tracks what is done and what is still open, with the reasoning
behind each decision. `docs/demo_runbook.md` is a script for demonstrating the
system in about five minutes.

## Before this is deployed anywhere

- Restrict CORS. `allow_origins=["*"]` in `app/main.py` is a development setting.
- Rotate the remaining secrets together: the database password, `JWT_SECRET` and
  `ENCRYPTION_KEY`. Rotating `ENCRYPTION_KEY` invalidates every encrypted row, so
  it is done once at deployment alongside the others rather than piecemeal. The
  Hugging Face token was already rotated after appearing in a screenshot during
  development, and no secret has ever been committed — I checked the full git
  history on 16 August 2026.
- Remove or protect `POST /api/v1/admin/retention/sweep`.
- Provide a GPU if the SRS timing target has to be met.

## Licence and data

Academic project. Every recording in `docs/evidence/` is a scripted fictional
consultation, performed by volunteers. **No real patient data has been used at any
point in this project, and none should be.**
