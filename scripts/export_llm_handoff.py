r"""
Freeze the classifier's selections so Colab does not have to run ClinicalBERT.

WHY A HANDOFF FILE
The LLM comparison needs the sentences the extractive classifier chose for each
section -- that is the hybrid contract's input. Producing them requires
Bio_ClinicalBERT, torch and the whole backend environment. Reproducing that
inside a Colab notebook whose only real job is running one language model at a
time invites exactly the dependency conflicts notebooks 02 and 04 were written
to avoid.

So the selections are computed once here, on the machine where the pipeline is
already known to work, and committed. The notebook reads them. Every model is
then handed byte-identical input, which is what makes the comparison between
models mean anything.

The file also carries the extractive rendering of those same selections, so the
control is in the same artefact as the thing it controls for, and the labelled
ground truth, so nothing has to be re-parsed in the notebook.

Usage:
    .\.venv312\Scripts\python -m scripts.export_llm_handoff
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OUT = os.path.join("docs", "evidence", "benchmarks", "llm_handoff.json")


def main() -> int:
    from scripts.evaluate_soap import (
        SCRIPTS_MD, EXPECTED_MD, parse_scripts, parse_expected,
    )
    from app.services.soap_service import SOAPService

    scripts = parse_scripts(SCRIPTS_MD)
    expected = parse_expected(EXPECTED_MD)
    if not scripts or not expected:
        print("FATAL: nothing parsed.")
        return 1

    payload = {
        "note": "Selections frozen by scripts/export_llm_handoff.py. Every "
                "model in notebooks/07 is given exactly these sentences.",
        "selections": {},
        "extractive": {},
        "expected": {},
    }

    for n in sorted(scripts):
        sections = SOAPService.select_sections(scripts[n])
        payload["selections"][str(n)] = sections
        payload["extractive"][str(n)] = SOAPService.render_extractive(sections)
        payload["expected"][str(n)] = [
            {"label": label, "sentence": sentence}
            for label, sentence in expected.get(n, [])
        ]
        counts = {k: len(v) for k, v in sections.items()}
        print(f"  script {n}: {counts}, {len(payload['expected'][str(n)])} labelled")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"\nwritten: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
