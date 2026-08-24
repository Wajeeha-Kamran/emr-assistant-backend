"""
Combination 0 - Baseline: Whisper base.en + pyannote 3.1.

This is what the backend runs today. Its numbers are the ones every other
combination is judged against, so it is run through the same code as the rest
rather than quoting the figures already in the report.

Run from the repository root:
    .venv\Scripts\python.exe scripts/combinations/combo_0.py
"""
from common import Combination, run

COMBINATION = Combination(
    number=0,
    asr="whisper",
    asr_model="base.en",
    diarizer="pyannote",
    why="The current system. Everything else is compared against this.",
    hyper={
        "whisper_model": 'base.en (74M)',
        "language": 'en',
        "word_timestamps": True,
        "diarizer": 'pyannote/speaker-diarization-3.1',
        "num_speakers": 2,
        "smoothing": 'majority of 3 neighbouring words',
        "doctor_identification": 'question-count majority vote',
        "device": 'cpu',
    },
)

if __name__ == "__main__":
    run(COMBINATION)
