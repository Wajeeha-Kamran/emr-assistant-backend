# Mock Consultation Scripts — Recording Guide

Four scripted doctor–patient consultations for evaluating the EMR Assistant.
These recordings serve **three** purposes at once:

1. **Diarization accuracy** (Module 9.1 Part B) — does the system correctly label who is speaking? SRS target: ≥85%.
2. **ASR word accuracy** (SRS 2.3.3) — does it transcribe the words correctly? Target: ≥85%. Never measured so far.
3. **SOAP note quality** — real generated notes to include as figures in the final report.

Because the words are scripted, the correct answer is known in advance. That is what makes measurement possible.

---

## How to record

**People:** two. One reads DOCTOR, the other reads PATIENT. Any two people — the voices only need to be distinguishable.

**Equipment:** a phone voice recorder is fine. Sit close to it, in a quiet room.

**Manner:** read at a natural conversational pace. Do not pause deliberately between turns, and do not rush either. Read it as speech, not as a list.

**Deliberate variation** — this matters, because it tests where the speaker detection breaks:

- **Script 1:** leave a clear, natural pause between turns (about a second).
- **Script 2:** respond quickly, with almost no gap between turns.
- **Script 3:** normal pacing, but the patient occasionally says "mm" or "yeah" while the doctor is still talking.
- **Script 4:** normal pacing, with two noticeably longer speeches.

Record each as a **separate file**. Do not edit them afterwards.

**Naming:** `consult_1.m4a`, `consult_2.m4a`, `consult_3.m4a`, `consult_4.m4a`

**Converting** — run this for each one:

```
ffmpeg -i consult_1.m4a -ar 16000 -ac 1 docs\evidence\consult_1.wav
```

Put the converted files in `docs\evidence\`. The reference text files (below) go in the same folder as `consult_1.txt`, `consult_2.txt`, and so on — copy each script's dialogue exactly as written, keeping the `DOCTOR:` and `PATIENT:` prefixes.

**If you fluff a line**, just carry on naturally — but correct the reference text file to match what was actually said. The reference must match the recording, not the other way round.

---

## Script 1 — Headache, possible migraine
*Pacing: clear pause between turns.*

DOCTOR: Good morning. Please take a seat. What brings you in today?

PATIENT: I've been having really bad headaches for about four days now.

DOCTOR: Can you describe the pain for me?

PATIENT: It's mostly on the right side, behind my eye. It throbs. Bright light makes it much worse.

DOCTOR: Have you felt sick at all, or been vomiting?

PATIENT: A bit nauseous yesterday morning, but I haven't actually been sick.

DOCTOR: Any changes to your vision? Blurring, or flashing lights?

PATIENT: Sometimes there are little zigzag lines before it starts.

DOCTOR: Have you had headaches like this before?

PATIENT: Not this bad. I get normal headaches but nothing like this.

DOCTOR: Are you taking any medication at the moment?

PATIENT: Just paracetamol when it gets bad. It doesn't help much.

DOCTOR: Let me check your blood pressure. Your blood pressure is one forty over ninety, which is elevated. Pupils are equal and reactive. No neck stiffness.

DOCTOR: This looks like migraine with aura, and your blood pressure is higher than I would like.

DOCTOR: I am going to prescribe sumatriptan fifty milligrams for the attacks. Keep a headache diary for two weeks. Come back in two weeks so we can recheck your blood pressure. If the pain becomes suddenly severe, or you develop weakness or confusion, go to the emergency department immediately.

PATIENT: Understood. Thank you, doctor.

---

## Script 2 — Ankle injury
*Pacing: quick responses, minimal gaps.*

DOCTOR: Hello, come in. What happened?

PATIENT: I twisted my ankle playing football yesterday evening.

DOCTOR: Which ankle?

PATIENT: The right one.

DOCTOR: Could you walk on it afterwards?

PATIENT: Barely. I limped off the pitch and it's been swollen since.

DOCTOR: Did you hear a pop or a crack at the time?

PATIENT: No, nothing like that.

DOCTOR: Have you put anything on it?

PATIENT: Just ice last night, and I kept it up on a cushion.

DOCTOR: Any previous injuries to that ankle?

PATIENT: I sprained it about two years ago, the same side.

DOCTOR: Let me have a look. There is swelling over the lateral malleolus and tenderness on the outer side. No bony tenderness at the posterior edge. You can bear weight, just about. Range of motion is reduced by pain.

DOCTOR: This is a lateral ankle sprain, grade two. I do not think it is fractured, and by the Ottawa rules you do not need an X-ray.

DOCTOR: Rest, ice, compression and elevation for the next three days. Take ibuprofen four hundred milligrams three times daily with food. Start gentle movement after day three. If you still cannot bear weight in a week, come back and we will arrange imaging.

PATIENT: How long until I can play again?

DOCTOR: Realistically four to six weeks, and only after you can hop on it without pain.

---

## Script 3 — Sore throat
*Pacing: normal, with occasional short acknowledgements from the patient while the doctor speaks.*

DOCTOR: Hi there. What can I do for you?

PATIENT: My throat has been really sore since Saturday, and it hurts to swallow.

DOCTOR: Have you had a fever?

PATIENT: I felt hot last night. I didn't take my temperature.

DOCTOR: Any cough?

PATIENT: No cough at all, actually.

DOCTOR: Any swelling in your neck, or tenderness?

PATIENT: Yeah, under my jaw feels tender.

DOCTOR: Anyone at home or at work unwell?

PATIENT: My daughter had a sore throat last week.

DOCTOR: Let me examine you. Temperature is thirty eight point two. The tonsils are enlarged with white exudate on both sides. There is tender cervical lymphadenopathy. No cough reported.

DOCTOR: That gives you a Centor score of four, which makes bacterial infection likely rather than viral.

PATIENT: Mm, right.

DOCTOR: I will start you on phenoxymethylpenicillin, two hundred and fifty milligrams four times a day for ten days. Finish the whole course even when you feel better. Take paracetamol for the pain and drink plenty of fluids.

PATIENT: Yeah, okay.

DOCTOR: If you develop difficulty breathing, or you cannot swallow your own saliva, that is an emergency and you should be seen straight away.

PATIENT: Thank you.

---

## Script 4 — Diabetes follow-up
*Pacing: normal, but with two longer speeches.*

DOCTOR: Good afternoon. This is your three-month diabetes review, isn't it?

PATIENT: That's right. It's been about three months since the last one.

DOCTOR: How have things been going?

PATIENT: Honestly, mixed. I've been taking the metformin every day, but my sugars are still higher than I'd like in the mornings. I've been checking most days. Usually around eight or nine before breakfast. In the evenings it's better, maybe six or seven. I've been trying to walk more, about twenty minutes most days, but work has been busy and I've missed some days. My weight is about the same as last time.

DOCTOR: Any hypos? Any episodes of feeling shaky, sweaty, confused?

PATIENT: No, nothing like that.

DOCTOR: How about your feet? Any numbness or tingling?

PATIENT: A bit of tingling in my toes at night sometimes.

DOCTOR: Any changes to your vision?

PATIENT: Not that I've noticed.

DOCTOR: Let me examine you and go through your results. Your blood pressure today is one thirty two over eighty four. Weight is unchanged at eighty six kilograms. Your HbA1c has come back at fifty eight millimoles per mole, which is slightly above target. Foot examination shows intact pulses and normal sensation to monofilament testing on both feet, so the tingling is not showing up as measurable nerve damage yet.

DOCTOR: Overall this is type two diabetes with suboptimal glycaemic control, and some early neuropathic symptoms that are not yet confirmed on examination.

DOCTOR: I am going to increase your metformin to one gram twice daily. Please continue monitoring your morning readings and bring the record next time. I will refer you for retinal screening, which is due, and I would like repeat bloods in three months. If the tingling in your feet gets worse or spreads, let me know sooner rather than waiting.

PATIENT: Should I change anything about my diet?

DOCTOR: Focus on the morning readings first. I will book you in with the diabetes nurse to go through evening meals, since that is what usually drives the fasting numbers.

PATIENT: Alright. Thank you, doctor.
