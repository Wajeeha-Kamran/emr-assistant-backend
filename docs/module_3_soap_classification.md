# Module 3 — SOAP classification quality

Measured 16 August 2026 with `scripts/evaluate_soap.py`.

## Why this was measured

The Module 9.2 live API run produced a SOAP note with an empty Assessment section
despite the doctor saying "This looks like migraine with aura", a greeting filed
under Plan, and the examination findings, diagnosis and treatment plan all piled
into Objective. That observation was turned into a number so any fix could be
shown to work rather than asserted to.

## Method

The reference scripts are fed to `SOAPService.generate_draft` directly, as if
perfectly transcribed and perfectly diarized. **ASR and diarization are removed
from the measurement entirely.** A misclassification here cannot be blamed on a
misheard word, and an improvement cannot be an artefact of a better transcript.

This also makes the result a *ceiling*: it is what the classifier achieves with a
perfect transcript. Running the same pipeline from audio can only score lower.

Ground truth is `docs/evidence/soap_expected.md` — all 73 doctor sentences
labelled O, A, P, or X (belongs in no section), labelled from the scripts rather
than from any system output.

Two numbers are reported because either alone is misleading.

- **Clinical accuracy** — of the sentences that belong in the note, how many
  reached the right section.
- **Noise rate** — of the sentences that belong nowhere, how many got in anyway.

## Result

| | Before | After |
|---|---|---|
| Clinical accuracy | 74.4% (29/39) | 71.8% (28/39) |
| **Noise rate** | **100% (34/34)** | **0% (0/34)** |
| Objective | 100% (15/15)* | 86.7% (13/15) |
| Assessment | **0% (0/5)** | 20% (1/5) |
| Plan | 73.7% (14/19) | 73.7% (14/19) |

\* Objective's 100% was an artefact: it was the default destination for
everything, so material belonging in Assessment and Plan inflated it.

**Read honestly:** the noise result is a large, unambiguous improvement — the note
no longer contains a single greeting or question. Clinical accuracy is unchanged
in real terms; a move from 29 to 28 correct out of 39 is one sentence and should
not be described as a regression or an improvement. Assessment remains broken.

## What changed

1. **Sentence-level classification.** Speech is split into sentences before
   classification. Previously one Whisper segment was classified as a unit, and a
   30-second segment containing examination, diagnosis and plan could only be
   assigned to a single section.
2. **Non-documentable speech filtered.** Questions are excluded (the doctor asking
   "Have you had a fever?" documents nothing; the patient's answer is recorded, and
   reaches Subjective from the PATIENT side), along with announcements
   ("Let me examine you") and pleasantries. These are structural properties of
   consultation speech, implemented as explicit readable rules rather than a
   similarity threshold — a threshold would need tuning, and tuning it against the
   same four scripts used for measurement would void the measurement.
3. **Reference anchors rebalanced to six per category.** Classification takes the
   maximum similarity across a category's anchors, so unequal counts bias the
   result toward the larger category for reasons unrelated to the text. An
   intermediate revision left Objective with 5, Assessment with 9 and Plan with 6,
   and Objective's accuracy fell accordingly. None of the anchors appears in the
   evaluation scripts.

A defect was introduced and caught during this work: the sentence splitter
initially stripped terminal punctuation before the question filter ran, so the
filter's test for a trailing "?" never fired and every question still reached the
note. Noise fell only to 73.5% until this was fixed.

## Known limitation — Assessment

Assessment scores 1 of 5 and will not be fixed by further anchor tuning. The
failures show why:

| Sentence | Went to |
|---|---|
| "This looks like migraine with aura, and your blood pressure is higher than I would like." | Objective |
| "That gives you a Centor score of four, which makes bacterial infection likely rather than viral." | Objective |
| "I do not think it is fractured, and by the Ottawa rules you do not need an X-ray." | Plan |
| "Overall this is type two diabetes with suboptimal glycaemic control..." | Objective |

ClinicalBERT's mean-pooled embedding represents **what a sentence is about** —
blood pressure, a score, an X-ray. It does not represent **what the speaker is
doing** with that topic. Diagnosing, measuring and instructing are speech acts,
and topic similarity cannot separate them. Every one of these sentences was heard
perfectly and still misfiled.

This is a limitation of zero-shot embedding classification, not of the anchors.

### Two routes forward

1. **Diagnostic-cue detection.** Recognise the speech act rather than the topic.
   Statements of diagnosis take recognisable forms. Any cue list must be written
   from clinical documentation conventions, not from the failing sentences above,
   or it is fitted to the test set and the measurement becomes worthless.
2. **A supervised classifier.** Label a few hundred SOAP sentences and train on
   them. More work, substantially more robust, and a stronger contribution.

## Reproducing

```
.\.venv\Scripts\python.exe -m scripts.evaluate_soap
```

Roughly one minute. Loads ClinicalBERT; no ASR, no database, no server.
