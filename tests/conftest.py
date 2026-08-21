"""
Test fixtures and TC-01…TC-10 traceability.

TWO THINGS CHANGED HERE IN MODULE 9.1 PART A.

1. TESTS NOW RUN AGAINST A DEDICATED DATABASE.

   Previously the suite ran against the development database and cleaned up by
   deleting rows belonging to a hard-coded list of test email addresses. That
   had three problems:

     - tests failed whenever the application was running, because the app and
       the suite were competing for the same rows;
     - every new test needed its email adding to a list in this file, and
       forgetting meant leaked rows that broke later runs;
     - a test could in principle damage real development data.

   The suite now points at a separate database, named by appending "_test" to
   whatever DATABASE_URL is configured. It is created automatically if absent.
   Between tests every table is emptied, so no cleanup list is needed and no
   test can inherit another's state.

   SAFETY. Emptying tables is destructive, so it is fenced three ways:
     - the URL is rewritten before the application is imported, so the app can
       never have opened the development database in this process;
     - _assert_test_database() refuses to proceed unless the database name ends
       in "_test", and is called again immediately before every truncation;
     - code_reference is never truncated. It holds the seeded ICD-10/CPT
       reference data, which every TC-08 test depends on.

2. EVERY TEST IS TAGGED WITH THE STD TEST CASE IT SUPPORTS.

   The mapping lives in TRACEABILITY below rather than as decorators scattered
   across 21 files, so the whole traceability matrix can be read in one place
   and cannot drift silently: if a mapped test is renamed or deleted, collection
   fails with a message naming it.

   Run one test case's tests with, for example:  pytest -m tc06
"""

import os
import re
import sys
from typing import Dict, List, Tuple
from urllib.parse import urlparse, urlunparse

import pytest

# ---------------------------------------------------------------------------
# Redirect to the test database BEFORE anything imports the application.
# app.db.session builds its engine at import time from settings.DATABASE_URL,
# and pydantic-settings gives environment variables priority over .env, so this
# assignment decides which database the whole process talks to.
# ---------------------------------------------------------------------------

def _test_database_url() -> str:
    from dotenv import dotenv_values

    raw = os.environ.get("DATABASE_URL") or dotenv_values(".env").get("DATABASE_URL")
    if not raw:
        sys.exit(
            "FATAL: DATABASE_URL is not set in the environment or in .env, so the "
            "test database name cannot be derived."
        )

    parsed = urlparse(raw)
    name = parsed.path.lstrip("/")
    if not name:
        sys.exit(f"FATAL: DATABASE_URL has no database name: {raw}")
    if name.endswith("_test"):
        return raw
    return urlunparse(parsed._replace(path=f"/{name}_test"))


os.environ["DATABASE_URL"] = _test_database_url()

from app.core.config import settings  # noqa: E402  (must follow the line above)


def _assert_test_database() -> str:
    """Return the database name, refusing anything that is not a test database."""
    name = urlparse(settings.DATABASE_URL).path.lstrip("/")
    if not name.endswith("_test"):
        pytest.exit(
            f"REFUSING TO RUN: the suite is pointed at '{name}', which is not a "
            "test database. Tests empty tables between runs and this guard exists "
            "to make sure that can never happen to development data.",
            returncode=1,
        )
    return name


_assert_test_database()

from sqlalchemy import create_engine, text  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.db.base  # noqa: E402,F401  registers Base before models are imported
from app.db.base import Base  # noqa: E402
from app.db.session import engine  # noqa: E402

# Importing every model module is what populates Base.metadata. Missing one
# would silently create an incomplete schema.
from app.models import (  # noqa: E402,F401
    audio, code_reference, code_suggestion, doctor, session as session_model,
    signature, soap_note, transcript,
)

# Never emptied between tests: seeded reference data, and Alembic's bookkeeping.
PRESERVED_TABLES = {"code_reference", "alembic_version"}


# ---------------------------------------------------------------------------
# Database lifecycle
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def _test_database():
    """Create the test database and schema once per run."""
    db_name = _assert_test_database()

    # CREATE DATABASE cannot run inside a transaction or against the database
    # being created, so this connects to the server's default database instead.
    admin_url = urlunparse(urlparse(settings.DATABASE_URL)._replace(path="/postgres"))
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": db_name}
        ).scalar()
        if not exists:
            # Creation only. Nothing here drops or overwrites an existing database.
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))
            print(f"\nCreated test database '{db_name}'.")
    admin.dispose()

    Base.metadata.create_all(bind=engine)

    # create_all only creates tables that are missing entirely. A column added
    # to a table that already exists is never applied, so the test database
    # falls behind the models and every test touching that table dies with
    # UndefinedColumn — which reads as broken code rather than a stale schema.
    # That has now cost a full run twice. Repairing it here means an ordinary
    # `pytest` is enough; scripts/migrate_test_db.py does the same from the
    # command line when you want to see what changed without running the suite.
    from scripts.migrate_test_db import sync_schema

    added = sync_schema(engine, Base.metadata)
    if added:
        print("\nTest database was behind the models. Added:")
        for label in added:
            print(f"  {label}")

    # Reference codes are seeded automatically. TC-08's tests assert against
    # specific ICD-10/CPT codes, so an empty code_reference table would fail
    # them for a reason that has nothing to do with the code under test.
    #
    # This is cheap: the table holds 30 plain rows (code, description, type).
    # No embeddings are stored — ClinicalBERT computes them at query time — so
    # there is no model to load here and nothing worth caching between runs.
    from app.models.code_reference import CodeReference
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        seeded = db.query(CodeReference).count()
    finally:
        db.close()

    if seeded == 0:
        try:
            from scripts.seed_codes import seed_codes
            seed_codes()
        except Exception as e:  # pragma: no cover - setup diagnostics
            print(
                f"\nWARNING: could not seed reference codes ({type(e).__name__}: {e}).\n"
                "         TC-08 tests will fail until this is resolved. Try:\n"
                "             .\\.venv\\Scripts\\python.exe -m scripts.seed_test_codes\n"
            )

    yield


@pytest.fixture(autouse=True)
def _clean_tables():
    """
    Empty every table except the preserved ones, before and after each test.

    Replaces the old per-email cleanup: no list to maintain, and a test cannot
    inherit rows left behind by another.
    """
    def _truncate():
        _assert_test_database()  # re-checked immediately before the destructive call
        targets = [
            t.name for t in reversed(Base.metadata.sorted_tables)
            if t.name not in PRESERVED_TABLES
        ]
        if not targets:
            return
        quoted = ", ".join(f'"{t}"' for t in targets)
        with engine.connect() as conn:
            conn.execute(text(f"TRUNCATE {quoted} RESTART IDENTITY CASCADE"))
            conn.commit()

    _truncate()
    yield
    _truncate()


@pytest.fixture(scope="module")
def client():
    with TestClient(app_instance()) as c:
        yield c


def app_instance():
    from app.main import app
    return app


# ---------------------------------------------------------------------------
# Audio storage isolation (unchanged behaviour, kept from the original file)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def configure_test_storage():
    import shutil

    original = settings.AUDIO_STORAGE_DIR
    test_storage = "./storage/test_audio"
    settings.AUDIO_STORAGE_DIR = test_storage

    if os.path.exists(test_storage):
        shutil.rmtree(test_storage)
    os.makedirs(test_storage, exist_ok=True)

    yield

    if os.path.exists(test_storage):
        shutil.rmtree(test_storage)
    settings.AUDIO_STORAGE_DIR = original


# ---------------------------------------------------------------------------
# STD traceability — TC-01 … TC-10
# ---------------------------------------------------------------------------
# Each entry is (test case title, [node patterns]). A pattern ending in ".py"
# claims the whole file; otherwise it names a single test.

TRACEABILITY: Dict[str, Tuple[str, List[str]]] = {
    "tc01": ("Start Recording", [
        "integration/test_sessions.py",
    ]),
    "tc02": ("Stop Recording + Audio Saved", [
        "integration/test_audio.py",
    ]),
    "tc03": ("Edit Draft Saved", [
        "integration/test_soap_notes_api.py::test_edit_section_success",
        "integration/test_soap_notes_api.py::test_edit_section_signed_rejected",
        "integration/test_soap_notes_api.py::test_edit_section_ownership_denied",
        "integration/test_soap_notes_api.py::test_edit_section_mismatched_ids",
        "integration/test_soap_notes_api.py::test_edit_section_unauthenticated",
        "integration/test_soap_notes_api.py::test_edit_section_empty_content",
    ]),
    "tc04": ("Note Signed and Locked", [
        "integration/test_signatures_api.py",
        "integration/test_soap_notes.py::test_prevent_signed_note_overwrite",
    ]),
    "tc05": ("Temporary Storage + Retention Policy", [
        "integration/test_retention.py",
        "integration/test_retention_worker.py",
    ]),
    "tc06": ("Diarized Transcript Generated", [
        "integration/test_asr.py",
        "integration/test_diarization.py",
        "integration/test_transcripts.py",
    ]),
    "tc07": ("SOAP Draft Generated", [
        "integration/test_soap_draft.py",
        "integration/test_soap_notes.py::test_generate_and_save_draft_setup",
        "integration/test_soap_notes.py::test_generate_in_background_success",
        "integration/test_soap_notes.py::test_ownership_check",
        "integration/test_soap_notes.py::test_enforce_four_sections",
        "integration/test_soap_notes.py::test_prevent_signed_note_overwrite",
        "integration/test_soap_notes_api.py::test_generate_draft_success",
        "integration/test_soap_notes_api.py::test_generate_draft_already_signed",
        "integration/test_soap_notes_api.py::test_generate_draft_transcript_not_ready",
        "integration/test_soap_notes_api.py::test_generate_draft_unauthorized",
        "integration/test_soap_notes_api.py::test_get_soap_note_success",
        "integration/test_soap_notes_api.py::test_get_soap_note_not_found",
        "integration/test_soap_notes_api.py::test_get_soap_note_unauthorized",
        "integration/test_soap_notes_api.py::test_retry_generation",
    ]),
    "tc08": ("Code Suggestions Displayed (Ranked)", [
        "integration/test_code_suggestions.py",
        "integration/test_code_suggestions_api.py",
    ]),
    "tc09": ("Sync Success Update Status", [
        "integration/test_emr_sync.py::test_contract_validation",
        "integration/test_emr_sync.py::test_fractional_duration_type_guard",
        "integration/test_emr_sync.py::test_sync_success_tc09",
        "integration/test_emr_sync.py::test_get_sync_status_api",
        "integration/test_simulated_emr.py::test_receive_record_success",
        "integration/test_simulated_emr.py::test_receive_record_different_timestamps",
    ]),
    "tc10": ("Sync Failure Handling", [
        "integration/test_emr_sync.py::test_sync_forced_failure_tc10",
        "integration/test_emr_sync.py::test_sync_4xx_fail_fast",
        "integration/test_emr_sync.py::test_retry_sync_requeues_a_failed_note",
        "integration/test_emr_sync.py::test_retry_sync_rejects_a_successful_note",
        "integration/test_emr_sync.py::test_retry_sync_rejects_a_pending_note",
        "integration/test_emr_sync.py::test_retry_sync_rejects_an_unsigned_note",
        "integration/test_emr_sync.py::test_retry_sync_denies_another_doctors_note",
        "integration/test_emr_sync.py::test_retry_sync_requires_authentication",
        "integration/test_simulated_emr.py::test_receive_record_malformed",
    ]),
}

# Tests that support no single STD test case. These verify non-functional
# requirements and infrastructure. Listed explicitly rather than left untagged,
# so "untagged" always means "someone forgot", not "deliberately excluded".
SUPPORTING: Dict[str, Tuple[str, List[str]]] = {
    "auth": ("Authentication (underpins every test case)", [
        "integration/test_auth.py",
    ]),
    "nfr_security": ("NFR — encryption at rest", [
        "integration/test_encryption.py",
    ]),
    "nfr_reliability": ("NFR — timeout behaviour", [
        "integration/test_timeouts.py",
    ]),
    "recovery": ("Recovery of incomplete consultations — added beyond the original STD", [
        "integration/test_attention.py",
    ]),
    "infra": ("Infrastructure and configuration", [
        "unit/test_db.py",
        "unit/test_main.py",
        "unit/test_engine_factory.py",
    ]),
}


def _matches(nodeid: str, pattern: str) -> bool:
    normalised = nodeid.replace("\\", "/")
    if pattern.endswith(".py"):
        return pattern in normalised
    path, _, test_name = pattern.partition("::")
    return path in normalised and re.search(rf"::{re.escape(test_name)}(\[|$)", normalised) is not None


def pytest_configure(config):
    for marker, (title, _) in {**TRACEABILITY, **SUPPORTING}.items():
        config.addinivalue_line("markers", f"{marker}: {title}")


def pytest_collection_modifyitems(config, items):
    unmatched: List[str] = []

    for marker, (_, patterns) in {**TRACEABILITY, **SUPPORTING}.items():
        for pattern in patterns:
            hits = [i for i in items if _matches(i.nodeid, pattern)]
            if not hits:
                unmatched.append(f"{marker}: {pattern}")
            for item in hits:
                item.add_marker(getattr(pytest.mark, marker))

    if unmatched:
        # Loud on purpose. A silently stale traceability matrix is worse than no
        # matrix, because it looks like evidence while claiming coverage that
        # does not exist.
        raise pytest.UsageError(
            "Traceability entries in tests/conftest.py match no collected test "
            "(renamed or deleted?):\n  " + "\n  ".join(unmatched)
        )

    untagged = [
        i.nodeid for i in items
        if not any(m.name in {**TRACEABILITY, **SUPPORTING} for m in i.iter_markers())
    ]
    if untagged:
        raise pytest.UsageError(
            "These tests are not mapped to an STD test case or listed as "
            "supporting. Add them to TRACEABILITY or SUPPORTING in "
            "tests/conftest.py:\n  " + "\n  ".join(untagged)
        )


# ---------------------------------------------------------------------------
# Per-test-case summary
# ---------------------------------------------------------------------------

_OUTCOMES: Dict[str, str] = {}


def pytest_runtest_logreport(report):
    """Record the worst outcome seen for each test across all phases."""
    if report.when == "call" or (report.when == "setup" and report.outcome != "passed"):
        previous = _OUTCOMES.get(report.nodeid)
        if previous != "failed":
            _OUTCOMES[report.nodeid] = report.outcome


def pytest_terminal_summary(terminalreporter):
    """
    Print an STD traceability table at the end of every run.

    This exists so the traceability evidence is generated by the test suite
    itself rather than transcribed by hand into a report. A hand-copied table
    is a claim; this is a result. If a test case has no passing tests, that is
    visible here rather than buried in a list of 107 dots.
    """
    items = getattr(terminalreporter, "_session", None)
    if items is None:
        return

    rows = []
    for marker, (title, _) in TRACEABILITY.items():
        matched = [
            nodeid for nodeid, _ in _OUTCOMES.items()
            if any(
                _matches(nodeid, pattern)
                for pattern in TRACEABILITY[marker][1]
            )
        ]
        passed = sum(1 for n in matched if _OUTCOMES[n] == "passed")
        total = len(matched)
        rows.append((marker.upper().replace("TC", "TC-"), title, passed, total))

    if not rows:
        return

    terminalreporter.write_sep("=", "STD TEST CASE TRACEABILITY")
    terminalreporter.write_line(f"{'Test case':<10}{'Description':<40}{'Passed':>10}")
    for tc, title, passed, total in rows:
        status = "" if passed == total else "   <-- INCOMPLETE"
        terminalreporter.write_line(
            f"{tc:<10}{title:<40}{f'{passed}/{total}':>10}{status}"
        )

    supporting = sum(
        1 for nodeid, outcome in _OUTCOMES.items()
        if outcome == "passed" and not any(
            _matches(nodeid, pat)
            for _, patterns in TRACEABILITY.values() for pat in patterns
        )
    )
    terminalreporter.write_line("")
    terminalreporter.write_line(
        f"{'':<10}{'Supporting (auth, NFR, infrastructure)':<40}{supporting:>10}"
    )
