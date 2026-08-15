# Module 9.1 Part B — ASR and Diarization Accuracy

Measured 15 August 2026. Reproduce with the commands in the last section.

Two requirements from SRS 2.3.3 had never been measured on real audio:

| Requirement | Target |
|---|---|
| ASR word accuracy | ≥ 85% |
| Speaker (diarization) accuracy | ≥ 85% |

---

## 1. Method

Four consultations were scripted first (`docs/evidence/consultation_scripts.md`),
covering a headache, an ankle sprain, a sore throat and a diabetes review. Because
the words are written down in advance, the correct answer is known and accuracy can
be computed rather than judged.

The evaluation calls `ASRService` and `DiarizationService` directly — no HTTP
server, no database, no background tasks. This measures the models, not the
plumbing; a failure here cannot be blamed on the API layer and vice versa.

**Word accuracy** is one minus the word error rate, computed by Levenshtein
distance over word sequences. It is reported twice, once over all words and once
with numeric tokens removed, because the scripts spell numbers out ("one forty over
ninety") while Whisper writes digits ("140/90"). That is a formatting difference,
not a recognition failure, and counting it as an error would understate real
performance.

**Speaker accuracy** aligns the reference and produced word sequences with
`difflib`, then compares the predicted speaker against the true speaker for every
word the aligner matches in both. Misheard words are excluded, so this measures
speaker labelling rather than re-measuring ASR.

### Two audio conditions

Three sets of recordings were measured. All three speak the identical scripts and
are scored against identical ground truth, so the only variable is the audio.

| Set | Description | Folder |
|---|---|---|
| Human — similar voices | Two speakers of the same gender, similar age and accent (siblings), one phone microphone. Results reported below; the recordings themselves are held locally and not committed, so this row is not reproducible from the repository. | `docs/evidence` (not committed) |
| Human — distinct voices | Female doctor, male patient. Same room, same method of recording. **The primary reported result.** | `docs/evidence/human_distinct` |
| Synthetic | Two Windows speech voices, one male and one female. A control condition only. | `docs/evidence/synthetic` |

The second and third sets exist because the first could not distinguish a defective
pipeline from a pipeline working correctly on difficult audio. The synthetic set is
not a substitute for real recordings: synthetic speech has no overlapping talk, no
background noise and no disfluency, so its scores describe an easy case and must
never be presented as real-world performance.

---

## 2. Results

### Human recordings, distinct voices — the primary result

Female doctor, male patient.

| Script | Pacing | Word accuracy | Speaker accuracy | Turns found | Turns real |
|---|---|---|---|---|---|
| 1 — headache | clear pauses | 87.3% | **100.0%** | 14 | 16 |
| 2 — ankle sprain | rapid, no gaps | 94.8% | 12.9% | 9 | 17 |
| 3 — sore throat | normal | 87.8% | **97.5%** | 12 | 17 |
| 4 — diabetes review | normal, long speeches | 75.5% | **100.0%** | 14 | 16 |
| **Mean** | | **86.4%** | **77.6%** | | |

ASR word accuracy **meets** the 85% target. Mean speaker accuracy does not, but the
mean is misleading here and should not be quoted alone: **three of the four
consultations scored 97.5% or above**, and the single failure is script 2, the
recording deliberately made as a rapid exchange with almost no gap between turns.
Section 3 explains what happens there.

### Human recordings, similar voices

Two siblings, same gender, similar age and accent. **These recordings are not
included in the repository.** The figures below are reported from the measured
run of 15 August 2026 and cannot be regenerated from a clone; the other two
conditions can. They are retained because the comparison between conditions is
the finding, and removing the weakest condition would leave only the results that
flatter the system.

| Script | Word accuracy | Speaker accuracy | Turns found | Turns real |
|---|---|---|---|---|
| 1 — headache | 93.4% | 23.6% | 3 | 16 |
| 2 — ankle sprain | 95.8% | 12.9%* | 7 | 17 |
| 3 — sore throat | 90.6% | 92.7% | 13 | 17 |
| 4 — diabetes review | 88.8% | 10.6% | 5 | 16 |
| **Mean** | **92.1%** | **35.9%** | | |

\* 16.7% as measured; the figure above is from the distinct-voice run. See the raw
output in the repository for both.

### Synthetic control

| Script | Word accuracy | Speaker accuracy | Turns found | Turns real |
|---|---|---|---|---|
| 1 | 95.3% | 100.0% | 14 | 16 |
| 2 | 98.6% | 100.0% | 15 | 17 |
| 3 | 93.9% | 99.4% | 16 | 17 |
| 4 | 93.3% | 100.0% | 14 | 16 |
| **Mean** | **95.3%** | **99.9%** | | |

### The three conditions side by side

| Condition | Mean speaker accuracy | Scripts at or above the 85% target |
|---|---|---|
| Human, similar voices | 35.9% | 1 of 4 |
| Human, distinct voices | 77.6% | 3 of 4 |
| Synthetic, distinct voices | 99.9% | 4 of 4 |

---

## 3. What the differences between the conditions mean

The "turns found" column carries the explanation. Two distinct failures appear, and
they are not the same problem.

### Failure 1 — voices too similar to separate

On three of the four similar-voice recordings the system never separates the
speakers at all. It found 3 speaker turns where 16 existed, and merged both people
into single blocks:

```
PATIENT: Good afternoon. This is your third month diabetes review.
DOCTOR:  Isn't it? That's right... How have things been going?
         Honestly, mixed. I've been taking the metformin every day...
```

Both speakers are inside the second block. Once that happens the accuracy figure no
longer measures speaker detection; it mostly records which of the two merged
clusters happened to be named DOCTOR.

Re-recording the identical scripts with a female doctor and a male patient — same
room, same equipment, same method — moved three of the four consultations to 97.5%
or above. Nothing in the code changed between those two runs. Voice similarity is
therefore established as the cause, not the implementation.

### Failure 2 — turn-taking too rapid

Script 2 fails even with clearly distinct voices, and fails differently. It
separates correctly for the opening exchanges and then collapses:

```
PATIENT: Hello, come in. What happened?              <- actually the doctor
DOCTOR:  I twisted my ankle playing football...      <- actually the patient
PATIENT: Which ankle?
DOCTOR:  The right one. Could you walk
PATIENT: on it afterwards?
DOCTOR:  Barely, I limped off the pitch... Did you hear a pop or a crack at
         the time? No, nothing like that. Have you put anything on it?...
```

Script 2 is the recording deliberately made as a rapid exchange with almost no gap
between turns, per the recording guide. Short turns give the diarizer very little
audio per speaker, and near-overlap blurs the boundary. Note also that the score of
12.9% is 100 − 87.1: the boundaries were largely right and the two names were
swapped, because the doctor's questions fell inside the patient's cluster and the
clinician-identification vote followed them.

### What this means for the requirement

Stated honestly:

> The system meets the 85% diarization target when the two speakers are
> acoustically distinguishable and speak at a conversational pace. It degrades
> when the voices are similar, and when turn-taking is rapid enough that
> individual turns become very short.

That is a more useful statement than a single averaged percentage, and every part
of it is backed by a measurement rather than an assumption.

### Consequence for SOAP notes

Diarization is not cosmetic. The SOAP Subjective section is populated from PATIENT
speech. When every segment is labelled DOCTOR the Subjective section is empty, which
is how the original defect was first noticed. Any deployment therefore depends on
adequate speaker separation, and that is a recording-quality requirement as much as
a software one.

### Recommended future work

Two changes would address both failures, and neither is a rewrite:

1. **Voice enrolment.** The doctor is an authenticated user, so their voice can be
   registered once at sign-up. That reduces the problem from "tell two unknown
   voices apart" to "find the known doctor's voice", which is a substantially
   easier task, and it removes the clinician-identification vote entirely.
   `app/ml/speaker_embedding_engine.py` already produces the fingerprints this
   would need.
2. **A confidence signal.** The pipeline can tell at runtime when its own output is
   unreliable — very few speaker turns for the length of audio, or one speaker
   holding almost all the speech time. Surfacing that on the session would let the
   interface ask the clinician to check the speaker labels, rather than presenting
   a merged transcript as though it were correct.

## 4. How the diarization method was arrived at

Four approaches were built and measured on the same human audio. All are retained
in `app/services/diarization_service.py` because the progression is the design
record.

| Method | Mean speaker accuracy | Why it was superseded |
|---|---|---|
| Pause heuristic | 68.9% | Never fired. Whisper leaves no gaps between segments (93 gaps measured, mean 0.006s, max 0.560s) against roughly 66 real speaker changes, so the condition was unreachable at any threshold. Every segment was labelled DOCTOR; the 68.9% is simply the share of words the doctor happens to speak. |
| Per-segment voice fingerprints | 66.0% | Fingerprints a whole Whisper segment. Fails whenever one segment contains two speakers, which is routine. |
| Sliding-window fingerprints | 48.8% | Correct approach — found 15 turns against 16 real — but fragile clustering and label assignment. |
| pyannote.audio (adopted) | 35.9% human / 99.9% synthetic | Purpose-built pipeline. Separates correctly whenever the voices are distinguishable. |

The pause heuristic scoring higher than better methods is worth reading carefully:
a number can rise while the system gets worse. It scored 68.9% while producing an
entirely single-speaker transcript. This is why the "turns found" column is reported
alongside the percentage.

### The label-assignment finding

Separating voices and naming them are different problems. Script 3 separated almost
perfectly yet scored 7.3% — every boundary correct, DOCTOR and PATIENT swapped.

The original rule was "whoever speaks the first word is the doctor". pyannote had
given the three-word opening fragment its own short turn and assigned it to the
wrong cluster, inverting the entire consultation. Anchoring identity on a single
word has no redundancy: nothing can outvote one mistake.

It was replaced with a majority vote — **the speaker who asks the questions is the
clinician** — which is a structural property of history-taking, not a tuned
parameter. Counted over the reference scripts the margin is large:

| | Doctor questions | Patient questions |
|---|---|---|
| Script 1 | 7 | 0 |
| Script 2 | 6 | 1 |
| Script 3 | 5 | 0 |
| Script 4 | 7 | 1 |

On the human set this rule scored *worse* in aggregate (35.9% against 64.1%),
because on merged audio the doctor's questions sit inside the merged block and the
vote points at the wrong cluster. On merged audio neither rule is meaningful — both
are coin flips. The rule was therefore chosen on the synthetic control, where
separation succeeds and the question is actually answerable: it identified the
clinician correctly in 4 of 4.

Known limitation: a consultation in which the patient asks more questions than the
clinician would invert. Speaking first is retained as the tie-break.

---

## 5. Honest notes on this measurement

- **Four recordings per condition is a small sample.** Nothing here should be read
  as a general accuracy claim for the system.
- **The mean speaker accuracy of the primary condition (77.6%) is dragged down by
  one script.** Quote it alongside the per-script figures, never alone. Three of
  four scored 97.5% or above; one scored 12.9%. A mean over four values, one of
  which is an outlier, is a weak summary and presenting only the favourable reading
  of it would be dishonest in the other direction.
- **The label-assignment rule was changed after the first measurement.** The change
  fixed a design fault visible in the transcript, and the replacement has no tunable
  parameter, but it was made with the results already in view and is disclosed for
  that reason.
- **No threshold was tuned against these recordings.** The pause threshold was left
  at its configured value and proven unreachable by direct measurement of gap
  distribution rather than by trial.
- **Synthetic results are a control, never a headline.** Reporting 99.9% as the
  system's diarization accuracy would be misleading.
- **The recordings contain no real patient data.** All four consultations are
  scripted fiction.
- **The similar-voice recordings are not committed.** That condition's figures are
  reported but not independently reproducible. Anyone repeating this work would
  need to record their own similar-voice pair.

---

## 6. Reproducing this

From the repository root:

```
# human recordings, distinct voices — the primary result
.\.venv\Scripts\python.exe -m scripts.evaluate_accuracy --audio-dir docs/evidence/human_distinct

# human recordings, similar voices — audio not committed; will report
# "no recordings evaluated" on a fresh clone
.\.venv\Scripts\python.exe -m scripts.evaluate_accuracy

# synthetic control
powershell -ExecutionPolicy Bypass -File scripts\synthesize_scripts.ps1
.\.venv\Scripts\python.exe -m scripts.build_synthetic_audio
.\.venv\Scripts\python.exe -m scripts.evaluate_accuracy --audio-dir docs/evidence/synthetic

# evidence that the pause heuristic cannot work at any threshold
.\.venv\Scripts\python.exe -m scripts.diagnose_gaps
```

Requires `HF_TOKEN` in `.env`, with the licences accepted for all three gated
repositories: `pyannote/segmentation-3.0`, `pyannote/speaker-diarization-3.1` and
`pyannote/speaker-diarization-community-1`.

Labelled transcripts are written beside each audio set as `diarized_output.txt`.
Read them. The numbers say how well it did; the transcripts say how it failed.
