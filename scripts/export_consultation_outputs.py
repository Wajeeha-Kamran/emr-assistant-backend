"""
Run consultation recordings through the live backend and save what comes out, so
the SOAP notes shown to a clinician are genuine system output rather than
anything written by hand.

Everything goes over HTTP against the running API — the same path the mobile app
takes — so this exercises the real asynchronous generate-and-poll flow rather
than calling the services directly.

Before running, start the backend in another terminal:

    .\\run_backend.ps1

Then, from the repository root:

    # the project's own four evaluation recordings
    .\\.venv\\Scripts\\python.exe -m scripts.export_consultation_outputs

    # any other folder of recordings, e.g. the Kaggle dataset
    .\\.venv\\Scripts\\python.exe -m scripts.export_consultation_outputs ^
        --audio-dir "D:\\Downloads\\audio-recording-whisper" ^
        --out kaggle_outputs.json --limit 5

Transcription runs at roughly the length of the audio on CPU, so allow about a
minute per minute of recording.

Non-WAV input is converted automatically. The backend reads audio through
soundfile, which handles WAV but not MP3, M4A or AAC — without conversion those
upload cleanly and then fail inside transcription, which is the least helpful
place to find out.
"""

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import time

import httpx

BASE = "http://127.0.0.1:8000"
DEFAULT_AUDIO_DIR = os.path.join("docs", "evidence", "human_distinct")

# A throwaway account, so this never touches a real one. Reused if it exists.
EMAIL = "export@example.com"
PASSWORD = "exportpassword123"
FULL_NAME = "Dr. Export"

POLL_SECONDS = 3
TRANSCRIPT_TIMEOUT = 1800
NLP_TIMEOUT = 300

AUDIO_EXTENSIONS = (".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac", ".mp4")


def fail(message):
    sys.exit(f"\nFAILED: {message}")


# ---------------------------------------------------------------------------
# Input preparation
# ---------------------------------------------------------------------------

def find_audio(audio_dir, limit):
    if not os.path.isdir(audio_dir):
        fail(f"{audio_dir} is not a folder.")

    files = sorted(
        p for p in glob.glob(os.path.join(audio_dir, "**", "*"), recursive=True)
        if p.lower().endswith(AUDIO_EXTENSIONS)
    )
    if not files:
        fail(f"no audio files found under {audio_dir}")

    if limit:
        files = files[:limit]
    return files


def as_wav(path, work_dir):
    """Return a 16 kHz mono WAV version of path, converting only if needed."""
    if path.lower().endswith(".wav"):
        return path

    if not shutil.which("ffmpeg"):
        fail("ffmpeg is needed to convert non-WAV audio, and is not on PATH. "
             "It ships with the Whisper setup, so check your environment.")

    os.makedirs(work_dir, exist_ok=True)
    target = os.path.join(work_dir, os.path.splitext(os.path.basename(path))[0] + ".wav")

    print(f"  converting {os.path.basename(path)} to WAV…")
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", path, "-ac", "1", "-ar", "16000", target],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not os.path.exists(target):
        fail(f"ffmpeg could not convert {path}:\n{result.stderr[-500:]}")

    return target


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def authenticate(client):
    """Register the throwaway doctor, or log in if it already exists."""
    client.post("/api/v1/auth/register", json={
        "email": EMAIL, "password": PASSWORD, "full_name": FULL_NAME,
    })  # a 400 here just means an earlier run created it

    response = client.post(
        "/api/v1/auth/login",
        data={"username": EMAIL, "password": PASSWORD},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if response.status_code != 200:
        fail(f"login returned {response.status_code}: {response.text}")

    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def wait_for(description, check, timeout):
    """Poll until check() returns a value. check returns None to keep waiting."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = check()
        if result is not None:
            return result
        time.sleep(POLL_SECONDS)
    fail(f"timed out waiting for {description} after {timeout}s")


def process(client, headers, audio_path, original_name):
    print(f"\n{original_name}")

    # -- record ------------------------------------------------------------
    # The trailing slash matters: without it the request is redirected and some
    # clients drop the Authorization header.
    response = client.post("/api/v1/sessions/", headers=headers)
    if response.status_code not in (200, 201):
        fail(f"could not create a session: {response.status_code} {response.text}")
    session_id = response.json()["id"]

    client.post(f"/api/v1/sessions/{session_id}/start-recording", headers=headers)

    print("  uploading…")
    with open(audio_path, "rb") as fh:
        response = client.post(
            f"/api/v1/sessions/{session_id}/stop-recording",
            headers=headers,
            files={"file": (os.path.basename(audio_path), fh, "audio/wav")},
        )
    if response.status_code != 200:
        print(f"  SKIPPED — upload rejected: {response.status_code} {response.text[:200]}")
        return None

    # -- transcribe --------------------------------------------------------
    print("  transcribing and separating speakers (this is the slow part)…")

    def transcript_ready():
        r = client.get(f"/api/v1/sessions/{session_id}/transcript", headers=headers)
        if r.status_code != 200:
            return None
        body = r.json()
        if body["status"] == "completed":
            return body
        if body["status"] == "failed":
            fail(f"transcription failed for {original_name}")
        return None

    transcript = wait_for("the transcript", transcript_ready, TRANSCRIPT_TIMEOUT)
    print(f"  {len(transcript['segments'])} turns")

    # -- draft the note ----------------------------------------------------
    print("  drafting the note…")
    client.post(f"/api/v1/sessions/{session_id}/soap-notes/generate", headers=headers)

    def note_ready():
        r = client.get(f"/api/v1/sessions/{session_id}/soap-notes", headers=headers)
        if r.status_code != 200:
            return None
        body = r.json()
        status = body.get("generation_status")
        if status == "completed":
            return body
        if status == "failed":
            fail(f"note generation failed for {original_name}: {body.get('generation_error')}")
        return None

    note = wait_for("the SOAP note", note_ready, NLP_TIMEOUT)

    # -- suggest codes -----------------------------------------------------
    print("  matching codes…")
    client.post(f"/api/v1/soap-notes/{note['id']}/code-suggestions/generate", headers=headers)

    def codes_ready():
        r = client.get(f"/api/v1/sessions/{session_id}/soap-notes", headers=headers)
        if r.status_code != 200:
            return None
        status = r.json().get("codes_generation_status")
        if status == "completed":
            return True
        if status == "failed":
            print("  WARNING: code suggestion failed; continuing without codes")
            return True
        return None

    wait_for("the code suggestions", codes_ready, NLP_TIMEOUT)

    codes = client.get(
        f"/api/v1/soap-notes/{note['id']}/code-suggestions", headers=headers
    ).json()

    print(f"  done — {len(note['sections'])} sections, {len(codes)} codes")

    return {
        "audio_file": original_name,
        "session_id": session_id,
        "transcript": [
            {"speaker": s["speaker_role"], "text": s["text"],
             "start": s["start_time"], "end": s["end_time"]}
            for s in transcript["segments"]
        ],
        "soap_sections": {
            s["section_type"]: s["content"] for s in note["sections"]
        },
        "code_suggestions": [
            {"code": c["code"], "description": c["description"],
             "type": c["code_type"], "rank": c["rank"]}
            for c in codes
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio-dir", default=DEFAULT_AUDIO_DIR,
                        help="folder of recordings, searched recursively")
    parser.add_argument("--out", default="consultation_outputs.json",
                        help="where to write the results")
    parser.add_argument("--limit", type=int, default=0,
                        help="process at most this many files (0 = all)")
    args = parser.parse_args()

    audio_files = find_audio(args.audio_dir, args.limit)
    print(f"{len(audio_files)} recordings to process from {args.audio_dir}")

    work_dir = os.path.join("scratch", "converted_audio")
    results = []

    with httpx.Client(base_url=BASE, timeout=600.0) as client:
        try:
            client.get("/health")
        except Exception:
            fail("the backend is not responding. Start it with .\\run_backend.ps1 first.")

        headers = authenticate(client)

        for path in audio_files:
            original_name = os.path.basename(path)
            try:
                prepared = as_wav(path, work_dir)
                outcome = process(client, headers, prepared, original_name)
                if outcome:
                    results.append(outcome)
            except SystemExit:
                raise
            except Exception as e:
                # One bad recording should not lose the whole run.
                print(f"  SKIPPED — {type(e).__name__}: {e}")

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2, ensure_ascii=False)

    print("\n" + "=" * 60)
    print(f"Wrote {args.out} — {len(results)} of {len(audio_files)} recordings.")
    print("=" * 60)


if __name__ == "__main__":
    main()
