r"""
Run the REAL LLM renderer, including the grounding gate.

WHY THIS SCRIPT EXISTS
Everything measured about MedGemma so far was measured in Colab, by a notebook
that defines its own generation loop. It borrows the production PROMPT and one
helper, and never calls LLMSoapEngine.render(). So as of 5 October 2026:

    LLMSoapEngine.render()   had never executed
    LLMSoapEngine._gate()    had never executed, anywhere

The numbers in claude/llm_soap_comparison_results.md are ungated raw model
output, and the "sections the gate rejects" row was computed afterwards by
applying the scoring function to saved notes. That is a measurement of what the
gate WOULD have done, not a record of it running.

This script closes that gap. It calls the production engine on the frozen
classifier selections, so the code path exercised here is the same one the
backend uses when SOAP_ENGINE is not "extractive".

WHAT IT REPORTS
For every section, whether the output is the model's prose or the verbatim
fallback, and why. Fallback is detected by comparing against
SOAPService.render_extractive -- the engine returns text either way, and a note
that quietly degraded must never be mistaken for a generated one.

It also times each section, which is the CPU latency measurement that has never
been taken.

USAGE
    # GPU (Colab), the four scripted consultations
    python -m scripts.run_llm_engine --model google/medgemma-4b-it

    # one consultation, one section -- use this first on CPU
    python -m scripts.run_llm_engine --model google/medgemma-4b-it \
        --consultation 1 --section objective

    # the real Kaggle consultations
    python -m scripts.run_llm_engine --model google/medgemma-4b-it \
        --handoff docs/evidence/benchmarks/llm_handoff_kaggle.json

    # prove the gate is doing something: run again with it off and diff
    python -m scripts.run_llm_engine --model google/medgemma-4b-it --no-gate

ON CPU, START SMALL. A 4B model in bfloat16 needs roughly 8 GB of RAM and
generates a few tokens per second. Run one section before running a whole note.
"""

import argparse
import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SECTIONS = ("subjective", "objective", "assessment", "plan")
DEFAULT_HANDOFF = os.path.join("docs", "evidence", "benchmarks", "llm_handoff.json")


def _ensure_env() -> None:
    """
    Satisfy the settings object without a .env file.

    app/core/config.py requires APP_ENV, DATABASE_URL, SIMULATED_EMR_URL,
    JWT_SECRET and ENCRYPTION_KEY, and fails loudly if they are missing -- which
    is correct for the service and unhelpful here. This script touches no
    database, no auth and no encryption; it loads a JSON file and runs a model.
    Placeholders are filled in only where the variable is genuinely absent, so a
    real .env always wins.
    """
    placeholders = {
        "APP_ENV": "evaluation",
        "DATABASE_URL": "postgresql://unused/unused",
        "SIMULATED_EMR_URL": "http://localhost:8001",
        "JWT_SECRET": "unused-in-this-script",
        "ENCRYPTION_KEY": "dGhpcy1rZXktaXMtbm90LXVzZWQtaW4tdGhpcy1zY3JpcHQ=",
    }
    for key, value in placeholders.items():
        os.environ.setdefault(key, value)


def _order(keys):
    """Scripted handoffs key on "1".."4"; Kaggle keys on "CAR0001"."""
    return sorted(keys, key=lambda k: (0, int(k), "") if str(k).isdigit()
                  else (1, 0, str(k)))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", required=True,
                    help="e.g. google/medgemma-4b-it")
    ap.add_argument("--handoff", default=DEFAULT_HANDOFF)
    ap.add_argument("--consultation", default=None,
                    help="only this key, e.g. 1 or CAR0001")
    ap.add_argument("--section", default=None, choices=SECTIONS,
                    help="only this section")
    ap.add_argument("--no-gate", action="store_true",
                    help="disable the grounding gate, to see raw output")
    ap.add_argument("--dtype", default=None,
                    choices=("auto", "bfloat16", "float32"))
    ap.add_argument("--max-new-tokens", type=int, default=None)
    ap.add_argument("--out", default=None, help="write the notes to this JSON")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)-8s %(name)s: %(message)s",
    )

    _ensure_env()

    # Settings must be adjusted BEFORE the engine is constructed: the engine
    # reads LLM_MODEL_ID, the gate flag and the threshold in __init__.
    from app.core.config import settings
    settings.LLM_MODEL_ID = args.model
    if args.no_gate:
        settings.LLM_GROUNDING_GATE = False
    if args.dtype:
        settings.LLM_DTYPE = args.dtype
    if args.max_new_tokens:
        settings.LLM_MAX_NEW_TOKENS = args.max_new_tokens

    if not os.path.exists(args.handoff):
        print(f"FATAL: {args.handoff} not found. Run from the repository root.")
        return 1
    with open(args.handoff, encoding="utf-8") as fh:
        data = json.load(fh)
    selections = data["selections"]

    keys = _order(selections)
    if args.consultation:
        if args.consultation not in selections:
            print(f"FATAL: {args.consultation!r} is not in {args.handoff}. "
                  f"Available: {', '.join(keys)}")
            return 1
        keys = [args.consultation]
    wanted = (args.section,) if args.section else SECTIONS

    from app.ml.llm_soap_engine import LLMSoapEngine, LLMSoapEngineError
    from app.services.soap_service import SOAPService

    print(f"\nloading {args.model} "
          f"(gate {'OFF' if args.no_gate else 'ON'})", flush=True)
    load_start = time.time()
    try:
        engine = LLMSoapEngine.get_instance()
    except LLMSoapEngineError as e:
        print(f"\nFATAL: {e}")
        return 1
    print(f"loaded on {engine.device} as {engine.dtype} "
          f"in {time.time() - load_start:.1f}s\n", flush=True)

    notes = {}
    rows = []
    for key in keys:
        picked = {name: selections[key].get(name) or []
                  for name in wanted}
        verbatim = SOAPService.render_extractive(picked)

        t0 = time.time()
        rendered = engine.render(picked)
        elapsed = time.time() - t0

        notes[key] = rendered
        print(f"=== {key}  ({elapsed:.1f}s for {len(wanted)} section(s)) ===")
        for name in wanted:
            source = picked[name]
            out = rendered[name]
            if not source:
                state = "empty"
            elif out == verbatim[name]:
                state = "FELL BACK to verbatim"
            else:
                state = "rewritten by the model"
            print(f"  [{name}] {len(source)} source sentence(s) -> {state}")
            print(f"      {out[:220]}")
            rows.append({"consultation": key, "section": name,
                         "source_sentences": len(source), "state": state,
                         "seconds": round(elapsed, 1)})
        print()

    total = len(rows)
    fell_back = sum(1 for r in rows if r["state"].startswith("FELL BACK"))
    rewritten = sum(1 for r in rows if r["state"] == "rewritten by the model")
    print("================ SUMMARY ================")
    print(f"  model            {args.model}")
    print(f"  device / dtype   {engine.device} / {engine.dtype}")
    print(f"  gate             {'disabled' if args.no_gate else 'enabled'}")
    print(f"  sections         {total}")
    print(f"  rewritten        {rewritten}")
    print(f"  fell back        {fell_back}")
    print("\nA section that fell back is NOT a failure of the system -- it is"
          "\nthe gate refusing output the transcript does not support, which is"
          "\nwhat it is for. Read the WARNING lines above to see which sentence"
          "\ntriggered each one.")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(notes, fh, indent=2)
        print(f"\nwritten: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
