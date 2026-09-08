# Colab notebooks — model comparison

The ASR and diarization comparison could not be run on the development machine,
which has no GPU. It was run on Google Colab against a Tesla T4. These are the
notebooks exactly as they were run, with their output cells intact, so that the
figures in the report can be traced to the code that produced them.

Every notebook clones this repository rather than uploading files by hand. That
matters: the audio, the reference scripts and the scoring functions are the ones
in `docs/evidence/` and `scripts/evaluate_accuracy.py`, so a number here and a
number in the report were computed by the same code.

## Hardware

Identical across every run, recorded by the notebooks themselves and saved
alongside the results:

| | |
|---|---|
| GPU | NVIDIA Tesla T4, 15.6 GB VRAM |
| CPU | Intel Xeon @ 2.00 GHz, 1 physical / 2 logical cores |
| RAM | 13.6 GB |
| Python | 3.12.13 |
| PyTorch | 2.11.0 + cu128 (CUDA 12.8) |

The deployed system runs on CPU. These GPU timings are therefore a measure of the
models, not of the deployed pipeline — the CPU pipeline timings are in
`docs/evidence/robustness/`.

## Which notebook produced which result

| Notebook | What it did | Results file |
|---|---|---|
| `01_whisper_pyannote_benchmark.ipynb` | Run 0 (base.en + pyannote, human and synthetic audio), Run 1 (Whisper medium + pyannote), Run 4 (noise sweep at 20 / 10 / 5 dB) | `benchmark_comparison.csv`, `benchmark_detail.csv` |
| `01a_benchmark_initial.ipynb` | The first version of the above, before the pyannote 4.x return-type patch. Kept because the Sortformer and Parakeet cells in it are scaffolds, and the difference records what had to be corrected. | — |
| `02_handoff_medium_pyannote.ipynb` | Dumped Whisper `medium` words and pyannote spans to `handoff.json` | `handoff.json` (intermediate) |
| `03a_nemo_install_attempt.ipynb` | First NeMo install, interrupted. Kept because it is the record of the dependency conflict. | — |
| `03_nemo_sortformer_parakeet.ipynb` | Run 2 (medium + Sortformer) and Run 3 (Parakeet + pyannote), scored against the handoff | `nemo_comparison.csv`, `nemo_detail.csv`, `nemo_hardware.json` |
| `04_handoff_base_en.ipynb` | Dumped Whisper `base.en` words to `handoff_base.json` | `handoff_base.json` (intermediate) |
| `05_base_en_sortformer.ipynb` | Run 5 (base.en + Sortformer) — the deployed ASR with the alternative diarizer | `base_sortformer_detail.csv`, `base_sortformer_hardware.json` |
| `06_environment_test_and_noise_sweep.ipynb` | Whether Whisper, pyannote and NeMo can coexist in one Python environment, and Sortformer under the same noise sweep | `sortformer_noise_detail.csv`, `sortformer_noise_summary.csv` |

## Why the work is split across several notebooks

NeMo 2.5.0, the version Colab's `pip` resolved to in August, required
`numpy < 2.0`, while `pyannote.audio` 4.0.7 and the current `numba` want
`numpy 2.x`. Installing both in one Colab session broke whichever was
installed first.

**Corrected 8 Sep 2026.** This is a property of NeMo 2.5.0, not of NeMo.
NeMo 3.0.0 installs against `numpy 2.5.2` and `torch 2.14.0`, and NeMo 3.0.0,
`openai-whisper` 20250625 and `pyannote.audio` 4.0.7 import together in one
Python **3.12** environment on Windows with no version forcing at all. The
conflict described below is historical.

The workaround was to run Whisper and pyannote in one notebook, write the words
and speaker spans to a JSON handoff file, and score the NeMo diarizers against
that handoff in a second, clean notebook. This is why notebooks 02 and 04 produce
no results of their own — they exist so the comparison could cross an environment
boundary without changing any of the inputs.

Notebook 06, run later, established that the conflict is resolvable: installing
NeMo first and then forcing `numpy==1.26.4` last leaves all three importable in a
single process. A full `pip freeze` of the working combination is written by that
notebook as `pip_freeze_working.txt`.

On NeMo 3.0.0 even that step is unnecessary — see the correction above. The
only real constraint is the Python version: NeMo does not support Python 3.14,
which the backend `.venv` currently uses. That, and not the operating system,
was the actual blocker; the earlier note that Sortformer required Linux or
WSL2 was wrong and is withdrawn.

## Results, in short

Word and speaker accuracy on the four scripted consultations in
`docs/evidence/human_distinct`. Means only — the per-script figures are in the
detail CSVs, and they matter: the 77.6% speaker figure is three near-perfect
recordings and one collapse, not four mediocre ones.

| Combination | Word | Speaker | Peak VRAM |
|---|---|---|---|
| base.en + pyannote (fallback) | 88.3% | 77.6% | 2.00 GB |
| medium + pyannote | 89.0% | 77.8% | 5.06 GB |
| medium + Sortformer | 89.0% | 99.9% | 3.50 GB |
| Parakeet + pyannote | 90.3% | 77.7% | 4.77 GB |
| base.en + Sortformer | 88.3% | 99.9% | 1.26 GB |

Noise, on the deployed combination:

| | clean | 20 dB | 10 dB | 5 dB |
|---|---|---|---|---|
| word accuracy | 88.3% | 87.7% | 82.9% | 78.3% |

The **speaker** accuracy under noise is not reported for pyannote. It rose as
noise increased, which is not robustness: noise happened to stop two voices
merging on script 2, flipping an already-wrong labelling to a right one. A
fragile recording changing its mind is not a measurement, and it was discarded.
Notebook 06 re-ran the same sweep against Sortformer, which does not have that
failure to accidentally repair, and there the speaker figure holds steady
(99.6 → 99.6 → 99.4 → 99.3) while word accuracy falls as expected.

## What was not changed

No parameter was tuned against these recordings and re-run. The speaker-role rule
— whoever asks more questions is the doctor — is identical to `DiarizationService`
and is held constant across every run, so what is being compared is diarization
models and not naming rules.

Sortformer is **not** integrated into the deployed system. The 99.9% figure is a
measurement of an alternative, and the report says so wherever it appears.
