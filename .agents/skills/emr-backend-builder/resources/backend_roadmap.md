# AI-Powered EMR Assistant — Backend Implementation Roadmap

*Companion build guide to your SPMP / SRS / SDD / STD documentation. Backend-first, phase-by-phase, written for beginners using Google Antigravity as the development environment.*

---

## Scope Note for This Build

Two deliberate simplifications apply across every phase below, to keep the first pass lean:

- **Minimal by default.** Each module implements only what its own checklist requires — no speculative config, unused dependencies, or scaffolding for future modules. Where a module description below mentions a heavier tool (Celery+Redis, for example), treat that as the *eventual* option, not the starting one — start with the simplest thing that satisfies the current module (FastAPI `BackgroundTasks`, `APScheduler`), and only upgrade if a later module (specifically Phase 8.3's load testing) proves it's genuinely needed.
- **English-only audio, for now.** Whisper is used with `language="en"` explicitly set — no auto-detection, no multi-language handling. This keeps ASR and diarization simpler for the first working version. Multi-language support is a future add-on, not part of this roadmap.

---

## How to Use This Document

Work top to bottom. Part A gets your machine and repo ready. Part B and C tell you how to actually operate Antigravity and which AI model to reach for. Part E is the roadmap itself — one phase at a time, one module at a time, in order. Don't start Module N+1 until Module N's completion checklist is fully checked. Each module is scoped to be a single, reviewable unit of work — roughly what you'd hand to Antigravity as one task and one pull request.

Every phase is traced back to a specific chapter of your documentation (SRS use cases, functional requirements, SDD components, or STD test cases) so nothing here drifts from what you already got approved by your supervisor.

---

# PART A — Before You Open Antigravity

## A1. Backend Tech Stack Overview

This is locked to what your SRS (§2.3.1.3) and SPMP (§1.2.3) already specify — this roadmap doesn't introduce new tech, it just sequences the implementation.

| Layer | Technology | Role in your architecture |
|---|---|---|
| Language/runtime | Python 3.11+ | All backend logic (Application Layer) |
| API framework | FastAPI | Request Controller + all REST endpoints |
| ASR (prototype) | OpenAI Whisper | Speech-to-text for consultation audio |
| ASR (deployment-ready) | NVIDIA Riva | Swap-in target once prototype is validated |
| Diarization | pyannote.audio (or a lightweight heuristic for the two-role case) | Doctor/Patient speaker labeling |
| Medical NLP | BioGPT | SOAP draft structuring |
| Medical NLP | ClinicalBERT | Clinical understanding + ICD-10/CPT relevance scoring |
| Database | PostgreSQL 15+ | EMR Assistant schema + Simulated EMR schema (logically separated per SRS §2.6) |
| ORM / migrations | SQLAlchemy 2.x + Alembic | Data Layer |
| Auth | OAuth2 password flow + JWT | Doctor authentication (SRS assumption: "clinicians are authenticated and authorized") |
| Background processing | Celery + Redis (or APScheduler for lighter needs) | Long-running ASR/NLP jobs, retention cleanup |
| Containerization | Docker + docker-compose | Local + deployment parity |
| API testing | Postman | Manual/collection-based endpoint verification (per STD §4.2.3) |
| Automated testing | pytest, pytest-asyncio, httpx | Unit + integration tests mapped to TC-01…TC-10 |
| Version control | Git + GitHub | SPMP §1.2.3 |
| Docs | FastAPI auto OpenAPI/Swagger | API contract for the future .NET MAUI/Blazor frontend |

Frontend (.NET MAUI / Blazor) is explicitly out of scope until the backend roadmap below is complete — that matches your own stated plan.

## A2. Full Install List

### System-level (install once, outside Python)
- Python 3.11 or 3.12
- PostgreSQL 15+ (with the `pgvector` extension available — you'll use it for ICD-10/CPT semantic matching in Phase 4)
- Git
- Docker Desktop
- FFmpeg (required by Whisper for audio decoding)
- Redis (for Celery, or run it via Docker instead of installing natively)
- Google Antigravity (desktop app)

### Python packages, grouped by purpose

**Core API**
`fastapi`, `uvicorn[standard]`, `pydantic`, `pydantic-settings`, `python-dotenv`, `python-multipart` (needed for audio file uploads)

**Database**
`sqlalchemy`, `alembic`, `asyncpg` (async Postgres driver) or `psycopg2-binary` if you prefer sync, `pgvector` (Python client)

**Auth/security**
`python-jose[cryptography]`, `passlib[bcrypt]`, `cryptography`

**ASR / diarization**
`openai-whisper` (or `faster-whisper` for better CPU performance), `pydub`, `pyannote.audio` (optional — see Phase 2 module notes on a simpler alternative)

**Medical NLP**
`transformers`, `torch`, `accelerate`, `sentencepiece`

**Background jobs**
`celery`, `redis`, or `apscheduler` if you skip Celery initially

**Testing**
`pytest`, `pytest-asyncio`, `httpx`, `factory-boy` or `Faker` (synthetic test data — never use real patient audio/text)

**Dev tooling / quality**
`black`, `isort`, `ruff` (or `flake8`), `mypy`, `bandit` (security linter), `pre-commit`

**Production server**
`gunicorn` (paired with `uvicorn.workers.UvicornWorker`)

A note on hardware: BioGPT/ClinicalBERT and Whisper are heavy. For day-to-day development, use the smallest Whisper checkpoint (`base` or `small`) and CPU inference — save GPU-backed runs (Colab, Kaggle, or a rented GPU) for accuracy evaluation against the STD's 85% WAcc/diarization targets. This matches the STD's own testing environment note ("GPU optional for faster ASR").

## A3. Recommended Project Folder Structure

This mirrors your SDD's Three-Tier Architecture (§3.2.1) directly, so every folder maps to a named component in your design document.

```
emr-assistant-backend/
├── app/
│   ├── main.py                      # FastAPI app entrypoint
│   ├── core/                        # cross-cutting config
│   │   ├── config.py                 # pydantic-settings, env vars
│   │   ├── security.py               # JWT, password hashing
│   │   └── logging.py
│   ├── api/                         # PRESENTATION LAYER (routers only, no logic)
│   │   └── v1/
│   │       ├── endpoints/
│   │       │   ├── auth.py
│   │       │   ├── sessions.py
│   │       │   ├── audio.py
│   │       │   ├── transcripts.py
│   │       │   ├── soap_notes.py
│   │       │   ├── code_suggestions.py
│   │       │   ├── signatures.py
│   │       │   └── emr_sync.py
│   │       └── router.py
│   ├── services/                    # APPLICATION LAYER (business logic)
│   │   ├── session_manager.py
│   │   ├── audio_handler.py
│   │   ├── asr_service.py
│   │   ├── diarization_service.py
│   │   ├── soap_generator.py
│   │   ├── code_suggester.py
│   │   ├── note_finalizer.py
│   │   ├── emr_sync_client.py
│   │   └── retention_service.py
│   ├── ml/                          # model wrappers, kept separate from business logic
│   │   ├── whisper_engine.py
│   │   ├── riva_engine.py            # stub now, real later — see Module 2.4
│   │   ├── biogpt_engine.py
│   │   └── clinicalbert_engine.py
│   ├── models/                      # DATA LAYER — SQLAlchemy ORM
│   │   ├── doctor.py
│   │   ├── session.py
│   │   ├── transcript.py
│   │   ├── soap_note.py
│   │   ├── code_suggestion.py
│   │   ├── signature.py
│   │   └── simulated_emr_record.py
│   ├── schemas/                     # Pydantic request/response DTOs
│   ├── db/
│   │   ├── base.py
│   │   ├── session.py                # DB session dependency
│   │   └── init_db.py
│   └── workers/                     # Celery tasks
├── simulated_emr_service/           # standalone mock EMR (its own schema/app)
├── alembic/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── conftest.py
├── scripts/
├── docker/
├── .env.example
├── docker-compose.yml
├── Dockerfile
├── requirements.txt (or pyproject.toml)
└── README.md
```

Keep the **Presentation → Application → Data** boundary strict: routers in `api/` never talk to the database directly, and services never import from `api/`. This is what makes the codebase match your SDD and stay testable.

## A4. Initial Project Setup Steps

1. Install all A2 system-level tools.
2. Create the GitHub repo (`emr-assistant-backend`), clone it locally.
3. Open the repo in Antigravity, and let it index the project.
4. Create a Python virtual environment (`python -m venv .venv`) and activate it.
5. Create the folder structure from A3 (empty files are fine for now).
6. Create PostgreSQL databases: one for `emr_assistant`, one for `simulated_emr` (matches SRS §2.6's "kept logically separate").
7. Write `.env.example` with placeholders for `DATABASE_URL`, `SIMULATED_EMR_DATABASE_URL`, `JWT_SECRET`, `REDIS_URL`.
8. Install the core dependency group from A2 and freeze into `requirements.txt`.
9. Set up `pre-commit` with `black`, `isort`, `ruff`.
10. Commit this skeleton to `main` before writing any feature code — this is your baseline.
11. Confirm Antigravity can run your terminal commands (`pytest`, `uvicorn`) inside the project without manual copy-pasting.
12. Only then move to Phase 0, Module 0.1 below.

---

# PART B — Working With Antigravity

## B1. What Antigravity Actually Gives You

Antigravity has two surfaces. The **Editor View** is a synchronous, VS Code-style experience with an agent sidebar — use it when you want to watch code being written in real time. The **Manager View** is where you spawn and supervise agents working asynchronously, in parallel, across separate workspaces — use it once you're running more than one module at a time.

Instead of dumping raw tool calls at you, Antigravity's agents produce **Artifacts**: task lists, implementation plans, and verification evidence (like test runs or screenshots) that you can comment on directly, the way you'd leave feedback on a shared doc. That comment loop, not blind acceptance, is how you keep control.

Antigravity also lets you pick an autonomy level per task: full **agent-driven** ("autopilot"), **review-driven** (agent proposes, you approve every step), or the recommended middle ground, **agent-assisted**, where the agent acts but pauses at meaningful checkpoints. Use different levels for different modules — this roadmap tells you which is which.

## B2. How to Structure Prompts, Module by Module

Every prompt to Antigravity should contain four things, in this order:

1. **Context** — paste (or reference) the module's Objective, Features, and Files/Folders sections straight out of this roadmap.
2. **Boundaries** — name exactly which files/folders it may touch, and which architectural layer rule applies (e.g., "services/ only, do not modify api/ routers in this task").
3. **Acceptance criteria** — paste the module's Completion Checklist verbatim and tell it the task isn't done until every box is genuinely satisfied, including tests passing.
4. **Mode** — tell it explicitly: "Use Plan mode first and show me the implementation plan before writing code" for anything non-trivial.

**Worked example — Module 1.2 (Start Recording Endpoint):**

> "Implement Module 1.2 from the roadmap: the Start Recording endpoint. Objective: allow an authenticated doctor to start a consultation recording, per UC-01 in the SRS. Only touch `app/api/v1/endpoints/sessions.py`, `app/services/session_manager.py`, and their matching test files — don't modify the SOAP or transcript modules. Session state must transition to `RECORDING` on success. Handle the two alternate flows from UC-01: microphone/storage unavailable should return a clear 4xx error, not a 500. Write pytest coverage for both the happy path and both alternate flows before marking this done. Show me your implementation plan first."

Reuse this pattern for every module — swap in that module's specifics.

## B3. What to Delegate to Antigravity

- Scaffolding routers, Pydantic schemas, and SQLAlchemy models from a spec you give it
- Writing Alembic migrations once you've approved the schema shape
- Writing unit and integration tests from the TC-01…TC-10 descriptions in your STD
- Generating Postman collections and keeping OpenAPI docs in sync
- Docker/docker-compose and CI config scaffolding
- Refactors, lint/format fixes, docstrings, README sections
- Running the test suite and iterating on failures autonomously

## B4. What You Must Do or Review Yourself

- **Database schema decisions.** Approve the entity design yourself (it should mirror your SDD's class diagram); let the agent implement it, not invent it.
- **Auth and secrets.** Review JWT secret handling, password hashing config, and anything touching `.env` before merging.
- **Encryption-at-rest and retention/deletion logic.** This is the module that enforces your SRS's "temporary data deleted within ≤5 minutes after signing and sync" requirement — clinical data handling deserves a manual read-through, not a rubber stamp.
- **SOAP structural validation and ASR/diarization accuracy tuning.** The agent can implement the checks; you decide what "good enough" clinically means, since the doctor remains the final authority per your abstract.
- **Anything destructive in the terminal** — dropped tables, force-pushes, deleted migrations. Set Terminal Policy to require confirmation for these even though "Auto" is the default.
- **Final merge decisions.** Treat every Antigravity Artifact like a PR: read it, comment on it, then approve.

## B5. Best Practices for This Project Specifically

- **One module = one agent task = one PR.** Don't let scope creep across modules; it makes review and rollback much harder.
- **Start in Plan mode** for anything beyond trivial boilerplate — read the plan artifact before letting it execute.
- **Use Manager View for independent modules only.** You can safely run, say, Phase 2 (ASR) and Phase 6 (EMR sync) in parallel workspaces since they don't share files. Don't parallelize modules that both touch `models/` or `schemas/` — you'll get merge conflicts.
- **Keep a condensed spec pack in `/docs`** — trimmed excerpts of your SRS/SDD/STD relevant to the backend — and point Antigravity at it. Antigravity can save this to its knowledge base so future tasks reuse the context automatically.
- **Never paste real patient data.** This project handles clinical documentation; always use synthetic/dummy consultation audio and text, even in prompts and test fixtures.
- **Tie "done" to green tests, always.** Don't accept a module as complete on code existing alone — require the checklist's testing item to be satisfied first.

---

# PART C — Which AI to Use for What

No single model is best at everything, and the landscape shifts every few months — treat this as a starting point, not gospel, and check current leaderboards before committing to a long project.

| Task | Recommended model | Why | Where to access |
|---|---|---|---|
| Planning / architecture decisions (this roadmap, schema design, sequencing) | Claude Opus (current-gen, e.g. via claude.ai) | Strongest for long-horizon reasoning across a whole spec and for holding multi-chapter documentation in mind at once | claude.ai, Claude Code |
| Day-to-day coding inside Antigravity | Antigravity's native Gemini model (default in the picker) | Built-in, generous free limits, strong agentic/SWE-bench performance, large context for whole-repo awareness | Antigravity's model picker |
| Complex or elusive debugging (ASR pipeline failures, sync race conditions, concurrency issues) | Claude Opus-class model | Consistently strong on multi-file debugging benchmarks and reasoning through unfamiliar failure modes | Antigravity's model picker (if listed) or claude.ai/Claude Code |
| Security review (auth, JWT, encryption-at-rest, HTTPS) | Claude Opus-class model, paired with static tools | Good for reasoning about secure system design end-to-end — but pair it with non-LLM tools below, don't rely on chat review alone | claude.ai, Claude Code, plus `bandit` / `pip-audit` / `semgrep` locally |
| Code review of PRs/diffs | Claude Sonnet-class model | Near-frontier quality at lower cost — a sensible daily driver for reviewing every module's diff | Antigravity, claude.ai |
| Test generation (pytest, Postman collections) | Antigravity's native model or Claude Sonnet-class model | Structured, repetitive generation where speed matters more than deep novel reasoning | Antigravity |
| Documentation (README, docstrings, API descriptions) | Claude Sonnet-class model | Reliable, professional prose that stays consistent across long documents | claude.ai, Antigravity |
| High-volume boilerplate (CRUD stubs, migrations, comments) | A "flash"/cheap tier model | Fast and inexpensive for low-risk, repetitive generation | Antigravity's model picker |

A practical routing rule: if the task involves security, money-equivalent correctness (here: clinical documentation and signed records), or a bug you can't reproduce reliably, escalate to the strongest model available to you. Everything else can run on the cheaper default.

---

# PART D — Traceability Snapshot

Every phase below maps back to your own documentation, so you can cross-check against SDD Table 3.1 (Requirements Traceability Matrix) as you go.

| Phase | SRS Use Case(s) | Functional Req(s) | STD Test Case(s) |
|---|---|---|---|
| 0 — Bootstrap | — (infrastructure) | — | — |
| 1 — Session & Audio | UC-01, UC-02, UC-05 | FR-01, FR-08 | TC-01, TC-02, TC-05 |
| 2 — ASR & Diarization | UC-06 | FR-02 | TC-06 |
| 3 — SOAP Generation | UC-07 | FR-03 | TC-07 |
| 4 — Code Suggestions | UC-08 | FR-04 | TC-08 |
| 5 — Review & Sign | UC-03, UC-04 | FR-05, FR-06 | TC-03, TC-04 |
| 6 — EMR Sync | UC-09 | FR-07 | TC-09, TC-10 |
| 7 — Retention Enforcement | UC-05 (completion) | FR-08 | TC-05 |
| 8 — Security/Reliability/Perf | NFRs (§2.3.3) | — | cross-cutting |
| 9 — Testing & Docs | all | all | TC-01…TC-10 |
| 10 — Deployment | — | — | — |

---

# PART E — The Roadmap: Phases & Modules

## PHASE 0 — Environment & Core Bootstrap

*No use case yet — this phase builds the skeleton every later feature plugs into.*

### Module 0.1 — FastAPI App Skeleton & Config Management
- **Objective:** A running FastAPI app with a `/health` endpoint and centralized settings management.
- **Why now:** Nothing else can be built or tested without an app to run.
- **Features:** App factory pattern in `main.py`; `pydantic-settings`-based config reading from `.env`; structured logging setup.
- **Files/folders:** `app/main.py`, `app/core/config.py`, `app/core/logging.py`
- **Database changes:** None yet.
- **API endpoints:** `GET /health` → `{"status": "ok"}`
- **Dependencies:** `fastapi`, `uvicorn[standard]`, `pydantic-settings`, `python-dotenv`
- **Testing:** One test asserting `/health` returns 200.
- **Completion checklist:**
  - [ ] App boots locally with `uvicorn app.main:app --reload`
  - [ ] `/health` returns 200 and correct JSON
  - [ ] Settings load from `.env` correctly, fail loudly if a required var is missing
  - [ ] Test passes

### Module 0.2 — Database Connectivity (Two Logical Schemas)
- **Objective:** Working SQLAlchemy + Alembic setup against both the EMR Assistant DB and the Simulated EMR DB, per SRS §2.6.
- **Why now:** Every subsequent module persists data — this must exist first.
- **Features:** Async (or sync) DB engine/session factories for both schemas; Alembic initialized and pointed at the EMR Assistant schema; base declarative model class.
- **Files/folders:** `app/db/base.py`, `app/db/session.py`, `alembic/`, `alembic.ini`
- **Database changes:** Create `emr_assistant` and `simulated_emr` databases (or schemas within one instance); enable the `pgvector` extension on `emr_assistant` (used later in Phase 4).
- **API endpoints:** None.
- **Dependencies:** `sqlalchemy`, `alembic`, `asyncpg` or `psycopg2-binary`, `pgvector`
- **Testing:** Test that a DB session can be opened and closed cleanly against a test database.
- **Completion checklist:**
  - [ ] `alembic upgrade head` runs cleanly against a fresh database
  - [ ] Both schemas are reachable from the app via distinct connection strings
  - [ ] `pgvector` extension confirmed enabled
  - [ ] DB session test passes

### Module 0.3 — Doctor Authentication & Authorization
- **Objective:** Doctors can register/log in and receive a JWT; all subsequent endpoints require it. Satisfies the SRS assumption that "clinicians are authenticated and authorized" and the UC-01 precondition "doctor is logged in."
- **Why now:** Every use case from UC-01 onward assumes an authenticated doctor.
- **Features:** `Doctor` model; password hashing; JWT issuance/verification; a `get_current_doctor` FastAPI dependency for reuse everywhere.
- **Files/folders:** `app/models/doctor.py`, `app/core/security.py`, `app/api/v1/endpoints/auth.py`, `app/schemas/doctor.py`
- **Database changes:** New `doctors` table (id, email, hashed_password, full_name, created_at).
- **API endpoints:** `POST /api/v1/auth/register`, `POST /api/v1/auth/login` (returns JWT)
- **Dependencies:** `python-jose[cryptography]`, `passlib[bcrypt]`
- **Testing:** Register → login → access a protected dummy route succeeds; wrong password and missing token both correctly rejected.
- **Completion checklist:**
  - [ ] Passwords are hashed, never stored or logged in plaintext
  - [ ] JWT secret is read from `.env`, not hardcoded
  - [ ] Protected-route dependency rejects missing/invalid/expired tokens correctly
  - [ ] All auth tests pass

**⚠️ Manual review required:** secrets handling and hashing config (see Part B4).

---

## PHASE 1 — Consultation Session & Audio Capture

*Maps to Sprint 1 in your SPMP. Covers UC-01, UC-02, UC-05 and FR-01, FR-08.*

### Module 1.1 — ConsultationSession Domain Model & Lifecycle
- **Objective:** A `ConsultationSession` entity that tracks state through `INITIATED → RECORDING → STOPPED → FINALIZED`, per SDD §3.3.3 (Session Manager).
- **Why now:** Every artifact (audio, transcript, SOAP note) hangs off a session ID — this must exist before anything else in this phase.
- **Features:** Session state enum; creation on doctor login/session start; state-transition guard logic (no illegal jumps, e.g. can't go straight from `INITIATED` to `FINALIZED`).
- **Files/folders:** `app/models/session.py`, `app/services/session_manager.py`, `app/schemas/session.py`
- **Database changes:** New `consultation_sessions` table (id, doctor_id FK, status enum, created_at, started_at, stopped_at, finalized_at).
- **API endpoints:** `POST /api/v1/sessions` (create/initiate a session)
- **Dependencies:** none new
- **Testing:** Valid transitions succeed; invalid transitions raise a clear error; session correctly links to the authenticated doctor.
- **Completion checklist:**
  - [ ] All four states represented and enforced
  - [ ] Illegal transitions rejected with a clear error, not a silent no-op
  - [ ] Session always linked to `doctor_id` from the JWT, never a client-supplied value
  - [ ] Tests pass

### Module 1.2 — Start Recording Endpoint (UC-01)
- **Objective:** Doctor starts recording; session moves to `RECORDING`; the two UC-01 alternate flows (mic permission denied, storage/network unavailable) are handled explicitly.
- **Why now:** First real use-case-driven endpoint; validates the session lifecycle from 1.1 end-to-end.
- **Features:** Start-recording endpoint; explicit error responses for both alternate flows from the SRS.
- **Files/folders:** `app/api/v1/endpoints/sessions.py`, updates to `session_manager.py`
- **Database changes:** None beyond 1.1.
- **API endpoints:** `POST /api/v1/sessions/{id}/start-recording`
- **Dependencies:** none new
- **Testing:** Happy path (→ `RECORDING`); both alternate flows return 4xx, not 500; unauthenticated request rejected.
- **Completion checklist:**
  - [ ] Successful start transitions state correctly
  - [ ] Both alternate flows from UC-01 produce clear, distinct error responses
  - [ ] Recording status is retrievable immediately after starting
  - [ ] Tests pass, mapped to TC-01

### Module 1.3 — Stop Recording + Audio Handler (UC-02, FR-01)
- **Objective:** Doctor stops recording; audio file is uploaded and stored with metadata (fileRef, duration, timestamps); session moves to `STOPPED`.
- **Why now:** This is the trigger that later phases (ASR, SOAP) hang off of — nothing downstream works until audio is reliably captured and referenced.
- **Features:** Multipart audio upload endpoint; basic validation (format, max 30-minute duration per NFR §2.3.3 Efficiency); audio metadata persistence; temporary file storage.
- **Files/folders:** `app/api/v1/endpoints/audio.py`, `app/services/audio_handler.py`, `app/models/session.py` (extend with audio fields or a separate `audio_metadata` table)
- **Database changes:** New `audio_metadata` table (id, session_id FK, file_ref, duration_seconds, format, uploaded_at) or embed on session — your call, but keep it separate for clean querying.
- **API endpoints:** `POST /api/v1/sessions/{id}/stop-recording` (accepts the audio file)
- **Dependencies:** `python-multipart`, `pydub` (duration/format checks), `aiofiles` (async file writes)
- **Testing:** Valid upload persists correctly; oversized/invalid-format audio rejected with a clear error; session transitions to `STOPPED`.
- **Completion checklist:**
  - [ ] Audio stored with correct metadata (fileRef, duration, timestamps)
  - [ ] 30-minute session cap enforced (NFR — "Upload/processing should support audio recordings up to 30 minutes per session")
  - [ ] Session status correctly becomes `STOPPED`
  - [ ] Tests pass, mapped to TC-02

### Module 1.4 — Temporary Storage & Retention Policy Skeleton (UC-05, FR-08)
- **Objective:** Formalize "temporary" — track that audio/intermediate artifacts are linked to a session and slated for deletion once the session is finalized and synced. (Full automated cleanup is finished in Phase 7 — this module just builds the tracking scaffolding.)
- **Why now:** You want retention rules designed alongside the data model, not bolted on afterward — retroactively adding deletion logic to a live schema is painful.
- **Features:** A `retention_marked_for_deletion_at` / `deleted_at` field on temporary artifacts; a service method that flags artifacts as eligible for cleanup once a session is finalized.
- **Files/folders:** `app/services/retention_service.py` (skeleton only for now)
- **Database changes:** Add retention-tracking columns to `audio_metadata` (and later, transcript artifacts).
- **API endpoints:** None yet (internal service only).
- **Dependencies:** none new
- **Testing:** Flagging logic correctly marks artifacts only after finalization, never before.
- **Completion checklist:**
  - [ ] Retention fields exist on all temporary-artifact tables
  - [ ] Flagging only triggers post-finalization, verified by test
  - [ ] Signed SOAP notes are explicitly excluded from any deletion flagging (they're permanent per SRS §2.6)

---

## PHASE 2 — ASR & Two-Role Diarization Pipeline

*Maps to Sprint 2. Covers UC-06 and FR-02.*

### Module 2.1 — Whisper ASR Integration
- **Objective:** Convert stored consultation audio into raw text via Whisper, locked to English for this build.
- **Why now:** First AI pipeline stage — everything downstream (diarization, SOAP, codes) depends on transcript text existing.
- **Features:** A wrapper service that loads a Whisper model once (not per-request) and transcribes a given audio file with `language="en"` explicitly set (no auto-detection); async/background execution so the request thread isn't blocked.
- **Files/folders:** `app/ml/whisper_engine.py`, `app/services/asr_service.py`
- **Database changes:** None yet (transcript persistence comes in 2.3).
- **API endpoints:** None directly — triggered internally by the stop-recording flow or a background worker.
- **Dependencies:** `openai-whisper` or `faster-whisper`, FFmpeg (system-level)
- **Testing:** Transcription of a short synthetic audio clip produces non-empty text; failure path (corrupt file) raises a catchable, specific exception.
- **Completion checklist:**
  - [ ] Model loads once at startup/worker init, not per request
  - [ ] Transcription runs without blocking the main API event loop
  - [ ] Failure is caught and surfaced as a specific error, not a raw stack trace
  - [ ] Tests pass on synthetic audio

### Module 2.2 — Two-Role Diarization (Doctor/Patient)

> **Revision note (discovered during Module 3.3 testing):** Real-world testing note: Manual end-to-end testing during Module 3.3 revealed that the pause-based diarization heuristic depends on Whisper producing a segment boundary at the actual speaker change — if Whisper merges both speakers' speech into one segment (common with short pauses or single-speaker test recordings), diarization cannot separate them, regardless of pause length. A pretrained audio-based alternative (pyannote.audio) would fix this properly but requires a substantial rework of this module plus Module 2.3's calling code. Decision: defer this evaluation to Module 9.1, where diarization accuracy will be measured against real recorded mock consultations (per the SRS's ≥85% diarization accuracy NFR) rather than decided reactively from a single adversarial test. If measured accuracy falls short, revisit the pyannote.audio upgrade at that point with real evidence.

- **Objective:** Label transcript segments as `DOCTOR` or `PATIENT`, meeting the SRS's mandatory two-role diarization requirement.
- **Why now:** SOAP generation and downstream review both depend on knowing who said what.
- **Features:** A diarization service. For a genuine prototype, `pyannote.audio` gives real speaker-separation; a simpler, faster-to-build fallback is a turn-based heuristic (alternate speaker on pause-length thresholds) if you need to hit your sprint deadline first and refine accuracy later — document which one you chose and why, since the STD requires ≥85% labeling accuracy on your evaluation dataset.
- **Files/folders:** `app/services/diarization_service.py`
- **Database changes:** None yet (persisted together with transcript in 2.3).
- **API endpoints:** None directly (internal pipeline stage).
- **Dependencies:** `pyannote.audio` (optional, heavier) — or no new dependency if you go heuristic-first.
- **Testing:** Given a synthetic two-speaker sample, every segment gets a `DOCTOR` or `PATIENT` label — never null.
- **Completion checklist:**
  - [ ] Every transcript segment has a non-null speaker role
  - [ ] Accuracy measured against a small labeled evaluation set and logged (target ≥85% per SRS §2.3.3)
  - [ ] Approach documented (heuristic vs. model-based) for your final report

### Module 2.3 — Transcript & TranscriptSegment Persistence + Finalization API
- **Objective:** Store the diarized transcript, expose it, and mark it finalized once recording processing completes.
- **Why now:** Closes out UC-06 — gives you a durable, queryable transcript that Phase 3 consumes.
- **Features:** `Transcript` and `TranscriptSegment` models; an endpoint to retrieve the finalized transcript for a session; retry endpoint for ASR failure (per UC-06's alternate flow "ASR fails → allow retry/reprocess").
- **Files/folders:** `app/models/transcript.py`, `app/api/v1/endpoints/transcripts.py`
- **Database changes:** New `transcripts` table (id, session_id FK, finalized_at) and `transcript_segments` table (id, transcript_id FK, speaker_role enum, text, start_time, end_time).
- **API endpoints:** `GET /api/v1/sessions/{id}/transcript`, `POST /api/v1/sessions/{id}/transcript/retry`
- **Dependencies:** none new
- **Testing:** End-to-end: upload audio → transcript appears with ≥1 segment, every segment has a speaker role in `{DOCTOR, PATIENT}`; retry endpoint successfully reprocesses on simulated failure.
- **Completion checklist:**
  - [ ] Transcript created with ≥1 segment on success (matches TC-06 pass criteria exactly)
  - [ ] Every segment has speakerRole + timestamps
  - [ ] Retry path works after a simulated ASR failure
  - [ ] Tests pass, mapped to TC-06

### Module 2.4 — Riva-Ready Abstraction Layer
- **Objective:** Decouple the ASR call site from the specific engine (Whisper today, Riva later), satisfying your NFR §2.5.3 Maintainability requirement ("Models can be updated: Whisper → Riva").
- **Why now:** Cheap to build now, expensive to retrofit — do it right after Whisper works, before other modules build tight coupling to it.
- **Features:** An `ASREngine` interface/protocol with a `transcribe(audio) -> Transcript` method; `WhisperEngine` implements it now; `RivaEngine` is a documented stub for later; engine selection driven by config, not hardcoded imports.
- **Files/folders:** `app/ml/whisper_engine.py` (refactored to implement the interface), `app/ml/riva_engine.py` (stub), `app/ml/base.py` (interface definition)
- **Database changes:** None.
- **API endpoints:** None (internal refactor).
- **Dependencies:** none new
- **Testing:** Swapping the configured engine (via a test double) doesn't require touching `asr_service.py`.
- **Completion checklist:**
  - [ ] `asr_service.py` depends only on the interface, never imports Whisper directly
  - [ ] Engine selection is a one-line config change
  - [ ] Existing Module 2.1/2.3 tests still pass after the refactor

---

## PHASE 3 — SOAP Note Draft Generation

*Maps to Sprint 3. Covers UC-07 and FR-03.*

### Module 3.1 — BioGPT Integration Service

> **Revision note (discovered during implementation):** Testing with real, varied transcripts showed that raw `microsoft/biogpt` (347M params) does not reliably use the input transcript at all — it exhibits strong few-shot copying bias, echoing the hardcoded prompt example almost verbatim regardless of what the patient actually said. This is a known limitation of small (sub-billion-parameter) language models, which generally lack reliable in-context learning ability. Confirmed with three distinct test transcripts (headache/nausea, sprained ankle, chest pain) — all three produced near-identical, wrong output.
>
> **Revised approach — hybrid extraction + constrained generation, modeled on published two-stage clinical summarization architectures (e.g. ClinicSum):** Rather than asking BioGPT to read a full transcript and decide what's relevant (a task it cannot reliably do at this scale), the pipeline now splits the job in two:
> 1. **Extraction (ClinicalBERT):** Each transcript segment is embedded via ClinicalBERT and classified into a SOAP category (Subjective/Objective/Assessment/Plan) using zero-shot similarity against a small set of hardcoded reference descriptions per category — no fine-tuning, consistent with the minimalism rule. This surfaces the *actual patient/doctor words* relevant to each section.
> 2. **Constrained generation (BioGPT):** BioGPT's role shrinks to rephrasing the already-extracted real content into clinical note language for each section — a much easier, more bounded task than free generation from a full transcript, since the content it works from is now directly relevant rather than distant/abstract.
> 3. The existing fallback logic (Module 3.1's original design) is preserved: if a category has no matching segments (e.g. no Objective data from audio-only input), it falls back to `"Not documented in dialogue."` rather than fabricating content.
>
> **Roadmap impact:** This pulls the ClinicalBERT model/engine setup forward from Module 4.1 into Module 3.1. Module 4.1 (below) should **reuse and extend** the ClinicalBERT engine built here rather than re-integrating it from scratch — see the note on Module 4.1.
>
> **Residual known limitations (acceptable for prototype, must be documented):**
> 1. **Cross-category misclassification:** Content that clearly belongs in one SOAP category can still be assigned to a different one by the zero-shot similarity classifier. Confirmed empirically: a segment containing explicit treatment/prescription instructions ("prescribe ibuprofen 400mg...schedule an X-ray") was classified as SUBJECTIVE rather than PLAN. The speaker-role bias (+0.03 toward OBJECTIVE for DOCTOR segments) does not fix this specific case because it only biases toward OBJECTIVE, not PLAN. *(Historical note: Prior to the Module 4.1 mean-pooling fix, raw ClinicalBERT `[CLS]` embeddings suffered from severe anisotropy, compressing cosine similarities into a narrow 0.63–0.89 range. Mean pooling has since resolved this specific mathematical compression, but the conceptual limitation of zero-shot cross-category overlap remains).*
> 2. **Non-clinical noise segments are not filtered:** Segments with no clinical content (greetings, small talk, e.g. "Hello, how are you? Please take a seat.") are still classified into a real SOAP category (in testing, the greeting was assigned to PLAN) and sent to BioGPT for rephrasing. This can produce odd or low-value output in that section. The pipeline does not apply a minimum similarity threshold to exclude noise, because the prior anisotropy issue made any absolute threshold meaningless. Future improvement could add a separate noise-detection step or use mean-pooled embeddings with whitening.
>
> These are acceptable residual limitations for a prototype. The hybrid pipeline's primary job is to fix the catastrophic copying-bias failure (three different transcripts producing identical wrong output), not to achieve perfect section classification. Doctor review of the generated draft remains mandatory.

> **Final revision — extractive-only pipeline (BioGPT removed from critical path):** Testing the hybrid pipeline's BioGPT rephrasing step with real transcripts showed it also failed to follow instructions. BioGPT performed autoregressive completion rather than rephrasing — confirmed output showed the model echoing the doctor's own greeting/question verbatim as the Subjective section content instead of summarizing patient-reported symptoms. Since the "rephrased" output was strictly worse than the raw extracted text, BioGPT was removed from `generate_draft`'s execution path entirely. The final design is purely extractive: PATIENT segments → SUBJECTIVE deterministically, DOCTOR segments → classified into OBJECTIVE/ASSESSMENT/PLAN via ClinicalBERT. Output text is the real transcript content with a deterministic prefix, guaranteeing every word is traceable to the actual dialogue.
> 
> **Noise segment force-classification limitation:** Doctor-spoken noise segments (e.g. doctor's greetings/fillers) are still force-classified into one of the three candidate doctor sections (Objective, Assessment, Plan) because no similarity threshold exists (anisotropy makes a static threshold impossible). Consequently, non-clinical speech from the doctor can occasionally pollute these sections. The Subjective section is now completely protected from doctor noise since it only extracts Patient segments.
> 
> **Casual assessment-phrasing misclassification:** Doctor assessment statements phrased conversationally (e.g. "This looks like a migraine" or "The ankle appears sprained, not fractured") are misclassified as OBJECTIVE rather than ASSESSMENT. *(Historical note: this was confirmed by pre-mean-pooling diagnostic scores of 0.849 vs 0.770, and 0.840 vs 0.788 respectively. These specific scores describe the old `[CLS]` behavior, but the conceptual risk of conversational vs. clinical phrasing remains).* Only explicitly clinical-register phrasing ("Clinical diagnosis is...", "Prognosis is...") reliably lands in ASSESSMENT. Since real consultation speech is more likely to be casual than clinically formal, ASSESSMENT content may be under-represented in that section and appear in OBJECTIVE instead. This is acceptable for the prototype but should be flagged for improvement if assessment-section accuracy becomes a priority (e.g. richer reference descriptions, or a fine-tuned classifier).

- **Objective:** Turn a finalized transcript into a structured SOAP draft using a purely extractive pipeline (PATIENT segments → Subjective, DOCTOR segments → ClinicalBERT classification).
- **Why now:** This is the project's central value proposition — it can only start once a reliable transcript exists (Phase 2 done).
- **Features:** A ClinicalBERT engine wrapper for zero-shot segment classification into SOAP categories. The BioGPT engine is retained in the codebase but removed from the critical path. Both models loaded once, run off the request thread.
- **Files/folders:** `app/ml/biogpt_engine.py`, `app/services/soap_generator.py`
- **Database changes:** None yet.
- **API endpoints:** None directly (internal pipeline stage, triggered after transcript finalization or on demand).
- **Dependencies:** `transformers`, `torch`, `accelerate`, `sentencepiece`
- **Testing:** Given a synthetic transcript, output always contains exactly four sections, non-empty.
- **Completion checklist:**
  - [ ] Model loads once, not per call
  - [ ] Output structurally validated (4 sections) before being returned to the caller
  - [ ] Malformed/empty transcript input handled gracefully, not a crash

### Module 3.2 — SOAPNote & SOAPSection Data Model
- **Objective:** Persist SOAP drafts with their four sections as first-class, individually editable records.
- **Why now:** Needed before you can expose review/edit endpoints in Phase 5, and before code suggestions (Phase 4) can attach to a note.
- **Features:** `SOAPNote` (status: `DRAFT`/`SIGNED`) and `SOAPSection` (type enum: `SUBJECTIVE`/`OBJECTIVE`/`ASSESSMENT`/`PLAN`) models.
- **Files/folders:** `app/models/soap_note.py`
- **Database changes:** New `soap_notes` table (id, session_id FK, status enum, created_at, last_edited_at) and `soap_sections` table (id, soap_note_id FK, section_type enum, content).
- **API endpoints:** None yet (added in 3.3).
- **Dependencies:** none new
- **Testing:** A `SOAPNote` cannot be created without exactly four `SOAPSection` rows — enforce this at the service layer, not just by convention.
- **Completion checklist:**
  - [ ] Schema enforces exactly 4 sections per note (checked in a service-level test, not just assumed)
  - [ ] `status` defaults to `DRAFT`

### Module 3.3 — SOAP Draft Generation API + Validation
- **Objective:** Wire 3.1 and 3.2 together behind a real endpoint, with the SRS's 100%-completeness guarantee enforced.
- **Why now:** Completes UC-07 end-to-end.
- **Features:** Trigger-generation endpoint; retrieval endpoint; explicit validation step that blocks a malformed draft from ever being stored.
- **Files/folders:** `app/api/v1/endpoints/soap_notes.py`
- **Database changes:** None beyond 3.2.
- **API endpoints:** `POST /api/v1/sessions/{id}/soap-notes/generate`, `GET /api/v1/sessions/{id}/soap-notes`
- **Dependencies:** none new
- **Testing:** SOAPNote created with exactly 4 sections on success (TC-07 pass criteria, verbatim); generation failure returns transcript-with-error state, not a silent empty note.
- **Completion checklist:**
  - [ ] "SOAP structure must contain all four headings" holds true in **100%** of generated drafts, verified by test — this is a hard NFR, not a nice-to-have
  - [ ] Generation failure path shows transcript + explicit error, per UC-07's alternate flow
  - [ ] Tests pass, mapped to TC-07

---

## PHASE 4 — ICD-10/CPT Code Suggestion Engine

*Maps to Sprint 4. Covers UC-08 and FR-04.*

### Module 4.1 — Code Reference Data & Semantic Matching Setup

> **Note:** If Module 3.1 was built with the hybrid extraction approach (see revision note there), a ClinicalBERT engine wrapper already exists at `app/ml/clinicalbert_engine.py`. Reuse and extend it here rather than integrating ClinicalBERT from scratch — this module only needs to add the ICD-10/CPT reference corpus and semantic similarity search on top of the existing engine.
> 
> **Revision note (Option B - NumPy Pivot):** Given ~30 reference codes, a pgvector index provides no real benefit at this scale — consistent with the minimalism rule already applied to Celery/Redis and scipy earlier in this project. The pgvector requirement is dropped in favor of loading the reference codes from the DB into memory on startup and performing cosine similarity via standard NumPy.

- **Objective:** Load a reference set of ICD-10/CPT codes with descriptions and embeddings so suggestions can be matched semantically, not just by keyword.
- **Why now:** You need a corpus to match against before you can generate any suggestions at all.
- **Features:** A seed script that loads a (subset) ICD-10/CPT reference dataset into Postgres with `pgvector` embeddings (generated via the existing ClinicalBERT engine); a lookup/similarity service.
- **Files/folders:** `app/ml/clinicalbert_engine.py`, `scripts/seed_codes.py`
- **Database changes:** New `code_reference` table (code, description, code_type enum `ICD10`/`CPT`, embedding vector column via `pgvector`).
- **API endpoints:** None (internal reference data).
- **Dependencies:** `pgvector`, `transformers`, `torch` (shared with 3.1)
- **Testing:** Seed script populates a non-trivial reference set; a similarity query against a sample clinical phrase returns plausible candidate codes.
- **Completion checklist:**
  - [ ] Reference table populated and embeddings generated
  - [ ] Similarity search returns ranked candidates for a test phrase
  - [ ] Seed script is repeatable/idempotent

### Module 4.2 — CodeSuggestion Service & Data Model
- **Objective:** Generate a ranked list of ICD-10/CPT suggestions from transcript/SOAP content and persist them, linked to the SOAP note.
- **Why now:** Directly implements UC-08, right after SOAP drafts exist to analyze.
- **Features:** Ranking service using ClinicalBERT-based similarity against the reference set; minimum-3-suggestions guarantee when clinical evidence exists (per NFR §2.3.3 Accuracy).
- **Files/folders:** `app/services/code_suggester.py`, `app/models/code_suggestion.py`
- **Database changes:** New `code_suggestions` table (id, soap_note_id FK, code, description, code_type, rank, confidence_score, accepted boolean default false).
- **API endpoints:** None yet (added in 4.3).
- **Dependencies:** none new
- **Testing:** Given a sample SOAP note with clear clinical content, ≥3 relevant suggestions are returned and ranked consistently.
- **Completion checklist:**
  - [ ] ≥1 suggestion always stored when generation runs successfully (TC-08 minimum)
  - [ ] Ranking field exists and ordering is consistent across repeated runs on the same input
  - [ ] Suggestions correctly linked to their SOAPNote

### Module 4.3 — Code Suggestion API
- **Objective:** Expose suggestions for doctor review, and support accept/remove actions the doctor takes during review (Phase 5 will call this).
- **Why now:** Closes UC-08 end-to-end.
- **Features:** Trigger + retrieval endpoints; failure path that still shows the SOAP draft without suggestions rather than blocking review entirely (per UC-08 alternate flow).
- **Files/folders:** `app/api/v1/endpoints/code_suggestions.py`
- **Database changes:** None beyond 4.2.
- **API endpoints:** `POST /api/v1/soap-notes/{id}/code-suggestions/generate`, `GET /api/v1/soap-notes/{id}/code-suggestions`
- **Dependencies:** none new
- **Testing:** Suggestions visible in the API response; suggestion-generation failure doesn't block viewing the SOAP draft.
- **Completion checklist:**
  - [ ] Suggestions stored and visible via the endpoint (TC-08 pass criteria)
  - [ ] Failure path degrades gracefully, per UC-08 alternate flow
  - [ ] Tests pass, mapped to TC-08

---

## PHASE 5 — Doctor Review, Edit, Approve & Sign Workflow

*Maps to Sprint 5. Covers UC-03, UC-04 and FR-05, FR-06.*

### Module 5.1 — Review & Edit API
- **Objective:** Let the doctor edit any SOAP section and persist the change, per UC-03.
- **Why now:** Now that drafts and suggestions exist, the doctor needs a way to correct them before signing — this is the "human in the loop" your abstract promises.
- **Features:** Edit endpoint scoped to individual `SOAPSection`s; `last_edited_at` timestamp bump; validation that editing is blocked once a note is `SIGNED` (enforced properly in 5.2, but the guard belongs here too, defensively).
- **Files/folders:** `app/api/v1/endpoints/soap_notes.py` (extend), `app/services/soap_generator.py` (extend)
- **Database changes:** None beyond 3.2 (uses existing `last_edited_at`).
- **API endpoints:** `PATCH /api/v1/soap-notes/{id}/sections/{section_id}`
- **Dependencies:** none new
- **Testing:** Edit persists and reloads correctly; edits to a `SIGNED` note are rejected; save failure retains the original draft for retry (per UC-03 alternate flow).
- **Completion checklist:**
  - [ ] Edited content persists and survives reload
  - [ ] `last_edited_at` updates correctly
  - [ ] Edits on signed notes are rejected with a clear error
  - [ ] Tests pass, mapped to TC-03

### Module 5.2 — Signature Model & Approve/Sign Endpoint
- **Objective:** Doctor approves and signs; note becomes immutable; triggers Phase 6's sync.
- **Why now:** This is the finalization gate of the entire workflow — every earlier module exists to feed this one.
- **Features:** `Signature` model (simple confirmation for the prototype, structured so a real digital-signature mechanism could replace it later, per SDD §3.5.4's noted design flexibility); sign endpoint that locks the note and kicks off EMR sync (Phase 6).
- **Files/folders:** `app/models/signature.py`, `app/services/note_finalizer.py`, `app/api/v1/endpoints/signatures.py`
- **Database changes:** New `signatures` table (id, soap_note_id FK, doctor_id FK, signed_at, method).
- **API endpoints:** `POST /api/v1/soap-notes/{id}/sign`
- **Dependencies:** none new
- **Testing:** Signing creates a `Signature`, sets `SOAPNote.status = SIGNED`, and any subsequent edit attempt is blocked; cancellation before confirmation leaves the note editable.
- **Completion checklist:**
  - [ ] Signature record created and correctly linked
  - [ ] `SOAPNote.status` becomes `SIGNED` and edits are then blocked (verified by test, not assumption)
  - [ ] Signing triggers the sync flow from Phase 6 (can be a stub call for now if Phase 6 isn't built yet — wire the real call once it is)
  - [ ] Tests pass, mapped to TC-04

**⚠️ Manual review required:** confirm the sign action can't be triggered twice, and that locked notes are genuinely immutable at the service layer, not just in the UI.

---

## PHASE 6 — EMR Synchronization

*Maps to Sprint 6 (part 1). Covers UC-09 and FR-07.*

### Module 6.1 — Simulated EMR Service
- **Objective:** A standalone mock EMR endpoint/database that can receive and store finalized notes, demonstrating interoperability per your abstract.
- **Why now:** You need a receiving system before you can build the client that syncs to it.
- **Features:** A minimal separate FastAPI app (or a clearly separated router) backed by the `simulated_emr` database from Module 0.2; accepts a signed-note payload and stores it.
- **Files/folders:** `simulated_emr_service/` (own `main.py`, `models.py`, `endpoints.py`)
- **Database changes:** New `simulated_emr_records` table in the `simulated_emr` database (id, source_session_id, source_soap_note_id, payload JSON, received_at).
- **API endpoints:** `POST /simulated-emr/records` (on the simulated service)
- **Dependencies:** none new (reuses FastAPI/SQLAlchemy)
- **Testing:** Posting a well-formed payload persists a record; malformed payload rejected with a 4xx.
- **Completion checklist:**
  - [ ] Runs independently of the main app (own process/port, even if same repo)
  - [ ] Persists received records correctly
  - [ ] Clearly documented as a stand-in for a real EMR/EHR — not something the frontend should treat as production

### Module 6.2 — EMR Sync Client
- **Objective:** On signing, send the note to the simulated EMR endpoint and track `syncStatus` (`SUCCESS`/`FAILED`/`PENDING`).
- **Why now:** Closes UC-09 — the last step of the core clinical workflow.
- **Features:** HTTP client call to the simulated EMR; status tracking on the `SOAPNote` (or a dedicated sync-status field); retry/backoff behavior on failure, with the note remaining safely stored locally regardless of sync outcome (per UC-09's alternate flow and TC-10).
- **Files/folders:** `app/services/emr_sync_client.py`, `app/api/v1/endpoints/emr_sync.py`
- **Database changes:** Add `sync_status` enum column (`PENDING`/`SUCCESS`/`FAILED`) to `soap_notes`.
- **API endpoints:** `GET /api/v1/soap-notes/{id}/sync-status` (for the doctor to check)
- **Dependencies:** `httpx`
- **Testing:** Success path sets `SUCCESS` and creates the simulated EMR record (TC-09); forced-failure path sets `FAILED`/`PENDING`, shows failure feedback, and the signed note still exists locally (TC-10).
- **Completion checklist:**
  - [ ] `syncStatus` visible and accurate via the endpoint
  - [ ] Success path fully verified against TC-09
  - [ ] Failure path fully verified against TC-10 — system does not crash and does not falsely report success
  - [ ] Tests pass, mapped to TC-09 and TC-10

---

## PHASE 7 — Retention Enforcement & Data Lifecycle

*Completes Sprint 6 (part 2) and closes out UC-05/FR-08 fully.*

### Module 7.1 — Automated Retention/Cleanup Job
- **Objective:** Actually delete temporary artifacts (raw audio, intermediate files) once a note is signed and synced, within the SRS's ≤5-minute window — while permanently keeping the signed SOAP note.
- **Why now:** Phase 1.4 built the tracking scaffolding; now that signing (Phase 5) and sync (Phase 6) exist, the trigger condition is real and this can be finished.
- **Features:** A scheduled job (Celery beat or APScheduler) that scans for artifacts flagged eligible and past the retention window, deletes the underlying files and metadata, and logs what was removed for auditability.
- **Files/folders:** `app/services/retention_service.py` (completed), `app/workers/retention_worker.py`
- **Database changes:** Add `deleted_at` timestamps where not already present (from 1.4).
- **API endpoints:** None (background job); optionally an admin/debug endpoint to trigger a manual sweep in dev.
- **Dependencies:** `celery` + `redis`, or `apscheduler` if you're keeping infrastructure lighter
- **Testing:** Simulate a session that's signed + synced, fast-forward past the retention window (mock the clock, don't actually sleep 5 minutes in tests), confirm temp data is gone and the signed SOAPNote + Signature remain.
- **Completion checklist:**
  - [ ] Temp artifacts removed within the retention window after sign+sync (TC-05 pass criteria)
  - [ ] Signed SOAP notes and signatures are never touched by this job
  - [ ] Deletions are logged for auditability
  - [ ] Tests pass, mapped to TC-05

---

## PHASE 8 — Security, Reliability & Performance Hardening

*Cross-cutting — implements the Non-Functional Requirements from SRS §2.3.3 that don't belong to any single use case.*

### Module 8.1 — Security Hardening
- **Objective:** Every requirement in SRS §2.3.3 Security is actually enforced, not just assumed.
- **Why now:** Do this once the core workflow exists and there's real traffic/data flow to secure — but before anything resembling a demo goes anywhere near a network you don't control.
- **Features:** Enforce HTTPS/TLS at the deployment layer (reverse proxy or ASGI server config); encrypt sensitive fields at rest (transcript text, SOAP content) using `cryptography`; run `bandit` and `pip-audit` in CI; verify no secrets are logged.
- **Files/folders:** `app/core/security.py` (extend), `docker/nginx.conf` or equivalent TLS termination config
- **Database changes:** Possibly migrate sensitive text columns to encrypted storage (`pgcrypto` or application-level encryption).
- **API endpoints:** None new — this hardens existing ones.
- **Dependencies:** `cryptography`, `bandit`, `pip-audit`
- **Testing:** `bandit`/`pip-audit` run clean (or documented exceptions); a test confirming plaintext clinical text never appears unencrypted in the raw DB row.
- **Completion checklist:**
  - [ ] All client-server traffic is HTTPS-only in any deployed environment
  - [ ] Clinical data encrypted at rest
  - [ ] No secrets appear in logs or version control
  - [ ] Security scans run clean

**⚠️ Manual review required in full — this is the module where a rubber-stamped agent review is not acceptable.**

### Module 8.2 — Error Handling, Resilience & Observability
- **Objective:** Meet the Robustness NFRs: errors surfaced within ≤5 seconds with retry available, ≥95% successful processing rate across test runs.
- **Why now:** Once the full pipeline exists, failure modes across all stages (ASR, NLP, sync) need consistent handling — better to standardize now than patch each endpoint differently later.
- **Features:** A global exception-handling middleware with consistent error response shapes; timeouts on all ML inference and external HTTP calls; structured logging for failure diagnosis; a lightweight metrics counter for success/failure rate per pipeline stage.
- **Files/folders:** `app/core/error_handlers.py`, `app/core/logging.py` (extend)
- **Database changes:** Optional: a `processing_events` table for auditing pipeline successes/failures.
- **API endpoints:** None new.
- **Dependencies:** none required, though `prometheus-client` is a reasonable optional addition if you want real metrics later.
- **Testing:** Simulated ASR/NLP timeouts return an error within the 5-second budget; a batch of test runs across the pipeline is measured against the 95% success target.
- **Completion checklist:**
  - [ ] Every pipeline stage has an explicit timeout
  - [ ] Failures return within ≤5 seconds with a retry option surfaced to the caller
  - [ ] Measured success rate across your test dataset meets or exceeds 95%

### Module 8.3 — Performance & Concurrency
- **Objective:** Meet the Efficiency/Scalability NFRs: SOAP draft ready in ≤15s for a 10-minute audio (≤25s under concurrent load), and the system supports ≥10 concurrent doctor sessions without failure.
- **Why now:** Only measurable once the full pipeline (Phases 2–6) exists — this is a tuning pass, not a from-scratch build.
- **Features:** Move ASR/NLP inference into background workers (Celery) so the API stays responsive under load; connection pooling tuned for concurrent DB access; a simple load test script.
- **Files/folders:** `app/workers/` (ASR/SOAP/code-suggestion tasks), `scripts/load_test.py`
- **Database changes:** None structural — possibly connection pool config.
- **API endpoints:** None new — existing generation endpoints become async-triggered (return a job/status reference immediately, poll or push for completion).
- **Dependencies:** `celery`, `redis`
- **Testing:** A load test simulating 10 concurrent sessions confirms no failures and SOAP generation stays within the 25-second concurrent-load target.
- **Completion checklist:**
  - [ ] SOAP draft generation meets ≤15s (single session) and ≤25s (10 concurrent sessions) for 10-minute audio
  - [ ] System handles 10 concurrent sessions without failure, verified by load test
  - [ ] API remains responsive (non-blocking) during heavy ML inference

---

## PHASE 9 — Testing, QA & API Documentation

*Formalizes your STD chapter across the whole backend.*

### Module 9.1 — Full pytest Suite Mapped to TC-01…TC-10
- **Objective:** One coherent, CI-runnable test suite covering every test case in your STD, not just the ad-hoc tests written module-by-module. Diarization accuracy specifically should be measured against a batch of real (or realistically simulated, two-speaker) mock consultation recordings — see the deferred decision noted in Module 2.2.
- **Why now:** Consolidate and catch any gaps now that every use case has a working implementation.
- **Features:** Organize `tests/unit/` and `tests/integration/` so each TC-ID maps to a named test function; shared fixtures for authenticated doctor, sample session, sample audio.
- **Files/folders:** `tests/unit/`, `tests/integration/`, `tests/conftest.py`
- **Database changes:** A dedicated test database, isolated from dev/prod.
- **API endpoints:** None new.
- **Dependencies:** `pytest`, `pytest-asyncio`, `httpx`, `factory-boy`/`Faker`
- **Testing:** (this module is testing) — the suite itself must be green end-to-end, including every TC-01 through TC-10 scenario.
- **Completion checklist:**
  - [ ] TC-01 through TC-10 all have a corresponding, passing automated test
  - [ ] Test database never touches dev/prod data
  - [ ] Suite runs in under a few minutes so it's actually usable in CI

### Module 9.2 — Postman Collection
- **Objective:** A shareable, manually runnable Postman collection covering every endpoint, per STD §4.2.3's stated tooling.
- **Why now:** Useful both for your own manual verification and as a deliverable your supervisor/committee can run directly.
- **Features:** One request per endpoint, organized by workflow order (register → login → start recording → … → sync); environment variables for base URL and JWT.
- **Files/folders:** `docs/postman_collection.json`
- **Database changes:** None.
- **API endpoints:** None new — documents existing ones.
- **Dependencies:** none (Postman itself, external tool)
- **Testing:** Manually run the full collection top to bottom against a clean environment and confirm it completes without manual intervention.
- **Completion checklist:**
  - [ ] Collection covers every endpoint built so far
  - [ ] Full run-through works against a fresh environment
  - [ ] Exported and committed to the repo

### Module 9.3 — OpenAPI Docs + README
- **Objective:** A polished, accurate API reference and project README — this is the contract the future .NET MAUI/Blazor frontend will build against.
- **Why now:** Do this once the backend's endpoint surface is stable, right before declaring the backend "done."
- **Features:** Clean docstrings/response models so FastAPI's auto-generated OpenAPI docs are actually useful; a README covering setup, running locally, running tests, and architecture overview (with a link back to your SDD).
- **Files/folders:** `README.md`, docstrings across `app/api/v1/endpoints/`
- **Database changes:** None.
- **API endpoints:** None new.
- **Dependencies:** none new
- **Testing:** N/A (documentation) — but verify the `/docs` Swagger UI renders correctly with no missing descriptions.
- **Completion checklist:**
  - [ ] Every endpoint has a clear summary, request/response schema, and example in Swagger
  - [ ] README lets a new developer get the backend running from a clean clone in under 15 minutes

---

## PHASE 10 — Deployment Readiness

*Final phase — backend hand-off point, before frontend work begins.*

### Module 10.1 — Containerization
- **Objective:** The full backend (main app + simulated EMR service + Postgres + Redis) runs via `docker-compose up`.
- **Why now:** Locks in reproducibility before you move to frontend work or share the project with your supervisor for review.
- **Files/folders:** `Dockerfile`, `docker/`, `docker-compose.yml`
- **Database changes:** None (containerizes existing Postgres).
- **API endpoints:** None new.
- **Dependencies:** Docker, docker-compose
- **Testing:** Fresh `docker-compose up` from a clean checkout brings up a fully working stack; run the Module 9.1 suite against it.
- **Completion checklist:**
  - [ ] `docker-compose up` brings up app + simulated EMR + Postgres + Redis correctly
  - [ ] Test suite passes against the containerized stack

### Module 10.2 — Basic CI Pipeline
- **Objective:** Every push runs lint, type-check, and the full test suite automatically.
- **Why now:** Cheap insurance against regressions as you move into frontend integration.
- **Files/folders:** `.github/workflows/backend-ci.yml`
- **Dependencies:** GitHub Actions (no local install)
- **Testing:** CI itself — confirm a broken test actually fails the pipeline, and a clean commit passes.
- **Completion checklist:**
  - [ ] Lint (`ruff`/`black --check`), type-check (`mypy`), and `pytest` all run on every push
  - [ ] A deliberately broken test correctly fails the pipeline

### Module 10.3 — Environment Configuration & Secrets
- **Objective:** Clean separation of dev/staging/prod config, with no secrets in version control.
- **Files/folders:** `.env.example` (finalized), deployment-specific env files kept out of Git via `.gitignore`
- **Dependencies:** none new
- **Testing:** Confirm `.env` is gitignored; confirm the app fails fast and clearly if a required secret is missing in a given environment.
- **Completion checklist:**
  - [ ] No real secrets committed anywhere in Git history
  - [ ] Missing required config fails loudly at startup, not silently at runtime

### Module 10.4 — Final Backend Review & Frontend Handoff Package
- **Objective:** A frozen, documented API contract ready for the .NET MAUI/Blazor team (future-you) to build against.
- **Features:** Final pass confirming every NFR target in SRS §2.3.3 is met and evidenced; exported OpenAPI spec; a short handoff note summarizing what's implemented vs. what remains simulated (EMR integration) for future work.
- **Files/folders:** `docs/openapi.json` (exported snapshot), `docs/HANDOFF.md`
- **Completion checklist — this is your backend's Definition of Done:**
  - [ ] All 9 use cases (UC-01–UC-09) implemented and tested
  - [ ] All 8 functional requirements (FR-01–FR-08) satisfied
  - [ ] All 10 STD test cases (TC-01–TC-10) automated and passing
  - [ ] NFR targets met and evidenced: ASR ≥85% WAcc, diarization ≥85% accuracy, SOAP 100% four-section completeness, ≥3 code suggestions when evidence exists, ≤15s/≤25s SOAP generation, 10 concurrent sessions, ≥95% success rate, ≤5s error surfacing, ≤5min post-sign-and-sync retention
  - [ ] Security hardening (Module 8.1) fully reviewed manually, not just agent-approved
  - [ ] `docker-compose up` produces a fully working stack from a clean clone
  - [ ] OpenAPI spec exported and frozen as the frontend's integration contract

---

*Backend complete. Only after every box above is checked should frontend work (.NET MAUI / Blazor) begin, per your stated plan.*
