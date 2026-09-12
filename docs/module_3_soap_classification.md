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

Measured in three stages. Every figure is from a full run; nothing is interpolated.

| | Baseline | After stage 1 | After stage 2 |
|---|---|---|---|
| Clinical accuracy | 74.4% (29/39) | 71.8% (28/39) | **97.4% (38/39)** |
| Noise rate | 100% (34/34) | **0%** | **0%** |
| Objective | 100% (15/15)* | 86.7% | 93.3% (14/15) |
| Assessment | **0% (0/5)** | 20% (1/5) | **100% (5/5)** |
| Plan | 73.7% (14/19) | 73.7% | **100% (19/19)** |

\* Objective's baseline 100% was an artefact: it was the default destination for
everything, so material belonging in Assessment and Plan inflated it.

**Held-out set: 38/38 clinical sentences correct, 0% noise.**

## What changed, in two stages

### Stage 1 — granularity and filtering

1. **Sentence-level classification.** Speech is split into sentences before
   classification. Previously one Whisper segment was classified as a unit, and a
   30-second segment containing examination, diagnosis and plan could only be
   assigned to a single section.
2. **Non-documentable speech filtered.** Questions are excluded — the doctor asking
   "Have you had a fever?" documents nothing, and the patient's answer already
   reaches Subjective from the PATIENT side of the transcript — along with
   announcements ("Let me examine you") and pleasantries. Implemented as explicit
   readable rules rather than a similarity threshold: a threshold would need tuning,
   and tuning it against the same four scripts used for measurement would void the
   measurement.
3. **Reference anchors rebalanced to six per category.** Classification takes the
   maximum similarity across a category's anchors, so unequal counts bias the result
   toward the larger category for reasons unrelated to the text.

This stage solved noise completely and left accuracy unchanged in real terms
(29 to 28 correct out of 39 is one sentence). **Assessment stayed broken**, which
was the finding that mattered: two rounds of anchor rewriting moved it from 0/5 to
1/5, establishing that anchor tuning was not the answer.

### Stage 2 — speech-act cues

Embedding similarity classifies by **topic**. "This looks like migraine with aura"
and "Your blood pressure is one forty over ninety" are both about blood pressure and
headache, so ClinicalBERT places them close together and both land in Objective.

What separates them is not topic but **speech act** — what the clinician is *doing*
with the topic. Diagnosing, measuring and instructing are different acts, and each
has recognisable surface forms in clinical language. Cue patterns now detect the act;
the embedding model still handles every sentence with no clear marker.

The result is a hybrid: rules where the language is explicit, embeddings where it is
not. Neither alone was sufficient — the embeddings could not find Assessment at all,
and rules alone would not generalise past the phrasings anyone thought to write down.

Safety-netting is checked before everything else. A conditional instruction — "if X
happens, do Y" — is a directive whatever words appear inside the condition. Without
this, "If the pain becomes suddenly severe, go to the emergency department" was filed
under Assessment because "severe" is a severity term, and severity grading is part of
naming a condition.

## Guarding against a fix fitted to its own test set

The cue patterns were written by someone who had already seen which sentences the
previous version got wrong. That is the standard way a rule-based fix quietly becomes
fitted to its test set: it scores well on the four reference scripts and fails on
anything else.

`docs/evidence/soap_heldout.md` is the check — 56 labelled sentences from clinical
scenarios that appear nowhere in the reference scripts: chest pain, urinary tract
infection, asthma review, lower back pain, and a skin complaint. Same labels, same
scoring.

**It scores 100%, above the reference set's 97.4%.** The rules are not narrowly
fitted to the four consultations they were developed against.

**The caveat that must travel with that number.** The same author wrote both the cue
patterns and the held-out sentences. The set therefore tests generalisation across
*clinical scenarios* but not across *phrasing styles*: a different clinician, or real
ASR output with its disfluencies and mistranscriptions, may phrase things in ways
neither shares. It is a genuine check, not a complete one. A stronger version would
draw sentences from real clinical documentation or from a second author.

## Remaining error

One sentence out of 39: "You can bear weight, just about." — an examination finding
phrased conversationally, with no speech-act marker, so it falls through to the
embedding model and lands in Plan.

It was deliberately left alone. Writing a rule for a single sentence one can see
failing is exactly the fitting this section is about, and the cost — one ambiguous
observation misfiled — is far lower than the cost of a rule set quietly shaped to its
own test data.

## What the reference sets did not catch — backchannel (12 Sep 2026)

The caveat above turned out to be the real one. Both labelled sets are written
in full sentences, so every sentence in them is either clinical content or a
question. Real speech is not like that.

Run against the five Kaggle recordings — real consultations, real hesitation,
real ASR damage — the filter let through **312 of the 677 sentences that reached
it (46%)** that were nothing but acknowledgement:

| | count |
|---|---|
| "Okay." | 98 |
| "OK." | 52 |
| "No." | 47 |
| "Yeah." | 20 |
| "All right." | 12 |
| other backchannel (55 forms) | 83 |

The worst case was CAR0001, whose Objective section was 26 sentences, 25 of them
a bare "No.". `_OBJECTIVE_CUES` matches `^no\b` as an observation ("No neck
stiffness"), so every bare denial was filed as an examination finding.

That note scored **0.0% novel content and 0.0% omission** — perfect on every
faithfulness metric the project has, and worthless as a clinical note. It is the
clearest example so far of a measurement that was right about what it measured
and silent about what mattered.

**The fix.** `_is_backchannel` in `app/services/soap_service.py`: a sentence
whose every word is a function word, discourse marker or bare polarity token is
not documentable. Any sentence containing a digit is exempt, because "52. Okay,
okay." answers "how old are you" and the age is content.

| | before | after |
|---|---|---|
| Kaggle sentences reaching the note | 677 | 365 |
| Labelled O/A/P sentences discarded | — | **0 of 129** |
| Reference clinical accuracy | 97.4% | 97.4% (unchanged) |
| Reference noise rate | 0% | 0% (unchanged) |

The reference figures cannot move, and this is asserted by a test rather than
observed: `tests/unit/test_documentable_filter.py` reads both labelled files and
fails if any sentence labelled O, A or P is ever discarded. Without that test, a
future tightening of this filter could improve the noise rate by throwing away
findings and nothing would notice.

**What this costs.** "No." answering "Any chest pain?" is a pertinent negative,
and it is now dropped. Recovering it means pairing each short answer with the
question that prompted it and rendering the pair ("Denies chest pain") — a real
feature, with its own failure modes: the pairing has to survive diarization
errors, and the rendering would no longer be strictly extractive. Recorded as
the next iteration. Filing 25 unattributed "No."s under Objective is the larger
harm.

**What this does not fix.** The corrected Kaggle notes are still not good notes.
Assessment is empty in four of the five, and Plan absorbs fragments that
sentence-splitting cut mid-utterance ("when does it", "and how has your"). Those
are separate defects — the encounters are mostly history-taking with no stated
diagnosis, and real speech does not split cleanly on punctuation Whisper
inserted. Neither is addressed here.

## Reproducing

```
.\.venv312\Scripts\python.exe -m scripts.evaluate_soap              # the four reference scripts
.\.venv312\Scripts\python.exe -m scripts.evaluate_soap --heldout    # unseen clinical scenarios
```

Roughly one minute each. Loads ClinicalBERT; no ASR, no database, no server.

Run both. The reference figure alone says nothing about whether the rules generalise;
the held-out figure alone says nothing about performance on the consultations the
system was designed around.
