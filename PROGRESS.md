# EMR Assistant Backend Progress

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

## PHASE 9 — Testing, QA & API Documentation
- [ ] Module 9.1 — Full pytest Suite Mapped to TC-01…TC-10
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
        - ASR word accuracy 92.1% on human recordings — MET
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
- [ ] Module 9.2 — Postman Collection
- [ ] Module 9.3 — OpenAPI Docs + README

## PHASE 10 — Deployment Readiness
- [ ] Module 10.1 — Containerization
- [ ] Module 10.2 — Basic CI Pipeline
- [ ] Module 10.3 — Environment Configuration & Secrets
- [ ] Module 10.4 — Final Backend Review & Frontend Handoff Package

## Additional tasks (not in the original roadmap)
- [ ] CORS configuration — required before the Blazor web frontend; not needed
      for the .NET MAUI mobile app
- [ ] BioGPT design-comparison script (scripts/soap_pipeline_comparison.py) —
      produces a report figure showing raw / hybrid / extractive output
- [ ] ASR word-accuracy measurement vs the 85% NFR — never measured
- [ ] Optional: single GPU measurement (e.g. Google Colab) to evidence that the
      efficiency targets are hardware-bound rather than design-bound
