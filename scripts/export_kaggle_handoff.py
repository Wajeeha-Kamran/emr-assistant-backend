r"""
Freeze the classifier's selections for the Kaggle consultations.

WHY THIS EXISTS
The LLM comparison so far ran on four consultations written by the person
evaluating them: short, clean, and scripted. Every faithfulness figure in
claude/llm_soap_comparison_results.md rests on that one small, tidy sample.

The Kaggle recordings are real consultations -- 48 to 108 turns each against
the reference scripts' 16 or 17, real hesitation, and real ASR damage still in
the transcript ("located on the last side of my chest" is "left side"). If the
fabrication that MedGemma and Mistral produced is a property of generation,
it should appear here too. If it was an artefact of four clean scripts, it
should not.

WHAT CAN AND CANNOT BE MEASURED HERE
Nobody has labelled these sentence by sentence the way docs/evidence/
soap_expected.md labels the reference scripts, so there is no ground truth to
score placement against.

    clinical accuracy   NOT measurable  -- needs a reference note
    noise rate          NOT measurable  -- needs sentences labelled as noise

    novel content       measurable
    omission            measurable
    values not in source measurable
    unsupported sentences measurable
    polarity review     measurable

The split falls in a useful place. Everything that needs a reference is
blocked; everything that asks "is this note supported by the transcript it came
from" works, because that question is answered by comparing the note against
its own source. Those are the safety metrics, and the fabrication finding is
the one that most needs testing on data the author did not write.

Usage:
    .\.venv312\Scripts\python -m scripts.export_kaggle_handoff
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SRC = os.path.join("docs", "evidence", "kaggle_outputs.json")
OUT = os.path.join("docs", "evidence", "benchmarks", "llm_handoff_kaggle.json")


def main() -> int:
    from app.services.soap_service import SOAPService

    if not os.path.exists(SRC):
        print(f"FATAL: {SRC} not found. Run from the repository root.")
        return 1

    with open(SRC, encoding="utf-8") as f:
        records = json.load(f)

    payload = {
        "note": "Selections frozen by scripts/export_kaggle_handoff.py from the "
                "Kaggle consultations. No ground-truth labels exist for these, "
                "so only the faithfulness metrics apply.",
        "ground_truth": False,
        "selections": {},
        "extractive": {},
    }

    for rec in records:
        key = rec["audio_file"].rsplit(".", 1)[0]

        # kaggle_outputs.json calls the field "speaker"; SOAPService expects
        # "speaker_role". Mapping here rather than loosening the service keeps
        # the production contract single-valued.
        turns = [
            {"speaker_role": t.get("speaker"), "text": t.get("text", "")}
            for t in rec.get("transcript", [])
            if t.get("speaker") in ("DOCTOR", "PATIENT")
        ]
        if not turns:
            print(f"  {key}: no usable turns, skipped")
            continue

        sections = SOAPService.select_sections(turns)
        payload["selections"][key] = sections
        payload["extractive"][key] = SOAPService.render_extractive(sections)
        print(f"  {key}: {len(turns)} turns -> "
              f"{ {k: len(v) for k, v in sections.items()} }")

    if not payload["selections"]:
        print("FATAL: nothing selected.")
        return 1

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"\nwritten: {OUT}")
    print(f"consultations: {len(payload['selections'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
