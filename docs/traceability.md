# STD Traceability — TC-01 … TC-10

Generated from a full test run on 15 August 2026: **107 passed, 0 failed.**

Reproduce with:

```
.\.venv\Scripts\python.exe -m pytest -q
```

The suite prints the table below at the end of every run. It is produced from
the run itself rather than transcribed by hand, so it cannot quietly go out of
date: if a mapped test is renamed or deleted, collection fails with a message
naming it, and if a test is added without being mapped, collection also fails.

---

## Results

| Test case | Description | Use case | Functional req. | Tests passed |
|---|---|---|---|---|
| TC-01 | Start Recording | UC-01 | FR-01 | 6 / 6 |
| TC-02 | Stop Recording + Audio Saved | UC-02 | FR-01 | 5 / 5 |
| TC-03 | Edit Draft Saved | UC-03 | FR-05 | 6 / 6 |
| TC-04 | Note Signed and Locked | UC-04 | FR-06 | 7 / 7 |
| TC-05 | Temporary Storage + Retention Policy | UC-05 | FR-08 | 10 / 10 |
| TC-06 | Diarized Transcript Generated | UC-06 | FR-02 | 12 / 12 |
| TC-07 | SOAP Draft Generated | UC-07 | FR-03 | 18 / 18 |
| TC-08 | Code Suggestions Displayed (Ranked) | UC-08 | FR-04 | 17 / 17 |
| TC-09 | Sync Success Update Status | UC-09 | FR-07 | 6 / 6 |
| TC-10 | Sync Failure Handling | UC-09 | FR-07 | 3 / 3 |
| | **Mapped total** | | | **90 / 90** |
| | Supporting (authentication, NFRs, infrastructure) | | | 17 |
| | **Suite total** | | | **107** |

Run a single test case's tests with its marker, for example:

```
.\.venv\Scripts\python.exe -m pytest -m tc06 -q
```

---

## Which tests cover which test case

| Test case | Test files |
|---|---|
| TC-01 | `tests/integration/test_sessions.py` |
| TC-02 | `tests/integration/test_audio.py` |
| TC-03 | `tests/integration/test_soap_notes_api.py` (the `test_edit_section_*` tests) |
| TC-04 | `tests/integration/test_signatures_api.py`, plus `test_soap_notes.py::test_prevent_signed_note_overwrite` |
| TC-05 | `tests/integration/test_retention.py`, `tests/integration/test_retention_worker.py` |
| TC-06 | `tests/integration/test_asr.py`, `test_diarization.py`, `test_transcripts.py` |
| TC-07 | `tests/integration/test_soap_draft.py`, plus the draft and retrieval tests in `test_soap_notes.py` and `test_soap_notes_api.py` |
| TC-08 | `tests/integration/test_code_suggestions.py`, `test_code_suggestions_api.py` |
| TC-09 | The success-path tests in `test_emr_sync.py` and `test_simulated_emr.py` |
| TC-10 | The failure-path tests in `test_emr_sync.py` and `test_simulated_emr.py` |
| Supporting | `test_auth.py` (authentication underpins every case), `test_encryption.py` (NFR — encryption at rest), `test_timeouts.py` (NFR — timeout behaviour), `tests/unit/` (infrastructure) |

The mapping itself lives in one table in `tests/conftest.py`, not as decorators
spread across 21 files, so the whole matrix can be read and checked in one place.

---

## Test isolation

The suite runs against a **separate database**, named by appending `_test` to the
configured `DATABASE_URL`. It is created automatically on first run and its
reference codes are seeded automatically.

This replaced a scheme that ran against the development database and cleaned up
by deleting rows belonging to a hard-coded list of test email addresses. That
scheme meant tests failed whenever the application was running, every new test
needed its email added to a list, and a forgotten entry left rows behind that
broke later runs.

Emptying tables is destructive, so it is fenced three ways:

1. The database URL is rewritten before the application is imported, so the app
   cannot have opened the development database in the test process.
2. A guard refuses to run unless the database name ends in `_test`, and is
   re-checked immediately before every truncation.
3. `code_reference` is never truncated.

---

## Known gap, recorded rather than hidden

`tests/integration/test_diarization.py` calls `diarize_segments(segments)` without
an audio path. That argument selects voice-based diarization; without it the
service falls back to the deprecated pause heuristic. So those five tests pass
while exercising the code path that Module 9.1 Part B proved does not work.

This is the same blind spot that allowed the original defect — every segment
labelled DOCTOR, and consequently an empty SOAP Subjective section — to survive a
green test suite. TC-06 asserted only that a speaker role was not null, which is
true of a transcript that is 100% wrong.

Accuracy is measured separately and properly by `scripts/evaluate_accuracy.py`
against real recordings (see `docs/module_9_1_accuracy.md`), so the requirement is
verified. But the unit-level tests should exercise the real path with a short
fixture audio file. Recorded here as outstanding work rather than left as a
silently misleading filename.
