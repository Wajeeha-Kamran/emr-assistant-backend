# EMR Assistant Backend Progress

**State as of 16 August 2026.** Phases 0–9 complete. Phase 10 not started.
107 tests passing, all ten STD test cases green. Working tree clean.

**Next up:** Phase 10 (Docker, CI, secrets, handoff package), then the .NET MAUI
frontend. Full context for a cold start: `claude/EMR-Assistant-Backend-Handover.pdf`
in the Claude project, or the `docs/module_*.md` write-ups in this repo.


## PHASE 0 — Environment & Core Bootstrap
- [x] Module 0.1 — FastAPI App Skeleton & Config Management
- [x] Module 0.2 — Database Connectivity (Two Logical Schemas)
- [x] Module 0.3 — Doctor Authentication & Authorization

## PHASE 1 — Consultation Session & Audio Capture
- [x] Module 1.1 — ConsultationSession Domain Model & Lifecycle
- [x] Module 1.2 — Start Recording Endpoint (UC-01)
- [x] Module 1.3 — Stop Recording + Audio Handler (UC-02, FR-01)
- [x] Module 1.4 — Temporary Storage & Retention Policy Skeleton (UC-05, FR-08)

## PHASE 2 — ASR & Two-Role Diarization Pipeline
- [x] Module 2.1 — Whisper ASR Integration
- [x] Module 2.2 — Two-Role Diarization (Doctor/Patient)
- [x] Module 2.3 — Transcript & TranscriptSegment Persistence + Finalization API
- [x] Module 2.4 — Riva-Ready Abstraction Layer

## PHASE 3 — SOAP Note Draft Generation
- [x] Module 3.1 — BioGPT Integration Service (revised: extractive-only via ClinicalBERT, BioGPT retained but not in critical path)
- [x] Module 3.2 — SOAPNote & SOAPSection Data Model
- [x] Module 3.3 — SOAP Draft Generation API + Validation

## PHASE 4 — ICD-10/CPT Code Suggestion Engine
- [x] Module 4.1 — Code Reference Data & Semantic Matching Setup
- [x] Module 4.2 — CodeSuggestion Service & Data Model
- [x] Module 4.3 — Code Suggestion API

## PHASE 5 — Doctor Review, Edit, Approve & Sign Workflow
- [x] Module 5.1 — Review & Edit API
- [x] Module 5.2 — Signature Model & Approve/Sign Endpoint
- [x] Gap Closure (UC-08) — Reviewable and Editable Code Suggestions

## PHASE 6 — EMR Synchronization
- [x] Module 6.1 — Simulated EMR Service
- [x] Module 6.2 — EMR Sync Client

## PHASE 7 — Retention Enforcement & Data Lifecycle
- [x] Module 7.1 — Automated Retention/Cleanup Job

## PHASE 8 — Security, Reliability & Performance Hardening
- [x] Module 8.1 — Security Hardening
  - Encryption at rest for clinical text (SQLAlchemy TypeDecorator + Fernet)
  - TLS termination config for deployment (docker/nginx.conf)
  - bandit + pip-audit integrated; two exceptions documented with reasoning
- [x] **Module 8.2:** Error Handling, Resilience & Observability
  - Implement robust error surfacing (timeout wrappers, fast failure)
  - Light-weight metrics telemetry (success/failure rates)
  - Validate 95%+ success rate against test runs
- [x] Module 8.3 — Performance & Concurrency
  - Concurrency requirement MET (10/10 sessions) after fixing a Whisper
    thread-safety fault; inference now serialised on a lock
  - Timing requirements NOT met on CPU (~72s vs 15s target); measured, not
    assumed. Celery/Redis evaluated and rejected on evidence.
  - Full write-up: docs/module_8_3_performance.md

## Module 3 revisit — SOAP classification quality (16 Aug 2026)
- [x] Measured with scripts/evaluate_soap.py against 73 labelled doctor
      sentences in docs/evidence/soap_expected.md, plus a 56-sentence
      held-out set in docs/evidence/soap_heldout.md

                          baseline   stage 1   stage 2
        clinical accuracy    74.4%     71.8%     97.4%
        noise rate          100.0%      0.0%      0.0%
        Assessment            0/5       1/5       5/5
        Plan                 14/19     14/19     19/19

      Held-out set (unseen clinical scenarios): 38/38, 0% noise.

      - Stage 1: sentence-level classification, filtering of questions /
        announcements / pleasantries, anchors rebalanced to six per
        category. Solved noise; Assessment stayed broken, which proved
        anchor tuning was not the answer.
      - Stage 2: speech-act cues. Embeddings classify by topic; diagnosing,
        measuring and instructing are speech acts that topic similarity
        cannot separate. Hybrid: rules where the language is explicit,
        embeddings where it is not.
      - The held-out set exists to detect rules fitted to the reference
        scripts. It scores ABOVE the reference set, so they are not
        narrowly fitted. CAVEAT: the same author wrote both the cues and
        the held-out sentences, so it tests generalisation across clinical
        scenarios but not across phrasing styles.
      - One error remains and was deliberately left: "You can bear weight,
        just about." -> Plan. Writing a rule for a single visible failure
        is the fitting this whole section guards against.
      Full write-up: docs/module_3_soap_classification.md

## PHASE 9 — Testing, QA & API Documentation
- [x] Module 9.1 — Full pytest Suite Mapped to TC-01…TC-10
  - [x] Part A — tests reorganised to TC-01…TC-10 with a dedicated test DB
        - 107 passed, 0 failed (15 Aug 2026). 90 tests mapped across
          TC-01…TC-10, all green; 17 supporting (auth, NFRs, infrastructure)
        - Tests now run against emr_assistant_test, created and seeded
          automatically. Guard refuses any database not ending in "_test".
          Fixes tests failing while the app is running.
        - pytest.ini restricts collection to tests/. scratch/ contained ten
          files matching test_*.py that were previously being collected.
        - The suite prints an STD traceability table at the end of every run,
          so the evidence is generated rather than transcribed.
        - Full write-up: docs/traceability.md
        - KNOWN GAP: tests/integration/test_diarization.py calls
          diarize_segments() without an audio path, so it exercises the
          deprecated pause heuristic rather than pyannote. Accuracy is
          measured properly by scripts/evaluate_accuracy.py, but these tests
          should use a short fixture recording. See docs/traceability.md.
  - [x] Part B — ASR and diarization accuracy measured against the 85% NFR
        - ASR word accuracy — MET under every condition measured:
            similar voices 92.1%, distinct voices 86.4%, synthetic 95.3%
          (target 85%, numeral-excluded figure)
        - Diarization measured under three conditions:
            similar voices (siblings)        35.9%  — 1 of 4 scripts met
            distinct voices (F doctor/M pt)  77.6%  — 3 of 4 scripts met
            synthetic control                99.9%  — 4 of 4 scripts met
          Mean on the primary (distinct-voice) condition does not meet the 85%
          target, but three of four consultations scored 97.5%+. The single
          failure is script 2, deliberately recorded as a rapid exchange with
          almost no gap between turns. Voice similarity and rapid turn-taking
          are established as the limiting factors; the implementation is not.
        - Diarization rebuilt: pause heuristic -> per-segment fingerprints ->
          sliding-window fingerprints -> pyannote.audio. Speaker naming moved
          from "first word wins" to a question-count majority vote.
        - Full write-up: docs/module_9_1_accuracy.md
  - [x] Part B follow-up — all four scripts re-recorded with a female doctor
        and male patient, in docs/evidence/human_distinct/. Done 15 Aug 2026.
- [x] Module 9.2 — Postman Collection
  - All 19 requests run against a live server, 15 Aug 2026. Full workflow
    verified end to end: register -> login -> session -> record -> transcribe
    -> SOAP -> edit -> codes -> sign -> sync -> retention sweep.
  - Found and fixed three defects the automated suite could not catch:
      1. audio/wave rejected on upload (Windows clients, incl. .NET MAUI)
      2. transcript segments returned in arbitrary order
      3. finalized_at not cleared on transcript retry
  - Runbook and findings: docs/module_9_2_postman_runbook.md
  - FINDING FOR MODULE 3 — RAISED HERE, NOW FIXED. SOAP classification of
    doctor speech into Objective/Assessment/Plan was poor: one 30s segment
    held examination + diagnosis + plan and all of it landed in Objective,
    Assessment came back empty, and a greeting landed in Plan. Measured,
    then fixed in two stages — see "Module 3 revisit" above. Clinical
    accuracy 74.4% -> 97.4%, noise 100% -> 0%, Assessment 0/5 -> 5/5.
- [x] Module 9.3 — OpenAPI Docs + README
  - README.md written: setup, the three gated Hugging Face licences pyannote
    needs, running both services, the test suite and its per-test-case
    markers, the measurement scripts, architecture, and measured limitations.
  - Every endpoint documented. FastAPI renders function docstrings into
    /docs, so the descriptions cover what an integrator needs: transcription
    is asynchronous and must be polled, ownership failures return 404 rather
    than 403, signing is irreversible, the SOAP note is a draft for review.
  - API description with the intended call order, plus descriptions for all
    eight endpoint groups.

## PHASE 10 — Deployment Readiness
- [ ] Module 10.1 — Containerization
- [ ] Module 10.2 — Basic CI Pipeline
- [ ] Module 10.3 — Environment Configuration & Secrets
- [ ] Module 10.4 — Final Backend Review & Frontend Handoff Package

## Additional tasks (not in the original roadmap)
- [x] CORS configuration — already present in app/main.py with
      allow_origins=["*"]. Confirmed 16 Aug 2026; this entry was stale.
      NOTE for Module 10.3: "*" is a development setting. Restrict to the
      frontend's real origin before deployment.
- [ ] Fix tests/integration/test_diarization.py to exercise the real path.
      It calls diarize_segments() without an audio path, which selects the
      deprecated pause heuristic, so five tests pass while testing code that
      was proven not to work. Needs a short fixture recording. Noted inline
      under Module 9.1 Part A; listed here so it is visible as open work.
- [ ] BioGPT design-comparison script (scripts/soap_pipeline_comparison.py) —
      produces a report figure showing raw / hybrid / extractive output
- [x] ASR word-accuracy measurement vs the 85% NFR — done in Module 9.1
      Part B (15–16 Aug 2026). This entry was stale.
- [ ] Optional: single GPU measurement (e.g. Google Colab) to evidence that the
      efficiency targets are hardware-bound rather than design-bound
