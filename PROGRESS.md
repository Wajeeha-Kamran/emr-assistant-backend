# Backend progress log

**State as of 17 August 2026.** Phases 0 to 9 are complete. Phase 10 is partly
done: 10.4 finished, 10.1 partial, 10.3 mostly done, 10.2 deferred on purpose.
All ten STD test cases are green and the working tree is clean at `60e2879`.

This file is the build log. It records what was done, in what order, and why —
including the approaches that were tried and abandoned, because those are usually
the more useful half. If you are picking this project up, read this alongside
`README.md` (setup and how the system works) and the `docs/module_*.md` write-ups
(the measurements behind every number quoted here).

**Still to do:** finish Phase 10 (Dockerfile, CI, restrict CORS), and the two
remaining screens in the mobile client.


## PHASE 0 — Environment and core bootstrap
- [x] Module 0.1 — FastAPI app skeleton and config management
- [x] Module 0.2 — Database connectivity (two logical schemas)
- [x] Module 0.3 — Doctor authentication and authorization

## PHASE 1 — Consultation session and audio capture
- [x] Module 1.1 — ConsultationSession domain model and lifecycle
- [x] Module 1.2 — Start recording endpoint (UC-01)
- [x] Module 1.3 — Stop recording and audio handler (UC-02, FR-01)
- [x] Module 1.4 — Temporary storage and retention policy skeleton (UC-05, FR-08)

## PHASE 2 — ASR and two-role speaker separation
- [x] Module 2.1 — Whisper ASR integration
- [x] Module 2.2 — Two-role diarization (doctor / patient)
- [x] Module 2.3 — Transcript and TranscriptSegment persistence, finalization API
- [x] Module 2.4 — Riva-ready abstraction layer

## PHASE 3 — SOAP note draft generation
- [x] Module 3.1 — BioGPT integration service. Revised during the module to
      extractive-only via ClinicalBERT; BioGPT is retained in the codebase but is
      not on the critical path.
- [x] Module 3.2 — SOAPNote and SOAPSection data model
- [x] Module 3.3 — SOAP draft generation API and validation

## PHASE 4 — ICD-10 / CPT code suggestion engine
- [x] Module 4.1 — Code reference data and semantic matching setup
- [x] Module 4.2 — CodeSuggestion service and data model
- [x] Module 4.3 — Code suggestion API

## PHASE 5 — Doctor review, edit, approve and sign
- [x] Module 5.1 — Review and edit API
- [x] Module 5.2 — Signature model and approve/sign endpoint
- [x] Gap closure (UC-08) — code suggestions made reviewable and editable. UC-08
      requires accept and reject, so a read-only ranked list did not satisfy it.

## PHASE 6 — EMR synchronization
- [x] Module 6.1 — Simulated EMR service
- [x] Module 6.2 — EMR sync client

## PHASE 7 — Retention enforcement and data lifecycle
- [x] Module 7.1 — Automated retention and cleanup job

## PHASE 8 — Security, reliability and performance
- [x] Module 8.1 — Security hardening
  - Encryption at rest for clinical text (SQLAlchemy TypeDecorator plus Fernet)
  - TLS termination config for deployment (docker/nginx.conf)
  - bandit and pip-audit integrated; two exceptions documented with reasoning
- [x] Module 8.2 — Error handling, resilience and observability
  - Timeout wrappers and fast failure so errors surface rather than hang
  - Lightweight success/failure metrics
  - 95%+ success rate validated against test runs
- [x] Module 8.3 — Performance and concurrency
  - Concurrency requirement MET, 10 of 10 sessions, after fixing a Whisper thread
    safety fault. Inference is now serialised on a lock.
  - Timing requirement NOT met on CPU, roughly 72s against a 15s target. This was
    measured rather than assumed. Celery with Redis was evaluated and rejected on
    the evidence: the cost is CPU time, so moving the work to a queue changes
    where it happens and not how long it takes.
  - Full write-up: `docs/module_8_3_performance.md`

## Module 3 revisited — SOAP classification quality (16 Aug 2026)
- [x] Measured with `scripts/evaluate_soap.py` against 73 labelled doctor
      sentences in `docs/evidence/soap_expected.md`, plus a 56-sentence held-out
      set in `docs/evidence/soap_heldout.md`.

                          baseline   stage 1   stage 2
        clinical accuracy    74.4%     71.8%     97.4%
        noise rate          100.0%      0.0%      0.0%
        Assessment            0/5       1/5       5/5
        Plan                 14/19     14/19     19/19

      Held-out set, unseen clinical scenarios: 38/38, 0% noise.

      - Stage 1: sentence-level classification, filtering of questions,
        announcements and pleasantries, anchors rebalanced to six per category.
        This solved the noise problem but Assessment stayed broken, which proved
        that tuning anchors was not the answer.
      - Stage 2: speech-act cues. Embeddings classify by topic, but diagnosing,
        measuring and instructing are speech acts that topic similarity cannot
        tell apart. The fix is a hybrid — rules where the language is explicit,
        embeddings where it is not.
      - The held-out set exists to catch rules fitted to the reference scripts. It
        scores above the reference set, so they are not narrowly fitted. Caveat:
        the same author wrote both the cues and the held-out sentences, so this
        tests generalisation across clinical scenarios but not across phrasing
        styles.
      - One error remains and was left there deliberately: "You can bear weight,
        just about." classified as Plan. Writing a rule for a single visible
        failure is exactly the fitting this section guards against.
      - Full write-up: `docs/module_3_soap_classification.md`

## PHASE 9 — Testing, QA and API documentation
- [x] Module 9.1 — Full pytest suite mapped to TC-01 to TC-10
  - [x] Part A — tests reorganised to TC-01 to TC-10 with a dedicated test DB
        - 107 passed, 0 failed (15 Aug 2026). 90 tests mapped across TC-01 to
          TC-10, all green, plus 17 supporting tests covering auth, NFRs and
          infrastructure. The suite has grown since; the last recorded run was
          148 passing.
        - Tests run against `emr_assistant_test`, created and seeded
          automatically. A guard refuses any database not ending in `_test`. This
          also fixed tests failing whenever the app was running.
        - `pytest.ini` restricts collection to `tests/`. Before that, ten files in
          `scratch/` matching `test_*.py` were being collected.
        - The suite prints an STD traceability table at the end of every run, so
          the evidence is generated rather than transcribed by hand.
        - Full write-up: `docs/traceability.md`
        - KNOWN GAP: `tests/integration/test_diarization.py` calls
          `diarize_segments()` without an audio path, so it exercises the
          deprecated pause heuristic rather than pyannote. Accuracy is measured
          properly by `scripts/evaluate_accuracy.py`, but these five tests should
          use a short fixture recording.
  - [x] Part B — ASR and speaker accuracy measured against the 85% NFR
        - ASR word accuracy MET in every condition measured:
            distinct voices 86.4%, similar voices 92.1%, synthetic 95.3%
          (target 85%, numerals excluded)
        - Speaker accuracy measured under three conditions:
            similar voices (siblings)        35.9%  — 1 of 4 scripts met
            distinct voices (F doctor / M pt) 77.6%  — 3 of 4 scripts met
            synthetic control                99.9%  — 4 of 4 scripts met
          The mean on the primary distinct-voice condition does not meet 85%, but
          three of the four consultations scored 97.5% or above. The single
          failure is script 2, recorded deliberately as a rapid exchange with
          almost no gap between turns. Voice similarity and rapid turn taking are
          the limiting factors, not the implementation.
        - Speaker separation was rebuilt three times before pyannote: pause
          heuristic, then per-segment voice fingerprints, then sliding-window
          fingerprints. Speaker naming moved from "first word wins" to a
          question-count majority vote.
        - Full write-up: `docs/module_9_1_accuracy.md`
  - [x] Part B follow-up — all four scripts re-recorded with a female doctor and a
        male patient, in `docs/evidence/human_distinct/`. Done 15 Aug 2026.
- [x] Module 9.2 — Postman collection
  - All 19 requests run against a live server, 15 Aug 2026. The full workflow was
    verified end to end: register, login, session, record, transcribe, SOAP, edit,
    codes, sign, sync, retention sweep.
  - This found three defects the automated suite could not, because the suite
    calls the app in process and the collection went over HTTP:
      1. `audio/wave` rejected on upload, which affects Windows clients including
         the .NET MAUI app
      2. transcript segments returned in arbitrary order
      3. `finalized_at` not cleared on transcript retry
  - Runbook and findings: `docs/module_9_2_postman_runbook.md`
  - It also raised the SOAP classification problem that became the Module 3
    revisit above: one 30 second segment contained examination, diagnosis and plan
    and all of it landed in Objective, Assessment came back empty, and a greeting
    landed in Plan. Measured, then fixed in two stages.
- [x] Module 9.3 — OpenAPI docs and README
  - `README.md` covers setup, the three gated Hugging Face licences pyannote
    needs, running both services, the test suite and its per-test-case markers,
    the measurement scripts, the architecture and the measured limitations.
  - Every endpoint is documented. FastAPI renders function docstrings into
    `/docs`, so the descriptions cover what an integrator needs to know:
    transcription is asynchronous and must be polled, ownership failures return
    404 rather than 403, signing is irreversible, and the SOAP note is a draft.

## PHASE 10 — Deployment readiness
- [ ] Module 10.1 — Containerisation
  - PARTIAL (16 Aug 2026). Docker is not installed on the development machine and
    installing it would have cost a day, so `run_backend.ps1` was written instead.
    One command starts the API and the simulated EMR, waits until `/health`
    actually answers rather than assuming it started, and prints the addresses for
    this machine, the Android emulator and a phone on the LAN.
  - It binds `0.0.0.0` rather than `127.0.0.1`, which is required for a phone or
    emulator to reach the API at all. The default binding is unreachable from
    anything but the host.
  - Still outstanding: a real Dockerfile and a compose file bringing up PostgreSQL
    alongside both services. The script covers the development need; it does not
    make the system portable.
- [ ] Module 10.2 — Basic CI pipeline
  - Not started, deferred deliberately. It unblocks nothing, and it is easier to
    write once a Dockerfile exists because CI can reuse it.
- [ ] Module 10.3 — Environment configuration and secrets
  - The urgent item is DONE: the Hugging Face token was rotated after appearing in
    a screenshot.
  - Verified 16 Aug 2026 that no secret has ever been committed. `.env` is absent
    from the whole git history and the old hardcoded database password does not
    appear in any commit. The GitHub push is clean.
  - DEFERRED WITH REASON, not forgotten: rotating `ENCRYPTION_KEY` invalidates
    every Fernet-encrypted row in the development database. On a local machine
    holding synthetic data that is cost without benefit. Rotate it together with
    the database password and the JWT secret at deployment, once.
  - Still outstanding: restrict CORS from `allow_origins=["*"]` to the client's
    real origin.
- [x] Module 10.4 — Final backend review and frontend handoff package
  - `docs/openapi.json` exported by `scripts/export_openapi.py`. 19 paths, 19
    operations, 23 schemas, no undocumented operations.
  - The export caught a defect that the test suite, the live Postman run and code
    review had all missed: `/health` was defined twice in `app/main.py`, producing
    a duplicate operation ID and an invalid contract. The behaviour was correct
    because both definitions were identical, which is precisely why nothing else
    found it. Removed.
  - The backend review this module calls for was carried out across Modules 9.1 to
    9.3 and the live API run rather than as a separate exercise.

## Work after Phase 9 (16–17 Aug 2026)
Not in the original roadmap. Each of these came out of building the mobile client
and finding something the backend could not support.

- [x] **Recovering consultations that did not finish** (`9485df6`)
  - `GET /api/v1/attention` lists every consultation stuck at any stage, with the
    action that would clear it, plus `POST /soap-notes/{id}/retry-sync`.
  - The reason this matters is not convenience. Audio is only deleted once its
    note is signed AND synced, so a consultation that fails midway keeps its
    recording on disk indefinitely — and no endpoint listed a doctor's sessions,
    so there was no way to reach it from the app. This is a data protection
    measure.
  - Also fixed a trap found while writing it: a transcript left in `processing`
    blocked its own retry forever, because the concurrency guard had no time
    bound. The guard now reuses the ASR service's own timeout budget.
- [x] **Registration validation and case-insensitive email** (`c325f30`)
  - Without this, one person could register twice with the same address in
    different cases and end up with two accounts whose consultations were
    invisible to each other. Enforced by a unique index on the lowercased value in
    the database, not only in application code.
- [x] **Line endings normalised** (`e288e1e`)
  - `.gitattributes` added and `scratch/` untracked. Before this, 36 files across
    the two repositories showed as modified with no content change, which buries
    real edits.
- [x] **Discarding an abandoned consultation** (`2028ca4`)
  - New `DISCARDED` session state, endpoint and migration. A consultation started
    and then backed out of would otherwise sit in `RECORDING` permanently and its
    audio would never become eligible for deletion. `STOPPED` deliberately cannot
    be discarded — by then the audio is uploaded and the work belongs to the
    recovery path instead.
- [x] **Setup instructions and repository hygiene** (`0922a60`, `60e2879`)
  - The README's environment table named `SECRET_KEY` where `config.py` requires
    `JWT_SECRET`, and left out `APP_ENV` entirely. Anyone following the README
    would have hit a startup failure before the API served a single request.
  - `.env.example` gained `HF_TOKEN` and `AUDIO_STORAGE_DIR`. Missing `HF_TOKEN`
    produces the most misleading failure in the project, because the API starts
    and the upload succeeds and only transcription fails.
  - Eleven scratch recordings committed to the repository root were untracked. The
    one that two scripts actually use was moved to
    `docs/evidence/pipeline_clip.wav` with identical bytes, so the measurements
    those scripts produce are unaffected.
  - The README's note about secrets was corrected: it still described the Hugging
    Face token as needing rotation after it had already been rotated.

## Open work
- [ ] Fix `tests/integration/test_diarization.py` to exercise the real path. It
      calls `diarize_segments()` without an audio path, which selects the
      deprecated pause heuristic, so five tests pass while testing code that was
      proven not to work. It needs a short fixture recording.
- [ ] BioGPT design-comparison script (`scripts/soap_pipeline_comparison.py`), to
      produce a figure showing raw / hybrid / extractive output side by side.
- [ ] Restrict CORS before deployment (Module 10.3).
- [ ] Dockerfile and compose file (Module 10.1), then CI (Module 10.2).
- [ ] Set `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` once the models are
      cached, so that the absence of any external processing can be demonstrated
      by disconnecting the machine rather than only described.
- [ ] Optional: one GPU measurement, for example on Google Colab, to evidence that
      the efficiency target is hardware-bound rather than design-bound.

## Notes on entries that were stale
Two entries in earlier versions of this file were wrong and are recorded here
rather than quietly deleted. CORS was listed as outstanding work when it was
already configured (as `"*"`, which still needs restricting). ASR word accuracy
was listed as unmeasured after it had been measured in Module 9.1 Part B. A log
that corrects itself in public is worth more than one that looks tidy.
