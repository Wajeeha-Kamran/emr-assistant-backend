# Module 8.3 — Performance & Concurrency

**Date:** 15 August 2026
**Requirements addressed:** SRS 2.3.3 (Efficiency, Scalability), SRS 2.1.4 (Constraints)
**Hardware:** development laptop, CPU-only inference (no CUDA device available)

---

## 1. Method

Measurement script: `scripts/load_test.py`.

Three deliberate choices were made because the first attempt at this module produced misleading numbers, and each is worth recording:

**Real speech, not generated silence.** The initial script synthesised a 1-second all-zero WAV. Whisper produces no segments from silence, which both understates the workload and raises empty-tensor errors that resemble concurrency faults but are not. The script now inspects the audio, measures peak amplitude, and refuses to run on anything that looks like silence. The clip used is a 65.76 s mono 16 kHz recording of natural speech.

**Models warmed before timing.** Whisper and ClinicalBERT load lazily on first use. The initial measurement timed the first request after startup and therefore reported model-loading time as request time — 5.70 s for SOAP generation, against a true warm figure below 1 s. One untimed warm-up session now runs first; every reported figure is warm.

**Extrapolation by 30-second windows, not linear scaling.** Whisper pads or trims every input to a fixed 30-second window, so a 1-second clip costs approximately the same as a 30-second one. The initial script multiplied a 1-second measurement by 600 to estimate a 10-minute consultation, overstating it by roughly fifty times. Cost scales with the number of windows: `ceil(duration / 30)`. A 10-minute consultation is 20 windows. All 10-minute figures below are labelled estimates, not measurements.

The retention scheduler and the simulated EMR service were stopped during measurement; both were confirmed earlier to perturb results.

---

## 2. Results

### 2.1 Single session (warm)

| Stage | Measured (65.76 s clip, 3 windows) |
|---|---|
| ASR | 9.87 s |
| SOAP generation | 0.90 s |
| **Total** | **10.77 s** |

Per 30-second window: approximately 3.3 s ASR, 0.3 s SOAP.

**Estimated for a 10-minute consultation (20 windows): 71.8 s.**
SRS target: 15 s. **Not met.**

### 2.2 Ten concurrent sessions

| Metric | Result |
|---|---|
| Succeeded | 10 / 10 |
| Failed | 0 |
| Wall clock, all ten | 112.65 s |
| Mean ASR per session (includes queue wait) | 60.49 s |
| Mean SOAP per session | 3.09 s |

**Estimated for a 10-minute consultation under load: 423.9 s.**
SRS target: 25 s. **Not met.**

SRS requirement "support at least 10 concurrent doctor sessions without failure": **met.**

Note: the mean ASR figure includes time spent queueing, not inference alone. Inference remains ~10 s per session; the remainder is waiting.

---

## 3. Concurrency defect found and fixed

The first concurrent run failed completely — 0 of 10 sessions succeeded. Two distinct exceptions appeared in the server log, both inside Whisper's decoder:

```
KeyError: Linear(in_features=512, out_features=512, bias=True)
    at  v = kv_cache[self.value]          (whisper/model.py:109)

RuntimeError: cannot reshape tensor of 0 elements into shape [1, 0, 8, -1]
    at  q.view(*q.shape[:2], self.n_head, -1)   (whisper/model.py:119)
```

**Cause.** Whisper attaches a per-decode key/value cache to the model instance through forward hooks. The application holds one loaded model as a singleton, so ten concurrent decodes shared and overwrote that scratch state — one thread clearing entries another was still reading. This is a thread-safety fault in shared model state, not a capacity or queueing problem.

**Fix.** Inference is serialised on a module-level lock in `app/ml/whisper_engine.py`. Concurrent requests queue rather than collide. A second, latent defect was fixed at the same time: singleton construction was not guarded, so two requests arriving during a cold start could each load a separate copy of the model.

**Why not Celery or Redis.** The failure was contention on one process-local object, not a task-distribution problem. A distributed task queue would not have prevented it, would not improve inference speed, and would add a broker and worker processes to Module 10.1's container stack. The project's minimalism rule holds: the proportionate fix is a lock. This is the point at which the roadmap permitted introducing Celery, and the measurement showed it was not warranted.

**Result after fix:** 10 of 10 sessions succeeded, no exceptions, server stable throughout.

An incidental confirmation: during the failing run the server did not crash. Each background ASR task failed independently, was caught, and marked its transcript failed — the error-handling introduced in Module 8.2 behaving correctly under a genuine fault.

---

## 4. Conclusion on the timing requirements

The efficiency targets are not achievable with CPU-only inference, and no architectural change within this project's scope would achieve them.

The limit is arithmetic. Whisper `base.en` on this CPU costs approximately 3.3 s per 30 seconds of audio. A 10-minute consultation is 20 such windows, so roughly 70 s of computation. Moving that work to background workers, separate processes, or a task queue changes where it happens, not how long it takes. Additional threads make it worse — that is precisely the fault documented in section 3.

This outcome was anticipated in the project's own requirements. SRS 2.1.4 Constraints states: *"Hardware: GPU may be required for efficient ASR/NLP processing."* The measurements above are the evidence for that constraint.

### Options considered and not taken

**`faster-whisper` (CTranslate2).** Named as an alternative in the project roadmap; typically around four times faster on CPU at comparable accuracy. Estimated to bring the single-session figure from ~72 s to ~18 s — closer to the 15 s target but still above it, and still far above 25 s under concurrent load. Cost: replacing the ASR engine and re-validating accuracy. Deferred as future work.

**GPU deployment.** The direct remedy, and the one the SRS already anticipates.

**Celery / Redis.** Rejected on evidence — see section 3.

### Recommended future work

1. GPU-backed deployment for ASR inference.
2. Evaluate `faster-whisper` as a CPU optimisation, using the `ASREngine` abstraction from Module 2.4, which exists to make exactly this substitution a configuration change.
3. If neither is available, revise the efficiency targets in the SRS to state the hardware they assume.

---

## 5. Requirement status

| SRS 2.3.3 requirement | Target | Result | Status |
|---|---|---|---|
| 10 concurrent doctor sessions without failure | 10 | 10 / 10 | **Met** |
| SOAP draft ready, single session, 10-min audio | 15 s | ~72 s (est.) | Not met — CPU limit |
| SOAP draft ready, under concurrent load | 25 s | ~424 s (est.) | Not met — CPU limit |
| API remains responsive during ML inference | — | Yes, no crashes or dropped connections after fix | **Met** |

---

## 6. Reproducing these measurements

```
# Stop the retention scheduler and simulated EMR service first.
.\.venv\Scripts\uvicorn.exe app.main:app

# In a second terminal:
.\.venv\Scripts\python.exe -m scripts.load_test docs\evidence\load_clip.wav
```

The script refuses to run on silent audio, warms the models before timing, prints the window count for the clip supplied, and labels every extrapolated figure as an estimate rather than a measurement.
