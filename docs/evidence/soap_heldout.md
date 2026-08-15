# Held-out set — SOAP classification

Sentences from clinical scenarios that appear **nowhere** in
`consultation_scripts.md`: chest pain, urinary tract infection, asthma review,
lower back pain, and a skin complaint.

## Why this exists

`app/services/soap_service.py` classifies partly by speech-act cues — patterns
that recognise a clinician diagnosing, instructing, or recording an observation.
Those patterns were written as families of clinical phrasing, but they were
written by someone who had seen which sentences the previous version got wrong.
That is the standard way a rule-based fix quietly becomes fitted to its test set:
it scores well on the four reference scripts and fails on anything else.

This set is the check. It uses the same labels and the same scoring, on
consultations the rules were not written against. **If the score here is much
lower than on the reference scripts, the rules are fitted and the reference
score is not trustworthy.**

    O   Objective    — examination findings, vital signs, test results
    A   Assessment   — diagnosis, clinical impression, severity
    P   Plan         — prescriptions, follow-up, referrals, safety-netting
    X   Excluded     — belongs in no section

## Script 101 — Chest pain

X | Good afternoon.
X | What has been troubling you?
X | When did the pain start?
X | Does it go anywhere else, into your arm or jaw?
X | Let me listen to your chest.
O | Pulse is eighty two and regular.
O | Heart sounds are normal with no murmur.
O | There is reproducible tenderness over the costal margin.
O | The ECG shows normal sinus rhythm with no ST changes.
A | The pain is reproducible on palpation, which points to a musculoskeletal cause.
A | Cardiac origin is unlikely given the normal ECG and the character of the pain.
P | Take ibuprofen with food for the next five days.
P | Apply a warm compress to the area twice a day.
P | If the pain becomes crushing or you feel breathless, call an ambulance immediately.

## Script 102 — Urinary tract infection

X | Hello, do sit down.
X | How long has it been burning?
X | Any blood in the urine?
X | Any pain in your back or sides?
O | Temperature is thirty seven point four.
O | There is no loin tenderness on either side.
O | The urine dipstick is positive for nitrites and leucocytes.
A | This is a lower urinary tract infection without signs of upper tract involvement.
P | I will prescribe nitrofurantoin one hundred milligrams twice daily for three days.
P | Drink plenty of water over the next few days.
P | Come back in a week if the symptoms have not settled.

## Script 103 — Asthma review

X | Good morning, take a seat.
X | How often are you using your blue inhaler?
X | Any night-time waking with cough or wheeze?
O | Peak flow today is three hundred and eighty litres per minute.
O | Chest is clear on auscultation with no wheeze.
O | Inhaler technique was checked and is adequate.
A | Control is suboptimal given the frequency of reliever use.
A | This is moderate persistent asthma rather than intermittent.
P | I am going to step up your preventer inhaler to two puffs twice daily.
P | Continue the reliever as needed but let me know if you need it more often.
P | I will book you a review in eight weeks.

## Script 104 — Lower back pain

X | Hi, come through.
X | Did you lift anything heavy?
X | Any numbness or weakness in your legs?
O | There is paraspinal muscle spasm in the lumbar region.
O | Straight leg raise is negative on both sides.
O | Power and sensation in both legs are intact.
A | This appears to be mechanical low back pain without nerve root involvement.
A | Serious pathology is unlikely in the absence of red flag features.
P | Keep moving gently rather than resting in bed.
P | Take paracetamol regularly for the first week.
P | If you develop difficulty passing urine or numbness between your legs, go to hospital straight away.

## Script 105 — Skin complaint

X | Good afternoon, what can I help with?
X | How long has the rash been there?
X | Is it itchy at all?
O | There is a well demarcated scaly plaque on the extensor surface of the elbow.
O | No pustules or signs of secondary infection are present.
A | The distribution and appearance are consistent with plaque psoriasis.
P | Apply the steroid ointment thinly once daily for two weeks.
P | Use the emollient as often as you need it.
P | I will refer you to dermatology if there is no improvement.

---

## Totals

| Label | Count |
|---|---|
| O — Objective | 15 |
| A — Assessment | 8 |
| P — Plan | 15 |
| X — should not appear | 18 |
