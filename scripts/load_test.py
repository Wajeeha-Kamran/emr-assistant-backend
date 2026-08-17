"""
Module 8.3 — Load and performance measurement.

Measures the REAL performance of the pipeline against SRS 2.3.3 targets:
  - SOAP draft ready within 15s for a 10-minute consultation (single session)
  - Within 25s under concurrent load
  - At least 10 concurrent doctor sessions without failure

THREE THINGS THIS SCRIPT DOES DIFFERENTLY, and why they matter:

1. IT REFUSES TO RUN ON SILENCE.
   A generated all-zero WAV is not a valid workload. Whisper on silence
   produces zero segments, which both understates real work and can trigger
   empty-tensor errors that look like concurrency bugs but are not.

2. IT WARMS THE MODELS BEFORE TIMING.
   Whisper and ClinicalBERT load lazily on first use. Timing the first
   request measures model loading, not request handling. One untimed
   warm-up run happens first; every reported number is warm.

3. IT DOES NOT EXTRAPOLATE LINEARLY.
   Whisper pads or trims every input to a fixed 30-second window, so a
   1-second clip costs roughly the same as a 30-second one. Scaling a
   1-second measurement by 600 overstates a 10-minute audio by ~50x.
   Correct model: cost scales with the NUMBER OF 30-SECOND WINDOWS.
       windows(d) = ceil(d / 30)
       10-minute audio = ceil(600 / 30) = 20 windows
   The extrapolation below is labelled as an estimate, not a measurement.

Usage:
    python -m scripts.load_test path\to\real_speech.wav

Run with NO background uvicorn processes other than the app under test —
the retention sweeper corrupts results.
"""

import asyncio
import math
import os
import sys
import time
import uuid
import wave
from typing import Optional, Tuple

import httpx

BASE = "http://127.0.0.1:8000/api/v1"
CONCURRENT_SESSIONS = 10
WHISPER_WINDOW_SECONDS = 30
TARGET_AUDIO_SECONDS = 600  # 10 minutes, per SRS 2.3.3
SINGLE_TARGET_S = 15
CONCURRENT_TARGET_S = 25


def inspect_audio(path: str) -> float:
    """Return duration in seconds. Refuse silent or empty files."""
    if not os.path.exists(path):
        sys.exit(f"FATAL: audio file not found: {path}")

    with wave.open(path, "rb") as w:
        frames = w.getnframes()
        rate = w.getframerate()
        width = w.getsampwidth()
        channels = w.getnchannels()
        duration = frames / float(rate) if rate else 0.0
        raw = w.readframes(frames)

    if duration <= 0:
        sys.exit(f"FATAL: {path} has zero duration.")

    # Reject digital silence outright. int16 assumed; if not, skip the check.
    if width == 2:
        peak = 0
        step = max(1, len(raw) // 20000)  # sample, do not scan megabytes
        for i in range(0, len(raw) - 1, 2 * step):
            v = int.from_bytes(raw[i:i + 2], "little", signed=True)
            peak = max(peak, abs(v))
        if peak < 200:  # ~0.6% of full scale
            sys.exit(
                f"FATAL: {path} appears to be silence (peak amplitude {peak}).\n"
                "Performance measured on silence is meaningless — Whisper emits no\n"
                "segments and the SOAP pipeline has nothing to classify.\n"
                "Use a real recording of speech."
            )

    print(f"Audio: {path}")
    print(f"  duration      {duration:.2f}s")
    print(f"  sample rate   {rate} Hz, {channels}ch, {width * 8}-bit")
    print(f"  whisper windows for this clip: {math.ceil(duration / WHISPER_WINDOW_SECONDS)}")
    return duration


async def run_session(client: httpx.AsyncClient, audio: bytes,
                      label: str) -> Tuple[bool, float, float, Optional[str]]:
    """One full consultation. Returns (ok, asr_seconds, soap_seconds, error)."""
    try:
        email = f"load_{uuid.uuid4().hex[:10]}@example.com"
        await client.post(f"{BASE}/auth/register",
                          json={"email": email, "password": "password",
                                "full_name": "Dr Load Test"})
        login = await client.post(f"{BASE}/auth/login",
                                  data={"username": email, "password": "password"})
        if login.status_code != 200:
            return False, 0.0, 0.0, f"login {login.status_code}"
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        sess = await client.post(f"{BASE}/sessions/", headers=headers)
        if sess.status_code != 201:
            return False, 0.0, 0.0, f"create session {sess.status_code}"
        sid = sess.json()["id"]

        await client.post(f"{BASE}/sessions/{sid}/start-recording", headers=headers)

        asr_start = time.perf_counter()
        up = await client.post(
            f"{BASE}/sessions/{sid}/stop-recording", headers=headers,
            files={"file": ("clip.wav", audio, "audio/wav")},
        )
        if up.status_code != 200:
            return False, 0.0, 0.0, f"upload {up.status_code}: {up.text[:120]}"

        # Poll until the transcript finishes. ASR runs in a background task.
        deadline = time.perf_counter() + 600
        while True:
            t = await client.get(f"{BASE}/sessions/{sid}/transcript", headers=headers)
            if t.status_code == 200:
                status = t.json().get("status")
                if status == "completed":
                    break
                if status == "failed":
                    return False, 0.0, 0.0, "transcript failed"
            if time.perf_counter() > deadline:
                return False, 0.0, 0.0, "transcript timeout (600s)"
            await asyncio.sleep(0.25)
        asr_s = time.perf_counter() - asr_start

        soap_start = time.perf_counter()
        soap = await client.post(f"{BASE}/sessions/{sid}/soap-notes/generate",
                                 headers=headers)
        if soap.status_code != 201:
            return False, asr_s, 0.0, f"soap {soap.status_code}: {soap.text[:120]}"
        soap_s = time.perf_counter() - soap_start

        return True, asr_s, soap_s, None

    except Exception as e:  # noqa: BLE001 - we want the type name in the report
        return False, 0.0, 0.0, f"{type(e).__name__}: {e}"


def estimate_10min(asr_s: float, soap_s: float, clip_duration: float) -> float:
    """Estimate a 10-minute audio from a measured clip, by 30s windows."""
    clip_windows = max(1, math.ceil(clip_duration / WHISPER_WINDOW_SECONDS))
    target_windows = math.ceil(TARGET_AUDIO_SECONDS / WHISPER_WINDOW_SECONDS)
    asr_per_window = asr_s / clip_windows
    # SOAP cost scales with transcript length, roughly with windows too.
    soap_per_window = soap_s / clip_windows
    return (asr_per_window + soap_per_window) * target_windows


async def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else "docs/evidence/load_clip.wav"
    duration = inspect_audio(path)
    with open(path, "rb") as f:
        audio = f.read()

    async with httpx.AsyncClient(timeout=900.0) as client:
        print("\n--- WARM-UP (untimed: loads Whisper + ClinicalBERT) ---")
        ok, _, _, err = await run_session(client, audio, "warmup")
        print("warm-up:", "ok" if ok else f"FAILED - {err}")
        if not ok:
            sys.exit("Warm-up failed; fix that before measuring.")

        print("\n--- SINGLE SESSION (warm) ---")
        ok, asr_s, soap_s, err = await run_session(client, audio, "single")
        if not ok:
            sys.exit(f"Single session failed: {err}")
        total = asr_s + soap_s
        print(f"  ASR              {asr_s:.2f}s")
        print(f"  SOAP generation  {soap_s:.2f}s")
        print(f"  Total            {total:.2f}s   (clip is {duration:.2f}s)")
        est = estimate_10min(asr_s, soap_s, duration)
        print(f"  ESTIMATE for 10-minute audio: {est:.1f}s "
              f"(by 30s windows, NOT a measurement)")
        print(f"  SRS target: {SINGLE_TARGET_S}s -> "
              f"{'MET' if est <= SINGLE_TARGET_S else 'MISSED'}")

        print(f"\n--- {CONCURRENT_SESSIONS} CONCURRENT SESSIONS ---")
        wall = time.perf_counter()
        results = await asyncio.gather(
            *[run_session(client, audio, f"c{i}") for i in range(CONCURRENT_SESSIONS)]
        )
        wall = time.perf_counter() - wall

        good = [r for r in results if r[0]]
        bad = [r for r in results if not r[0]]
        print(f"  wall clock       {wall:.2f}s")
        print(f"  succeeded        {len(good)}/{CONCURRENT_SESSIONS}")
        print(f"  failed           {len(bad)}")
        for i, (_, _, _, err) in enumerate(bad):
            print(f"    failure: {err}")

        if good:
            a = sum(r[1] for r in good) / len(good)
            s = sum(r[2] for r in good) / len(good)
            print(f"  avg ASR          {a:.2f}s")
            print(f"  avg SOAP         {s:.2f}s")
            est_c = estimate_10min(a, s, duration)
            print(f"  ESTIMATE for 10-minute audio under load: {est_c:.1f}s "
                  f"(NOT a measurement)")
            print(f"  SRS target: {CONCURRENT_TARGET_S}s -> "
                  f"{'MET' if est_c <= CONCURRENT_TARGET_S else 'MISSED'}")

        print("\n--- VERDICT ---")
        print(f"  10 concurrent sessions without failure: "
              f"{'PASS' if not bad else 'FAIL'}")


if __name__ == "__main__":
    asyncio.run(main())
