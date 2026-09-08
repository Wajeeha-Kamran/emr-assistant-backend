# Sortformer diarization — measurement and integration

8 September 2026

## Why the diarizer was changed

pyannote replaced three home-built diarizers on 16 August and was the deployed
engine from then until now. Its headline figure across the four scripted
consultations is 88.3% word / 77.6% speaker accuracy. The speaker mean is
misleading:

| Script | pyannote speaker acc | Sortformer speaker acc |
|---|---|---|
| 1 | 100.0% | 100.0% |
| 2 | **12.4%** | **99.5%** |
| 3 | 98.1% | 100.0% |
| 4 | 100.0% | 100.0% |
| **Mean** | **77.6%** | **99.9%** |

Script 2 is not a partial error. 12.4% means the two speakers were swapped
almost everywhere: pyannote produced 9 turns against 17 real ones, so the two
voices were merged and then labelled the wrong way round. Every SOAP section
built from that transcript inherits the wrong role — a patient's reported
symptom is filed as a doctor's observation.

The cause is structural. pyannote embeds short windows and then clusters the
embeddings; when two voices sit close together in embedding space the
clustering collapses. Sortformer predicts speaker-labelled frames end to end,
so there is no clustering step available to collapse.

Word accuracy is identical for both (88.3%) because both were scored against
the same Whisper `base.en` output. The comparison isolates diarization.

Evidence: `docs/evidence/benchmarks/diarizer_head_to_head.csv`,
`base_sortformer_detail.csv`, `benchmark_detail.csv`.

## Does the Colab result hold outside Colab

Yes. Re-measured on CPU on the development machine, 8 September:

| Script | word | speaker | diarization s | audio s |
|---|---|---|---|---|
| 1 | 87.3% | 100.0% | 11.34 | 95.0 |
| 2 | 94.8% | 99.5% | 7.85 | 78.7 |
| 3 | 87.8% | 100.0% | 6.21 | 77.7 |
| 4 | 75.5% | 100.0% | 15.39 | 137.3 |
| **Mean** | **86.3%** | **99.9%** | | |

Speaker accuracy reproduces exactly. Whole-pipeline time is 0.29–0.41×
realtime on CPU, comfortably inside the performance budget.

Word accuracy fell from 88.3% to 86.3%, entirely on script 4 (83.6% → 75.5%).
That is Whisper, not the diarizer: the Colab run decoded in fp16 on a T4, this
one in fp32 on CPU, and script 4 is the longest recording. Speaker accuracy on
that script stayed at 100.0%.

Source: `docs/evidence/benchmarks/sortformer_cpu_detail.csv`,
produced by `scripts/evaluate_sortformer.py`.

## What was changed in the code

- `app/ml/sortformer_engine.py` — new. Singleton with an inference lock, the
  same shape as `PyannoteEngine`: `diarize(audio_path)` returns
  `[(start, end, label), ...]`. Converts input to mono 16 kHz, which
  Sortformer requires and the mobile client does not guarantee.
- `app/services/diarization_service.py` — `_diarize_by_sortformer` added.
  pyannote's word-attribution body was extracted into `_turns_to_segments`
  and is now shared, so both engines use identical smoothing and doctor
  identification and any accuracy difference belongs to the model.
- Dispatch order is now sortformer → pyannote → window → embedding → pause.
  A Sortformer failure falls through to pyannote automatically.
- `app/core/config.py` — `DIARIZATION_METHOD` default changed to
  `"sortformer"`. `HF_TOKEN` is now only needed by the fallback.

## Building the environment Sortformer needs

NeMo does not support Python 3.14, and the original `.venv` is Python 3.14.
On that interpreter `SortformerEngine` fails to import on the first request
and the service logs the failure and falls back to pyannote -- silently, as
far as the API is concerned. **Sortformer therefore requires `.venv312`.**
`run_backend.ps1` prefers it automatically and prints a yellow warning if it
has to fall back to `.venv`.

    py -3.12 -m venv .venv312
    .\.venv312\Scripts\pip install -r requirements-312.txt
    .\.venv312\Scripts\pip install nemo_toolkit[asr]
    .\.venv312\Scripts\python -m pytest
    .\.venv312\Scripts\python scripts\verify_sortformer_pipeline.py

**Use `requirements-312.txt`, not `requirements.txt`.** The latter includes
`resemblyzer`, whose `webrtcvad` dependency has no wheel and must compile. On
a machine where Python 3.12 lives at a drive root, setuptools emits the
malformed linker path `D:libs` and the build dies with
`LNK1104: cannot open file 'python312.lib'`. `requirements-312.txt` omits it;
resemblyzer served only the 66% `embedding` diarizer, which now sits fourth in
the fallback chain, and NeMo supplies `librosa` and `soundfile` in its place.

Expected result: **155 passed**, and the verify script printing
`PASS: Sortformer produced the speaker turns`. Run the verify script rather
than trusting the test suite -- no test asserts which diarizer ran, so all 155
pass just as happily on the pyannote fallback.

An earlier note recorded that Sortformer required Linux or WSL2. That was
wrong. NeMo 3.0.0, `openai-whisper` 20250625 and `pyannote.audio` 4.0.7
install and import together on Windows under Python 3.12 with `numpy` 2.5.3
and `torch` 2.14.0, with no version forcing. The `numpy < 2.0` conflict
belonged to NeMo 2.5.0 and no longer exists. `notebooks/README.md` has been
corrected.

## Consequence for the SOAP work

None for the 97.4% figure. `scripts/evaluate_soap.py` parses the DOCTOR: and
PATIENT: labels straight out of `consultation_scripts.md` and feeds them to
`SOAPService.generate_draft`, so ASR and diarization are removed from that
measurement by construction. 97.4% is the classifier judged on perfect input,
and it neither rose nor fell when the diarizer changed. It remains the correct
baseline to compare an open-source LLM against, because the LLM would be
measured under exactly the same conditions.

What does change is end-to-end quality. Module 9.2's live run produced a note
with an empty Assessment and the greeting filed under Plan; part of that came
from the classifier, and part from speaker labels that were wrong before the
classifier ever saw them. With diarization at 99.9%, the gap between the 97.4%
laboratory figure and what a real recording produces should narrow. That gap
has never been measured, and it is worth measuring: run a full recording
through the API and score the resulting note against `soap_expected.md`.
