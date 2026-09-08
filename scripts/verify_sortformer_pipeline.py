r"""
Prove the running backend actually uses Sortformer, end to end.

The integration is easy to get wrong in a way that is invisible: if NeMo fails
to import, DiarizationService catches the error, logs it, and falls back to
pyannote. Nothing crashes and the API still answers, so a passing test suite
says nothing about which diarizer ran.

This runs the real ASR engine and the real DiarizationService on consult_2.wav
-- the recording where pyannote swaps both speakers (12.4% speaker accuracy) --
and fails loudly unless the log line says the turns came from sortformer.

    .\.venv312\Scripts\python scripts\verify_sortformer_pipeline.py
"""

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

AUDIO = os.path.join("docs", "evidence", "human_distinct", "consult_2.wav")


class Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def main() -> int:
    if not os.path.exists(AUDIO):
        print(f"FAIL: {AUDIO} not found. Run from the repository root.")
        return 1

    capture = Capture()
    logging.basicConfig(level=logging.INFO)
    logging.getLogger().addHandler(capture)

    from app.core.config import settings
    print(f"DIARIZATION_METHOD = {settings.DIARIZATION_METHOD}")

    from app.ml.engine_factory import get_asr_engine
    from app.services.diarization_service import DiarizationService

    print("transcribing (Whisper base.en, CPU -- takes a minute)...")
    result = get_asr_engine().transcribe(AUDIO)
    segments = result.get("segments") or []
    print(f"  {len(segments)} segments")

    print("diarizing...")
    labelled = DiarizationService.diarize_segments(segments, audio_path=AUDIO)

    used = None
    for line in capture.lines:
        if line.startswith("Diarization ("):
            used = line[len("Diarization ("):].split(")")[0]
    fell_back = [l for l in capture.lines if "falling back" in l.lower()]

    print()
    for seg in labelled[:8]:
        text = (seg.get("text") or "").strip()
        print(f"  {seg.get('speaker_role'):<8} {text[:70]}")
    if len(labelled) > 8:
        print(f"  ... {len(labelled) - 8} more turns")

    roles = {s.get("speaker_role") for s in labelled}
    print(f"\nturns: {len(labelled)}   roles: {sorted(roles)}   engine: {used}")

    if fell_back:
        print("\nFAIL: the service fell back. Reasons logged:")
        for line in fell_back:
            print(f"  {line}")
        return 1
    if used != "sortformer":
        print(f"\nFAIL: turns came from '{used}', not sortformer.")
        return 1
    if len(roles) < 2:
        print(f"\nFAIL: only one role assigned ({roles}); both speakers merged.")
        return 1

    print("\nPASS: Sortformer produced the speaker turns, both roles present.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
