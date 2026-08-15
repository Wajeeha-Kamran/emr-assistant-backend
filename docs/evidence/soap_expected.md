# Expected SOAP classification — doctor speech, sentence by sentence

Ground truth for `scripts/evaluate_soap.py`. Every sentence the doctor speaks in
`consultation_scripts.md`, labelled with the section it belongs in.

    O   Objective    — examination findings, vital signs, test results
    A   Assessment   — diagnosis, clinical impression, severity
    P   Plan         — prescriptions, follow-up, referrals, safety-netting
    X   Excluded     — belongs in NO section

X covers two things a clinical note should not contain. **Questions**: the doctor
asking "Have you had a fever?" documents nothing — the patient's answer is what
gets recorded, and that is already in Subjective. **Social and procedural
narration**: "Good morning", "Let me examine you" carry no clinical content.

Labelled from the scripts, not from any system output, so no implementation can
have influenced them.

---

## Script 1

X | Good morning.
X | Please take a seat.
X | What brings you in today?
X | Can you describe the pain for me?
X | Have you felt sick at all, or been vomiting?
X | Any changes to your vision?
X | Blurring, or flashing lights?
X | Have you had headaches like this before?
X | Are you taking any medication at the moment?
X | Let me check your blood pressure.
O | Your blood pressure is one forty over ninety, which is elevated.
O | Pupils are equal and reactive.
O | No neck stiffness.
A | This looks like migraine with aura, and your blood pressure is higher than I would like.
P | I am going to prescribe sumatriptan fifty milligrams for the attacks.
P | Keep a headache diary for two weeks.
P | Come back in two weeks so we can recheck your blood pressure.
P | If the pain becomes suddenly severe, or you develop weakness or confusion, go to the emergency department immediately.

## Script 2

X | Hello, come in.
X | What happened?
X | Which ankle?
X | Could you walk on it afterwards?
X | Did you hear a pop or a crack at the time?
X | Have you put anything on it?
X | Any previous injuries to that ankle?
X | Let me have a look.
O | There is swelling over the lateral malleolus and tenderness on the outer side.
O | No bony tenderness at the posterior edge.
O | You can bear weight, just about.
O | Range of motion is reduced by pain.
A | This is a lateral ankle sprain, grade two.
A | I do not think it is fractured, and by the Ottawa rules you do not need an X-ray.
P | Rest, ice, compression and elevation for the next three days.
P | Take ibuprofen four hundred milligrams three times daily with food.
P | Start gentle movement after day three.
P | If you still cannot bear weight in a week, come back and we will arrange imaging.
P | Realistically four to six weeks, and only after you can hop on it without pain.

## Script 3

X | Hi there.
X | What can I do for you?
X | Have you had a fever?
X | Any cough?
X | Any swelling in your neck, or tenderness?
X | Anyone at home or at work unwell?
X | Let me examine you.
O | Temperature is thirty eight point two.
O | The tonsils are enlarged with white exudate on both sides.
O | There is tender cervical lymphadenopathy.
O | No cough reported.
A | That gives you a Centor score of four, which makes bacterial infection likely rather than viral.
P | I will start you on phenoxymethylpenicillin, two hundred and fifty milligrams four times a day for ten days.
P | Finish the whole course even when you feel better.
P | Take paracetamol for the pain and drink plenty of fluids.
P | If you develop difficulty breathing, or you cannot swallow your own saliva, that is an emergency and you should be seen straight away.

## Script 4

X | Good afternoon.
X | This is your three-month diabetes review, isn't it?
X | How have things been going?
X | Any hypos?
X | Any episodes of feeling shaky, sweaty, confused?
X | How about your feet?
X | Any numbness or tingling?
X | Any changes to your vision?
X | Let me examine you and go through your results.
O | Your blood pressure today is one thirty two over eighty four.
O | Weight is unchanged at eighty six kilograms.
O | Your HbA1c has come back at fifty eight millimoles per mole, which is slightly above target.
O | Foot examination shows intact pulses and normal sensation to monofilament testing on both feet, so the tingling is not showing up as measurable nerve damage yet.
A | Overall this is type two diabetes with suboptimal glycaemic control, and some early neuropathic symptoms that are not yet confirmed on examination.
P | I am going to increase your metformin to one gram twice daily.
P | Please continue monitoring your morning readings and bring the record next time.
P | I will refer you for retinal screening, which is due, and I would like repeat bloods in three months.
P | If the tingling in your feet gets worse or spreads, let me know sooner rather than waiting.
P | Focus on the morning readings first.
P | I will book you in with the diabetes nurse to go through evening meals, since that is what usually drives the fasting numbers.

---

## Totals

| Label | Count |
|---|---|
| O — Objective | 15 |
| A — Assessment | 5 |
| P — Plan | 19 |
| X — should not appear | 34 |
