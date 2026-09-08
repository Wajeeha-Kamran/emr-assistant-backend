# End-to-end SOAP accuracy, and the concurrency result

8 September 2026. Measured on `.venv312` (Python 3.12, NeMo 3.0.0,
Sortformer diarization).

## Two different numbers, and why both are honest

`scripts/evaluate_soap.py` feeds the hand-written DOCTOR:/PATIENT: scripts
straight to `SOAPService.generate_draft`. ASR and diarization are excluded by
construction, so it measures the classifier alone.

`scripts/evaluate_soap_e2e.py` runs the same four recordings through the real
`ASREngine` and the real `DiarizationService`, then scores the resulting note
against the same ground truth with the same scorer.

| | Clinical accuracy | Noise rate |
|---|---|---|
| Classifier only, perfect transcript | **97.4%** (38/39) | 0.0% |
| Held-out scenarios, perfect transcript | **100.0%** (38/38) | 0.0% |
| End to end, real audio | **82.1%** (32/39) | 0.0% |

The 15.3-point gap is what ASR and diarization cost. Noise rate stays at 0.0%
throughout: no greeting or question leaked into the note in any run.

Per section, end to end: objective 11/15 (73.3%), assessment 4/5 (80.0%),
plan 17/19 (89.5%).

## The scorer had to be corrected twice. Both corrections are recorded here.

The first version of `evaluate_soap_e2e.py` reused `evaluate_soap.py`'s exact
substring match and reported **23.1%**. That number was wrong, and the drafts
show why. Script 1's Assessment read:

> This looks like migraine with aura and your blood pressure is higher than
> what I would like.

against a ground truth of "...higher than I would like." One inserted word,
a completely correct Assessment, scored zero. Exact matching is right in
`evaluate_soap.py`, where the note is built from the same hand-written
sentences it is scored against; against an 86-88%-accurate transcript it
measures transcription, not classification.

The second version scored order-aware coverage with a 0.70 threshold and
reported **71.8%**. Still wrong, for a narrower reason: it reused
`evaluate_accuracy.strip_numerics`, which matches `^[0-9]+$`. That strips
digits but not number words. The references spell numbers out ("one thirty
two over eighty four") and Whisper writes digits ("132 over 84"), so the
filter stripped one side and not the other and no numeric sentence could
align. Ten of the thirty-nine sentences contain numbers.

The third version drops digits *and* number words from both sides and reports
**82.1%**. The threshold was not touched between the second and third runs;
only the asymmetry was fixed.

A metric revised three times deserves scrutiny, so every remaining failure is
listed below rather than summarised. The 0.70 threshold discriminates cleanly
in practice -- matches score 0.86-1.00 against a next-best of 0.14-0.36, so
the result is not sensitive to where in that gap the line is drawn.

## Every remaining failure, classified

Seven sentences out of thirty-nine.

**Genuine ASR loss (3)** -- the words that carried the finding were destroyed,
so no scorer should credit them:

| Script | Ground truth | What Whisper produced |
|---|---|---|
| 1 | "No neck stiffness." | "No next -tiffness." |
| 4 | "...fifty eight millimoles per mole" | "...58 millimetres per month" |
| 4 | "Foot examination shows intact pulses..." | absent from the note |

The HbA1c one is the most serious: the unit changed from millimoles per mole
to millimetres per month, which is not a clinical value at all.

**Genuine classification error (2)** -- the words are present, in the wrong
section:

| Script | Ground truth | Filed under | Should be |
|---|---|---|---|
| 2 | "You can bear weight, just about." | plan | objective |
| 4 | "Overall this is type two diabetes with suboptimal glycaemic control..." | objective | assessment |

Script 2's is the *same single error* the perfect-transcript run makes, so it
is a classifier limitation, not something ASR introduced. Script 4's is new,
and it is the Module 9.2 complaint recurring: the diagnosis filed under
Objective. Its coverage in Objective is 0.90, so the sentence is intact -- the
classifier put it in the wrong place.

**Sentence-boundary artefacts (2)** -- content present and in the right
section, coverage just under threshold because Whisper moved a full stop:

| Script | Ground truth | Coverage | What happened |
|---|---|---|---|
| 4 | "Focus on the morning readings first." | 0.67 | split as "Focus on the morning's reading. First," |
| 4 | "I will book you in with the diabetes nurse..." | 0.61 | tail reworded |

Counting these two as successes would give 87.2%. They are reported as
failures because the scorer should not be tuned around individual sentences.

## What this means

Sortformer moved diarization from 77.6% to 99.9%, and the end-to-end note is
now 82.1% against a 97.4% classifier ceiling. Of the seven-sentence gap, five
are attributable to ASR and two to classification -- and only one of the two
is new. **Whisper `base.en` is now the binding constraint on note quality, not
the diarizer and not the classifier.**

That matters for what comes next. An LLM replacing the extractive classifier
addresses the 2 classification failures; it cannot recover "millimetres per
month", because those words are what it would be given. Any evaluation of a
generative model must be run against the 97.4% classifier baseline on perfect
transcripts, since that is the part of the pipeline an LLM actually changes.

## Concurrency: the SRS targets are not met

`scripts/load_test.py` against a live backend on `.venv312`, warm models,
`consult_1.wav` (95.0s, 4 Whisper windows):

| Measure | Result | SRS 2.3.3 target | |
|---|---|---|---|
| Single session, warm | 36.50s (ASR 35.62 + SOAP 0.88) | 15s | **MISSED** |
| 10 concurrent sessions | **4 succeeded, 6 failed** | 10/10 no failure | **FAIL** |
| Wall clock, 10 concurrent | 149.14s | | |
| Mean ASR under load | 94.08s | | |

Failures were one `RemoteProtocolError: Server disconnected without sending a
response` and five `transcript failed`. Ten simultaneous Whisper
transcriptions contend for one CPU threadpool; this is a capacity limit, not a
logic defect.

**This contradicts the thesis.** Table 4.6 reports ten concurrent sessions
10/10. `claude/measurements_final.md` recorded "3, then 1 on repeat" after the
24 August async rework, and this run confirms the pessimistic record. The
thesis currently cites a figure the script does not reproduce, and the script
is in the repository for anyone to run.

The single-session figure needs the same care. 36.50s is for a 95-second clip
on CPU; the SRS target is written against a 10-minute consultation, and the
script's own extrapolation (182.5s) is labelled an estimate, not a
measurement. Neither number meets 15s.

This is a hardware limit before it is a software one -- every measurement here
is CPU-only, `torch 2.14.0+cpu`. It should be stated as measured rather than
adjusted, and it must be resolved before a 7B parameter model is added, since
that makes contention worse rather than better.
