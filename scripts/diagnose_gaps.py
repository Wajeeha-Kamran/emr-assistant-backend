"""
Diagnostic: what gaps actually exist between Whisper segments?

The diarization heuristic alternates speaker when
    segment[n].start - segment[n-1].end >= DIARIZATION_PAUSE_THRESHOLD

Evaluation showed it never alternates — every segment is labelled DOCTOR.
This script prints the real gap distribution so we can say definitively
whether ANY threshold value could make the heuristic work, rather than
guessing at one.

Usage:
    python -m scripts.diagnose_gaps
"""

import os
import sys

EVIDENCE_DIR = os.path.join("docs", "evidence")


def main() -> None:
    from app.services.asr_service import ASRService
    from app.core.config import settings

    threshold = settings.DIARIZATION_PAUSE_THRESHOLD
    print(f"Configured DIARIZATION_PAUSE_THRESHOLD = {threshold}s\n")

    all_gaps = []

    for n in (1, 2, 3, 4):
        wav = os.path.join(EVIDENCE_DIR, f"consult_{n}.wav")
        if not os.path.exists(wav):
            continue

        print(f"--- consult_{n}.wav ---", flush=True)
        segments = ASRService.transcribe_audio(wav).get("segments", [])

        gaps = []
        for prev, cur in zip(segments, segments[1:]):
            if prev.get("end") is not None and cur.get("start") is not None:
                gaps.append(cur["start"] - prev["end"])

        if not gaps:
            print("  no gaps computable\n")
            continue

        all_gaps.extend(gaps)
        over = [g for g in gaps if g >= threshold]
        print(f"  segments            {len(segments)}")
        print(f"  gaps measured       {len(gaps)}")
        print(f"  min / mean / max    {min(gaps):.3f}s / "
              f"{sum(gaps)/len(gaps):.3f}s / {max(gaps):.3f}s")
        print(f"  gaps >= {threshold}s        {len(over)}  "
              f"<-- number of times the speaker would flip")
        print()

    if not all_gaps:
        sys.exit("No audio evaluated.")

    print("=" * 58)
    print("OVERALL")
    print("=" * 58)
    print(f"  total gaps          {len(all_gaps)}")
    print(f"  min                 {min(all_gaps):.3f}s")
    print(f"  max                 {max(all_gaps):.3f}s")
    print(f"  mean                {sum(all_gaps)/len(all_gaps):.3f}s")
    print()
    print("  flips at various thresholds:")
    for t in (2.0, 1.5, 1.0, 0.5, 0.3, 0.2, 0.1, 0.05, 0.01):
        n_over = len([g for g in all_gaps if g >= t])
        print(f"    >= {t:>4}s : {n_over:>4} flips")
    print()
    print("  Roughly 66 real speaker changes exist across the four scripts")
    print("  (16+17+17+16 turns). Compare that with the flip counts above.")
    print()
    print("  If no threshold produces a flip count anywhere near 66, the")
    print("  heuristic cannot work at any setting and the failure is")
    print("  structural, not a tuning problem.")


if __name__ == "__main__":
    main()
