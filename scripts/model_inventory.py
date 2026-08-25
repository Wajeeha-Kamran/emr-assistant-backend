"""Print every model the system loads, with its measured parameter count and
the settings it is run at.

Why this is a script and not a table typed into the report: a table goes stale
the moment a setting changes, and nobody notices. This reads the counts out of
the weights actually installed and the settings out of app.core.config, so the
numbers in the report can always be regenerated and checked.

Run from the repository root:

    .\\.venv\\Scripts\\python.exe -m scripts.model_inventory

Nothing here is quoted from documentation or from memory. Every parameter count
is summed from weights loaded on this machine. Where a figure could not be
measured, the script says so rather than substituting a published one - a total
that silently omits a component is worse than no total.

Models evaluated in Colab but never deployed (Whisper medium, NVIDIA Sortformer,
NVIDIA Parakeet) are not installed here, so their parameter counts cannot be
measured. What *was* measured for them - accuracy and peak VRAM on a Tesla T4 -
is read out of docs/evidence/benchmarks/ at the end.
"""

import csv
import json
import os
import re
import sys
from decimal import ROUND_HALF_UP, Decimal

import torch

BENCHMARKS = os.path.join("docs", "evidence", "benchmarks")

# Types that are never worth descending into, and are common enough inside a
# loaded pipeline that walking them wastes real time.
_OPAQUE = (str, bytes, bytearray, int, float, bool, complex, type(None), torch.Tensor)


def _count(module: torch.nn.Module) -> int:
    return sum(p.numel() for p in module.parameters())


def _fmt(n: int) -> str:
    return f"{n:,} ({n / 1e6:.1f}M)"


def _collect(obj, path, depth, visited, found, counted):
    """Find every distinct torch module reachable from `obj`.

    pyannote's SpeakerDiarization is a Pipeline, not an nn.Module, and it keeps
    its segmentation and embedding models inside plain dictionaries and wrapper
    objects. There is no public API that reports what it loaded, so the object
    graph is walked - through dicts and sequences as well as attributes, which
    an earlier version of this script did not do and consequently found nothing.

    `counted` holds the id() of every module already added, so a model reachable
    by two paths is counted once.
    """
    if depth > 6 or isinstance(obj, _OPAQUE):
        return
    oid = id(obj)
    if oid in visited:
        return
    visited.add(oid)

    if isinstance(obj, torch.nn.Module):
        if oid not in counted:
            counted.add(oid)
            found[path] = _count(obj)
        # Its parameters are all counted; descending would double-count.
        return

    if isinstance(obj, dict):
        for key, value in obj.items():
            _collect(value, f"{path}[{key!r}]", depth + 1, visited, found, counted)
        return

    if isinstance(obj, (list, tuple, set, frozenset)):
        for i, value in enumerate(obj):
            _collect(value, f"{path}[{i}]", depth + 1, visited, found, counted)
        return

    attrs = getattr(obj, "__dict__", None)
    if isinstance(attrs, dict):
        for key, value in attrs.items():
            if key.startswith("__"):
                continue
            _collect(value, f"{path}.{key.lstrip('_')}", depth + 1, visited, found, counted)


def _describe_shape(obj) -> str:
    """What the pipeline object actually holds, printed when the walk finds nothing.

    Guessing twice at the same object is how the first version of this script
    reported zero. If the walk fails again, this prints enough to fix it without
    another round trip.
    """
    lines = [f"    object type: {type(obj).__module__}.{type(obj).__name__}"]
    attrs = getattr(obj, "__dict__", None)
    if not isinstance(attrs, dict):
        lines.append("    no __dict__ - the object uses __slots__ or a C extension")
        return "\n".join(lines)
    for key in sorted(attrs):
        value = attrs[key]
        kind = f"{type(value).__module__}.{type(value).__name__}"
        extra = ""
        if isinstance(value, dict):
            extra = f"  keys={sorted(map(str, value.keys()))[:8]}"
        lines.append(f"    {key:<28} {kind}{extra}")
    return "\n".join(lines)


def _role(path: str) -> str:
    """A readable name for a sub-model, derived from where it sits in the pipeline.

    Derived, not looked up: the label comes from the attribute the pipeline
    itself stores the model under, so it cannot drift from what was measured.
    """
    lowered = path.lower()
    if "embedding" in lowered:
        return "speaker embedding"
    if "segmentation" in lowered:
        return "segmentation" + (" (conversion)" if "conversion" in lowered else "")
    return path


def _num(value, default=float("nan")) -> float:
    """Parse a CSV cell as a float.

    The two comparison files were written by different cells and round
    differently - 88.3 in one, 89.02 in the other. Parsing and reformatting
    here means the table has one precision throughout instead of implying
    that some figures are more exact than others.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _r1(value: float) -> str:
    """One decimal place, rounding halves upward.

    Python's default rounds halves to even, so 99.85 prints as 99.8 while
    99.875 prints as 99.9. Two figures a reader expects to match then differ
    by a tenth for no visible reason.
    """
    return str(Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _sort_key(label: str):
    """Order by run number, and noise runs loudest-first rather than alphabetically.

    A plain string sort puts 10 dB before 20 dB before 5 dB, which reads as
    though the sweep went in that order. It did not.
    """
    run = label.split(".")[0].zfill(2)
    snr = re.search(r"(\d+)\s*dB", label)
    return (run, -int(snr.group(1)) if snr else 0, label)


def _read_csv(name):
    path = os.path.join(BENCHMARKS, name)
    if not os.path.exists(path):
        return None
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main() -> int:
    from app.core.config import settings

    measured = {}
    incomplete = []

    print("=" * 76)
    print("DEPLOYED MODELS - parameter counts summed from the installed weights")
    print("=" * 76)
    print()

    # ---- speech recognition ---------------------------------------------
    import whisper

    asr = whisper.load_model(settings.WHISPER_MODEL_NAME)
    measured["whisper"] = _count(asr)
    print(f"Speech recognition   openai-whisper {settings.WHISPER_MODEL_NAME}")
    print(f"                     {_fmt(measured['whisper'])} parameters")
    print("                     English-only checkpoint, word_timestamps=True")
    print("                     no fine-tuning; weights used as published")
    print()
    del asr

    # ---- speaker diarization --------------------------------------------
    try:
        from app.ml.pyannote_engine import MODEL_ID, PyannoteEngine

        pipeline = PyannoteEngine.get_instance().pipeline
        parts = {}
        _collect(pipeline, "pipeline", 0, set(), parts, set())

        # Layers with no weights (reshapes, conversions) are real modules but
        # contribute nothing, and listing them as "0 (0.0M)" reads like a
        # measurement that failed rather than a layer that has no parameters.
        weightless = sorted(name for name, count in parts.items() if count == 0)
        parts = {name: count for name, count in parts.items() if count > 0}

        print(f"Speaker diarization  {MODEL_ID}")
        if parts:
            measured["pyannote"] = sum(parts.values())
            print(f"                     {_fmt(measured['pyannote'])} parameters "
                  f"across {len(parts)} sub-models")
            for name, count in sorted(parts.items(), key=lambda kv: -kv[1]):
                print(f"                       {_role(name):<22} {_fmt(count)}")
            if weightless:
                print(f"                     ({len(weightless)} weightless layer(s) omitted: "
                      f"{', '.join(_role(n) for n in weightless)})")
        else:
            incomplete.append("pyannote diarization")
            print("                     NOT MEASURED - the walk found no torch module.")
            print("                     What the pipeline object actually holds:")
            print(_describe_shape(pipeline))
        print("                     run with num_speakers=2 (a consultation has two)")
        print()
    except Exception as exc:  # noqa: BLE001 - this is a report, not control flow
        incomplete.append("pyannote diarization")
        print(f"Speaker diarization  NOT LOADED: {type(exc).__name__}: {exc}")
        print("                     needs HF_TOKEN and the accepted model licences")
        print()

    # ---- clinical language model ----------------------------------------
    from app.ml.clinicalbert_engine import ClinicalBERTEngine

    bert = ClinicalBERTEngine.get_instance().model
    measured["clinicalbert"] = _count(bert)
    print("SOAP classification  emilyalsentzer/Bio_ClinicalBERT")
    print(f"                     {_fmt(measured['clinicalbert'])} parameters")
    print("                     mean-pooled sentence embeddings; no classifier head is")
    print("                     trained - sentences are placed by embedding similarity")
    print("                     combined with speech-act rules")
    print()
    print("Code suggestion      emilyalsentzer/Bio_ClinicalBERT (the same weights, reused)")
    print("                     cosine similarity against the reference code set;")
    print("                     ICD-10 matched from Assessment, CPT from Plan")
    print("                     counted once above, not twice")
    print()

    if incomplete:
        print(f"NO TOTAL PRINTED     {', '.join(incomplete)} could not be measured, and a")
        print("                     total that omits a component would be misleading.")
    else:
        print(f"TOTAL DEPLOYED       {_fmt(sum(measured.values()))} parameters")
    print()

    # ---- settings --------------------------------------------------------
    print("=" * 76)
    print("RUNTIME SETTINGS  (app/core/config.py)")
    print("=" * 76)
    print()
    for name in (
        "WHISPER_MODEL_NAME",
        "ASR_TIMEOUT_FLOOR_SECONDS",
        "ASR_TIMEOUT_FACTOR",
        "NLP_TIMEOUT_SECONDS",
        "ATTENTION_GRACE_MINUTES",
        "ATTENTION_STALL_BUFFER_SECONDS",
        "RETENTION_WINDOW_MINUTES",
        "RETENTION_SWEEP_INTERVAL_SECONDS",
    ):
        if hasattr(settings, name):
            print(f"  {name:<34} {getattr(settings, name)}")
    print(f"  {'diarization num_speakers':<34} 2")
    print(f"  {'code suggestions top_k':<34} 5   (per code type)")
    print()

    _print_comparison()
    return 0


def _print_comparison() -> None:
    """The Colab comparison table.

    Separated from main() so it can be exercised against the CSVs without
    loading three models first.
    """
    print("=" * 76)
    print("MODEL COMPARISON  -  every combination measured, on one Tesla T4")
    print("=" * 76)
    print()
    print("  Whisper medium, NVIDIA Sortformer and NVIDIA Parakeet are not installed")
    print("  on this machine, so no parameter count is quoted for them. Everything")
    print("  below is read from docs/evidence/benchmarks/ and was measured, not cited.")
    print()

    rows = {}
    missing = []

    for name in ("benchmark_comparison.csv", "nemo_comparison.csv"):
        data = _read_csv(name)
        if data is None:
            missing.append(name)
            continue
        for r in data:
            rows[r["run"]] = {
                "word": _num(r.get("word_acc_mean")),
                "spk": _num(r.get("speaker_acc_mean")),
                "vram": _num(r.get("vram_peak_gb")),
            }

    # Run 5 was never written to a comparison file, only a per-script detail
    # file, so it is aggregated here rather than left out of the table. Peak
    # VRAM is the maximum across scripts, not the mean: the question a VRAM
    # figure answers is whether it fits on a given card.
    detail = _read_csv("base_sortformer_detail.csv")
    if detail:
        label = detail[0]["run"]
        rows[label] = {
            "word": sum(_num(r["word_acc"]) for r in detail) / len(detail),
            "spk": sum(_num(r["speaker_acc"]) for r in detail) / len(detail),
            "vram": max(_num(r["vram_peak_gb"]) for r in detail),
        }
    else:
        missing.append("base_sortformer_detail.csv")

    if missing:
        print(f"  MISSING: {', '.join(missing)} - run from the repository root")
        print()

    # Two columns cannot be reported honestly for the noise runs, and the
    # reasons are printed under the table rather than left for a reader to
    # discover. Suppressing a number silently would be worse than printing it.
    NOISE_PREFIX = "4. "
    DEPLOYED = "0. base.en + pyannote"

    header = f"  {'combination':<40}{'word %':>9}{'speaker %':>11}{'peak VRAM':>12}"
    print(header)
    print("  " + "-" * (len(header) - 2))

    for label in sorted(rows, key=_sort_key):
        r = rows[label]
        noise = label.startswith(NOISE_PREFIX)
        shown = label + ("   <- DEPLOYED" if label == DEPLOYED else "")
        if "synthetic" in label:
            shown = label + "   [c]"
        word = _r1(r['word'])
        spk = "see [a]" if noise else _r1(r['spk'])
        vram = "see [b]" if noise else f"{r['vram']:.2f} GB"
        print(f"  {shown:<40}{word:>9}{spk:>11}{vram:>12}")

    print()
    print("  [a] Speaker accuracy under noise is withheld. It was measured as 99.1 /")
    print("      99.0 / 99.4 at 20 / 10 / 5 dB, against 77.6 on the same audio clean.")
    print("      Noise did not improve diarization: it stopped two voices merging on")
    print("      script 2, flipping an already-wrong labelling to a right one. A")
    print("      fragile recording changing its mind is not a robustness result, and")
    print("      the comparison report discarded it. Sortformer, which has no such")
    print("      failure to repair, was re-run over the same sweep in notebook 06 and")
    print("      held at 99.6 / 99.6 / 99.4 / 99.3 from clean to 5 dB.")
    print()
    print("  [b] Peak VRAM on the noise runs is not this combination's footprint.")
    print("      They ran base.en, but Whisper medium was still resident in the same")
    print("      process from the run above, and max_memory_allocated counts every")
    print("      allocation, not only the model under test. The clean base.en +")
    print("      pyannote figure of 2.00 GB is the one that means anything.")
    print()
    print("  [c] Synthetic voices, not the human recordings. Text-to-speech gives")
    print("      each speaker a perfectly steady voice and clean turn boundaries, so")
    print("      95.1% word and 99.8% speaker measure an easier problem, not a better")
    print("      system. It is in the table because the comparison report reports every")
    print("      run, but it is not comparable with the rows around it.")
    print()

    for name in ("nemo_hardware.json", "base_sortformer_hardware.json"):
        path = os.path.join(BENCHMARKS, name)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                hw = json.load(f)
            print(f"  Hardware, identical for every run: {hw.get('gpu')}, "
                  f"{hw.get('gpu_vram_gb')} GB VRAM, {hw.get('ram_total_gb')} GB RAM,")
            print(f"  {hw.get('cpu_cores_physical')} physical CPU core, "
                  f"torch {hw.get('torch')}, CUDA {hw.get('cuda')}.")
            break
    print()
    print("  The deployed system runs on CPU, so these GPU timings measure the models,")
    print("  not the deployed pipeline. CPU end-to-end timings are in")
    print("  docs/evidence/robustness/.")
    print()
    print("  Means only. Per-script figures are in the *_detail.csv files beside these,")
    print("  and they matter: 77.6% speaker is three near-perfect recordings and one")
    print("  collapse, not four mediocre ones.")


if __name__ == "__main__":
    sys.exit(main())
