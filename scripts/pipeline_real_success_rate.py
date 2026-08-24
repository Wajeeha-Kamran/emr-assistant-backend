"""Robustness measurement for the 95% successful-processing requirement.

The SRS wording is specific and this script is written to satisfy it exactly:

    "The system should have a minimum processing rate of 95% of successful
     processing on the evaluation dataset for atleast 3 test runs."

Two things follow from that sentence.

  * "on the evaluation dataset" - the four scripted consultations in
    docs/evidence, not a one-second clip. A one-second clip gives pyannote
    nothing to diarize, so every iteration falls through to the deprecated
    pause heuristic and the run measures the fallback path rather than the
    pipeline.

  * "for atleast 3 test runs" - three separate executions. This script is one
    run. Pass the run number on the command line and it records each run to
    its own file, then prints all runs found so far.

Usage:
    python -m scripts.pipeline_real_success_rate 1
    python -m scripts.pipeline_real_success_rate 2
    python -m scripts.pipeline_real_success_rate 3

Nothing is mocked. Real Whisper, real pyannote, real ClinicalBERT.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from io import BytesIO

from fastapi.testclient import TestClient

from app.main import app

# The evaluation dataset. Iterations rotate through these so every run covers
# all four, rather than measuring one recording ten times.
CLIPS = ["consult_1.wav", "consult_2.wav", "consult_3.wav", "consult_4.wav"]
EVIDENCE_DIR = "docs/evidence"
RESULTS_DIR = "docs/evidence/robustness"

ITERATIONS = 10

# A real consultation is 30-50 seconds of audio and this may be running on CPU
# with no GPU, so transcription takes far longer than it did on the one-second
# clip. This is a ceiling, not an expectation.
TRANSCRIPT_TIMEOUT_S = 600.0
GENERATION_TIMEOUT_S = 120.0


def main():
    run_number = sys.argv[1] if len(sys.argv) > 1 else "1"

    client = TestClient(app)
    client.post("/api/v1/auth/register", json={
        "email": "pipeline_real@example.com",
        "full_name": "Pipeline Real",
        "password": "pwd",
    })
    login = client.post("/api/v1/auth/login", data={
        "username": "pipeline_real@example.com", "password": "pwd"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    # Load every clip once.
    audio = {}
    for name in CLIPS:
        path = os.path.join(EVIDENCE_DIR, name)
        try:
            with open(path, "rb") as f:
                audio[name] = f.read()
        except FileNotFoundError:
            print(f"ERROR: {path} not found.")
            return

    stage_successes = {
        "session_create": 0,
        "start_recording": 0,
        "stop_recording": 0,
        "transcript_complete": 0,
        "soap_generation": 0,
        "code_suggestion": 0,
        "emr_sync": 0,
        "retention": 0,
    }
    pipeline_successes = 0
    per_iteration = []

    def wait_for(field, session_id, timeout_s=GENERATION_TIMEOUT_S):
        """Poll the note until `field` leaves "processing".

        Both generation stages became asynchronous in c027a07: each returns 202
        and the model runs in a background task, so the response no longer
        carries the result. A stage is complete when its status column reads
        "completed". 200/201 are still accepted so this script also works
        against a pre-c027a07 build, where a missing status field means the work
        was done inline before the call returned.
        """
        waited = 0.0
        while waited < timeout_s:
            r = client.get(f"/api/v1/sessions/{session_id}/soap-notes", headers=headers)
            if r.status_code == 200:
                state = r.json().get(field, "completed")
                if state in ("completed", None):
                    return True, r.json()
                if state == "failed":
                    return False, r.json()
            time.sleep(0.5)
            waited += 0.5
        return False, None

    def retention_holds(session_id):
        """Verify the audio was actually deleted, rather than assuming it.

        The previous version of this script incremented the retention counter
        unconditionally once sync succeeded, so that stage always read 10/10
        whatever happened on disk. This reads the row and the filesystem.

        The retention window is forced to zero for the sweep so the check does
        not have to wait it out. That means this measures *that* the audio is
        deleted after sync, not that it happens within the five-minute window -
        the timing requirement is separate and is not measured here.
        """
        from app.core.config import settings
        from app.db.session import SessionLocal
        from app.models.audio import AudioMetadata
        from app.workers.retention_worker import RetentionWorker

        db = SessionLocal()
        try:
            row = db.query(AudioMetadata).filter(
                AudioMetadata.session_id == session_id).first()
            if row is None:
                return False, "no audio row"
            path_before = row.file_path
        finally:
            db.close()

        original = settings.RETENTION_WINDOW_MINUTES
        settings.RETENTION_WINDOW_MINUTES = 0
        try:
            RetentionWorker.run_cleanup()
        finally:
            settings.RETENTION_WINDOW_MINUTES = original

        db = SessionLocal()
        try:
            row = db.query(AudioMetadata).filter(
                AudioMetadata.session_id == session_id).first()
            if row is None:
                return False, "audio row vanished"
            if row.file_path is not None:
                return False, "file_path still set"
            if row.deleted_at is None:
                return False, "deleted_at not stamped"
        finally:
            db.close()

        if path_before and os.path.exists(path_before):
            return False, f"file still on disk: {path_before}"
        return True, None

    print(f"Robustness run {run_number} - {ITERATIONS} iterations over "
          f"{len(CLIPS)} consultations, real models, nothing mocked.\n")

    for i in range(ITERATIONS):
        clip = CLIPS[i % len(CLIPS)]
        started = time.time()
        outcome = {"iteration": i + 1, "clip": clip, "result": "FAILED", "failed_at": None}
        try:
            # 1. Create session
            resp = client.post("/api/v1/sessions/", headers=headers)
            if resp.status_code != 201:
                outcome["failed_at"] = f"session_create {resp.status_code}"
                per_iteration.append(outcome)
                print(f"  {i+1:2}/{ITERATIONS} {clip:<15} FAILED at session_create")
                continue
            session_id = resp.json()["id"]
            stage_successes["session_create"] += 1

            # 2. Start recording
            resp = client.post(f"/api/v1/sessions/{session_id}/start-recording", headers=headers)
            if resp.status_code not in (200, 202):
                outcome["failed_at"] = f"start_recording {resp.status_code}"
                per_iteration.append(outcome)
                print(f"  {i+1:2}/{ITERATIONS} {clip:<15} FAILED at start_recording")
                continue
            stage_successes["start_recording"] += 1

            # 3. Stop recording and upload
            files = {"file": (clip, BytesIO(audio[clip]), "audio/wav")}
            resp = client.post(f"/api/v1/sessions/{session_id}/stop-recording",
                               headers=headers, files=files)
            if resp.status_code not in (200, 202):
                outcome["failed_at"] = f"stop_recording {resp.status_code}"
                per_iteration.append(outcome)
                print(f"  {i+1:2}/{ITERATIONS} {clip:<15} FAILED at stop_recording")
                continue
            stage_successes["stop_recording"] += 1

            # 4. Transcription
            transcript_ready = False
            transcript_has_segments = False
            waited = 0.0
            while waited < TRANSCRIPT_TIMEOUT_S:
                time.sleep(2)
                waited += 2
                t = client.get(f"/api/v1/sessions/{session_id}/transcript", headers=headers)
                if t.status_code != 200:
                    continue
                status = t.json().get("status")
                if status == "completed":
                    segments = t.json().get("segments", [])
                    transcript_has_segments = (
                        len(segments) > 0
                        and any(s.get("speaker_role") for s in segments))
                    transcript_ready = True
                    break
                if status == "failed":
                    break

            if not (transcript_ready and transcript_has_segments):
                outcome["failed_at"] = "transcript"
                per_iteration.append(outcome)
                print(f"  {i+1:2}/{ITERATIONS} {clip:<15} FAILED at transcript")
                continue
            stage_successes["transcript_complete"] += 1

            # 5. SOAP draft
            resp = client.post(f"/api/v1/sessions/{session_id}/soap-notes/generate",
                               headers=headers)
            if resp.status_code not in (200, 201, 202):
                outcome["failed_at"] = f"soap_generate {resp.status_code}"
                per_iteration.append(outcome)
                print(f"  {i+1:2}/{ITERATIONS} {clip:<15} FAILED at soap_generate")
                continue
            note_id = resp.json()["id"]

            ok, body = wait_for("generation_status", session_id)
            if not ok:
                outcome["failed_at"] = f"soap: {(body or {}).get('generation_error')}"
                per_iteration.append(outcome)
                print(f"  {i+1:2}/{ITERATIONS} {clip:<15} FAILED at soap_generation")
                continue
            stage_successes["soap_generation"] += 1

            # 6. Code suggestion. An empty list is a completed run, not a
            # failure: a note with nothing codable in Assessment and Plan
            # legitimately has no codes, so the status is what decides.
            c = client.post(f"/api/v1/soap-notes/{note_id}/code-suggestions/generate",
                            headers=headers)
            if c.status_code not in (200, 201, 202):
                outcome["failed_at"] = f"code_generate {c.status_code}"
                per_iteration.append(outcome)
                print(f"  {i+1:2}/{ITERATIONS} {clip:<15} FAILED at code_generate")
                continue

            ok, body = wait_for("codes_generation_status", session_id)
            if not ok:
                outcome["failed_at"] = f"codes: {(body or {}).get('codes_generation_error')}"
                per_iteration.append(outcome)
                print(f"  {i+1:2}/{ITERATIONS} {clip:<15} FAILED at code_suggestion")
                continue
            stage_successes["code_suggestion"] += 1

            # 7. Sign and sync
            s = client.post(f"/api/v1/soap-notes/{note_id}/sign", headers=headers)
            if s.status_code not in (200, 201):
                outcome["failed_at"] = f"sign {s.status_code}"
                per_iteration.append(outcome)
                print(f"  {i+1:2}/{ITERATIONS} {clip:<15} FAILED at sign")
                continue

            sync_ready = False
            for _ in range(20):
                time.sleep(0.5)
                ss = client.get(f"/api/v1/soap-notes/{note_id}/sync-status", headers=headers)
                if ss.status_code == 200:
                    st = ss.json().get("sync_status")
                    if st == "SUCCESS":
                        sync_ready = True
                        break
                    if st == "FAILED":
                        break
            if not sync_ready:
                outcome["failed_at"] = "emr_sync"
                per_iteration.append(outcome)
                print(f"  {i+1:2}/{ITERATIONS} {clip:<15} FAILED at emr_sync")
                continue
            stage_successes["emr_sync"] += 1

            # 8. Retention - verified, not assumed
            held, why = retention_holds(session_id)
            if not held:
                outcome["failed_at"] = f"retention: {why}"
                per_iteration.append(outcome)
                print(f"  {i+1:2}/{ITERATIONS} {clip:<15} FAILED at retention ({why})")
                continue
            stage_successes["retention"] += 1

            pipeline_successes += 1
            outcome["result"] = "SUCCESS"
            outcome["seconds"] = round(time.time() - started, 1)
            per_iteration.append(outcome)
            print(f"  {i+1:2}/{ITERATIONS} {clip:<15} SUCCESS  ({outcome['seconds']}s)")

        except Exception as e:
            outcome["failed_at"] = f"exception: {e}"
            per_iteration.append(outcome)
            print(f"  {i+1:2}/{ITERATIONS} {clip:<15} FAILED with {e}")

    rate = (pipeline_successes / ITERATIONS) * 100 if ITERATIONS else 0.0

    print(f"\n--- RUN {run_number} ---")
    for stage, count in stage_successes.items():
        print(f"  {stage:<22} {count}/{ITERATIONS}  ({count / ITERATIONS * 100:.1f}%)")
    print(f"  {'PIPELINE SUCCESS RATE':<22} {rate:.1f}%")

    os.makedirs(RESULTS_DIR, exist_ok=True)
    record = {
        "run": run_number,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "dataset": CLIPS,
        "iterations": ITERATIONS,
        "stage_successes": stage_successes,
        "pipeline_success_rate": rate,
        "iterations_detail": per_iteration,
    }
    out_path = os.path.join(RESULTS_DIR, f"run_{run_number}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2)
    print(f"\n  saved: {out_path}")

    # Every run recorded so far, which is what the requirement asks to see.
    runs = []
    for name in sorted(os.listdir(RESULTS_DIR)):
        if name.startswith("run_") and name.endswith(".json"):
            with open(os.path.join(RESULTS_DIR, name), encoding="utf-8") as f:
                runs.append(json.load(f))

    print("\n--- ALL RUNS RECORDED ---")
    for r in runs:
        print(f"  run {r['run']}: {r['pipeline_success_rate']:.1f}%  "
              f"({r['iterations']} iterations, {r['recorded_at'][:19]}Z)")

    if len(runs) < 3:
        print(f"\n  {len(runs)} of 3 runs recorded. The requirement asks for at "
              f"least 3 test runs - run this script again.")
    else:
        rates = [r["pipeline_success_rate"] for r in runs]
        worst = min(rates)
        print(f"\n  {len(runs)} runs recorded. Lowest: {worst:.1f}%. "
              f"Mean: {sum(rates) / len(rates):.1f}%.")
        if worst >= 95.0:
            print("  REQUIREMENT MET: every run reached at least 95%.")
        else:
            print("  REQUIREMENT NOT MET: at least one run fell below 95%.")


if __name__ == "__main__":
    main()
