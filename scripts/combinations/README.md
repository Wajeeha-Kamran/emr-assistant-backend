# The six model combinations

One file per combination, so the configuration behind a row in the report is
visible in one place. Everything shared lives in `common.py`.

| # | Speech recognition | Speaker separation | Runs where | Why it is tested |
|---|---|---|---|---|
| 0 | Whisper `base.en` | pyannote 3.1 | this laptop | The current system. The baseline. |
| 1 | Whisper `medium` | pyannote 3.1 | this laptop | Does a larger recogniser help? |
| 2 | Whisper `medium` | Sortformer | **Colab** | Larger recogniser, better separator. |
| 3 | Parakeet TDT 0.6B v2 | pyannote 3.1 | **Colab** | NVIDIA's recogniser instead of Whisper. |
| 4 | Whisper `base.en` | pyannote 3.1 | this laptop | The baseline with noise at 10 dB. |
| 5 | Whisper `base.en` | Sortformer | **Colab** | Cheapest recogniser, best separator. The recommendation. |

## Running the three that work locally

From the repository root, with the backend's virtual environment:

```
.venv\Scripts\python.exe scripts/combinations/combo_0.py
.venv\Scripts\python.exe scripts/combinations/combo_1.py
.venv\Scripts\python.exe scripts/combinations/combo_4.py
```

Each writes `docs/evidence/combinations/combination_N.json` and prints a table.
Combination 1 loads Whisper `medium`, roughly ten times the size of `base.en`,
so expect it to take considerably longer on a CPU.

## Why three of them need Colab

Combinations 2, 3 and 5 need NVIDIA NeMo, which does not import on Windows.
Measured on 22 August 2026, Python 3.14, this laptop:

- NeMo declares `protobuf~=5.29.5`; onnx requires protobuf 6.x. Protobuf
  enforces a matching major version, so one of the two must give.
- NeMo reaches `texterrors`, which imports `plac`, which calls
  `multiprocessing.get_context("fork")` while being imported. `fork` is a Unix
  system call. `plac` 1.4.6 needs it; `plac` 1.3.5 avoids it but imports
  `asyncore`, removed from Python in 3.12. No version of that dependency
  satisfies both Python 3.14 and Windows.

This is a packaging problem, not a limit of the models. Sortformer itself runs
on this laptop's CPU in 12 seconds for a 95 second consultation — 0.13×
realtime — once NeMo is forced to import. NVIDIA's supported routes on Windows
are WSL2 or a Linux container.

Running those three combinations therefore means either Colab, which is already
set up and proven, or moving the backend to WSL2. The second is the right
long-term answer and the wrong thing to attempt in the week before submission.

## What is held constant

Only the pieces named in each combination change. Both diarizers return
`[(start, end, label)]` and are fed through the same downstream code — the same
word collection, the same smoothing over three neighbouring words, the same
question-count vote for which speaker is the doctor. A difference in the scores
is therefore a difference between the models, not between two ways of
assembling their output.

Noise in combination 4 is additive white Gaussian at 10 dB SNR from a fixed
seed, so the same combination run twice produces the same audio. Without that,
a difference between two runs could be the noise rather than the model.

## Scoring

`common.py` imports `word_error_rate` and `speaker_accuracy` from
`scripts/evaluate_accuracy.py` rather than reimplementing them, so these
numbers can be placed beside the ones already reported. Word accuracy is
1 − word error rate over word sequences; speaker accuracy compares labels on
the words that align between the script and the output.

Per-recording figures are printed above the mean deliberately. On four
recordings a mean hides a spread of more than ten points, and on consult_2 the
difference between diarizers is the whole story.
